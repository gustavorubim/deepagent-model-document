"""CLI entrypoint for MRM deep agent."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape

from mrm_deepagent.agent_runtime import build_agent
from mrm_deepagent.config import ensure_output_root, load_config
from mrm_deepagent.context_manager import load_context, merge_missing_items, write_context
from mrm_deepagent.draft_generator import (
    build_tools,
    collect_missing_items,
    generate_draft,
    write_run_artifacts,
)
from mrm_deepagent.draft_parser import parse_draft_markdown
from mrm_deepagent.exceptions import (
    AlreadyAppliedError,
    DraftParseError,
    MissingRuntimeConfigError,
    TemplateValidationError,
    UnsupportedTemplateError,
)
from mrm_deepagent.repo_indexer import index_repo
from mrm_deepagent.template_applier import apply_draft_to_template
from mrm_deepagent.template_parser import parse_template, validate_template
from mrm_deepagent.tracing import RunTraceCollector

app = typer.Typer(help="Deep agent for governance document drafting and application.")
console = Console()


def _vprint(enabled: bool, message: str) -> None:
    """Print verbose progress messages."""
    if enabled:
        console.print(f"[cyan]verbose:[/cyan] {escape(message)}")


def _configure_trace_streaming(trace: RunTraceCollector, enabled: bool) -> None:
    """Enable live trace-event printing in verbose mode."""
    if not enabled:
        trace.set_live_sink(None)
        return

    def _sink(event: dict[str, Any]) -> None:
        section = event.get("section_id") or "-"
        attempt = event.get("attempt")
        payload = event.get("payload_format") or "-"
        duration = event.get("duration_ms")
        details = _truncate_details(str(event.get("details", "")))
        parts = [
            f"trace[{event.get('seq', '?')}]",
            f"{event.get('event_type', '')}",
            f"{event.get('component', '')}.{event.get('action', '')}",
            f"status={event.get('status', '')}",
            f"section={section}",
            f"attempt={attempt if attempt != '' else '-'}",
        ]
        if payload != "-":
            parts.append(f"payload={payload}")
        if duration != "":
            parts.append(f"duration_ms={duration}")
        if details:
            parts.append(f"details={details}")
        _vprint(True, " ".join(parts))

    trace.set_live_sink(_sink)


def _truncate_details(text: str, max_len: int = 240) -> str:
    value = text.strip()
    if len(value) <= max_len:
        return value
    return f"{value[: max_len - 3]}..."


@app.command("validate-template")
def validate_template_cmd(
    template: Annotated[Path, typer.Option(help="Path to template file (.docx or .md).")],
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--no-verbose", help="Enable detailed logs. Enabled by default."),
    ] = True,
) -> None:
    """Validate template marker correctness."""
    _vprint(verbose, f"Loading template: {template}")
    try:
        parsed = parse_template(template)
    except TemplateValidationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    _vprint(
        verbose,
        f"Parsed {len(parsed.sections)} sections "
        f"(format={parsed.template_format.value}). Running validation checks.",
    )
    errors = validate_template(parsed)
    if errors:
        console.print("[red]Template validation failed:[/red]")
        for error in errors:
            console.print(f"- {error}")
        raise typer.Exit(code=2)
    console.print(f"[green]Template valid.[/green] Sections: {len(parsed.sections)}")


@app.command("draft")
def draft_cmd(
    codebase: Annotated[Path, typer.Option(help="Path to codebase to analyze.")],
    template: Annotated[Path, typer.Option(help="Path to template file (.docx or .md).")],
    output_root: Annotated[str, typer.Option(help="Root output directory.")] = "outputs",
    context_file: Annotated[
        str | None,
        typer.Option(
            help=(
                "Path to missing-context markdown file. "
                "If omitted, defaults to contexts/<template-stem>-additional-context.md."
            )
        ),
    ] = None,
    model: Annotated[
        str,
        typer.Option(help="Gemini model name override."),
    ] = "gemini-3-flash-preview",
    section_retries: Annotated[
        int,
        typer.Option(help="Number of retries per section LLM call."),
    ] = 3,
    section_timeout_s: Annotated[
        int,
        typer.Option(help="Timeout in seconds per section LLM call."),
    ] = 90,
    config: Annotated[Path | None, typer.Option(help="Optional YAML config path.")] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--no-verbose", help="Enable detailed logs. Enabled by default."),
    ] = True,
) -> None:
    """Generate draft markdown from codebase and template."""
    trace = RunTraceCollector()
    _configure_trace_streaming(trace, verbose)
    try:
        _vprint(verbose, "Loading runtime configuration (YAML + CLI overrides).")
        runtime_config = load_config(
            config_path=config,
            overrides={
                "model": model,
                "output_root": output_root,
                "context_file": context_file,
            },
        )
    except MissingRuntimeConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3) from exc
    trace.log(
        event_type="run",
        component="cli",
        action="config_loaded",
        status="ok",
        details={
            "model": runtime_config.model,
        },
    )

    try:
        parsed_template = parse_template(template)
    except TemplateValidationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    _vprint(verbose, f"Template parsed with {len(parsed_template.sections)} sections.")
    trace.log(
        event_type="run",
        component="cli",
        action="template_parsed",
        status="ok",
        details={
            "sections": len(parsed_template.sections),
            "template_path": str(template),
            "template_format": parsed_template.template_format.value,
        },
    )
    errors = validate_template(parsed_template)
    if errors:
        for error in errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2)

    _vprint(
        verbose,
        "Gemini settings are configured directly in code (agent_runtime.py).",
    )
    _vprint(
        verbose,
        f"Section call policy: retries={section_retries}, timeout={section_timeout_s}s.",
    )

    _vprint(verbose, f"Indexing codebase files from: {codebase}")
    repo_index = index_repo(
        codebase_path=codebase,
        allowlist=runtime_config.repo_allowlist,
        denylist=runtime_config.repo_denylist,
    )
    _vprint(verbose, f"Indexed {len(repo_index.files)} text files.")
    trace.log(
        event_type="run",
        component="cli",
        action="repo_indexed",
        status="ok",
        details={
            "codebase": str(codebase),
            "file_count": len(repo_index.files),
            "template_format": parsed_template.template_format.value,
        },
    )
    configured_context = _configured_context_override(runtime_config.context_file)
    explicit_context = context_file if context_file is not None else configured_context
    context_path, legacy_context_path = _resolve_context_path(
        template_stem=parsed_template.template_stem or template.stem,
        explicit_context_path=explicit_context,
    )
    if legacy_context_path is not None:
        _vprint(
            verbose,
            f"Detected legacy context file '{legacy_context_path.name}'. "
            f"Migrating context into '{context_path.name}'.",
        )
    existing_context = load_context(context_path)
    if legacy_context_path is not None:
        legacy_context = load_context(legacy_context_path)
        existing_context = merge_missing_items(existing_context, legacy_context)
    _vprint(
        verbose,
        f"Loaded {len(existing_context)} context entries from {context_path}.",
    )
    trace.log(
        event_type="run",
        component="cli",
        action="context_loaded",
        status="ok",
        details={
            "context_path": str(context_path),
            "count": len(existing_context),
            "template_format": parsed_template.template_format.value,
        },
    )
    tools = build_tools(repo_index, existing_context, trace=trace)
    _vprint(verbose, f"Built {len(tools)} agent tools.")
    runtime = build_agent(
        runtime_config,
        tools,
        log=lambda message: _vprint(verbose, message),
        trace=trace,
    )
    _vprint(verbose, "Generating draft section-by-section with deep agent.")
    draft = generate_draft(
        parsed_template,
        repo_index,
        existing_context,
        runtime,
        retries=section_retries,
        timeout_s=section_timeout_s,
        progress_callback=lambda message: _vprint(verbose, message),
        trace=trace,
    )
    _vprint(verbose, f"Draft contains {len(draft.sections)} fillable sections.")

    run_dir = _make_run_dir(ensure_output_root(runtime_config.output_root))
    _vprint(verbose, f"Writing run artifacts into: {run_dir}")
    write_run_artifacts(run_dir, draft)

    merged_context = merge_missing_items(existing_context, collect_missing_items(draft))
    write_context(merged_context, context_path)
    _vprint(verbose, f"Context file updated with {len(merged_context)} total items.")
    trace.log(
        event_type="run",
        component="cli",
        action="draft_finished",
        status="ok",
        details={
            "run_dir": str(run_dir),
            "context_path": str(context_path),
            "template_format": parsed_template.template_format.value,
            "template_path": str(template),
            "output_path": str(run_dir / "draft.md"),
        },
    )
    trace_json = run_dir / "trace.json"
    trace_csv = run_dir / "trace.csv"
    trace.write_json(trace_json)
    trace.write_csv(trace_csv)
    _vprint(verbose, f"Trace artifacts written: {trace_json}, {trace_csv}")

    console.print(f"[green]Draft generated.[/green] {run_dir / 'draft.md'}")
    console.print(f"[green]Context updated.[/green] {context_path}")


@app.command("apply")
def apply_cmd(
    draft: Annotated[Path, typer.Option(help="Path to reviewed draft markdown.")],
    template: Annotated[Path, typer.Option(help="Path to template file (.docx or .md).")],
    output_root: Annotated[str, typer.Option(help="Root output directory.")] = "outputs",
    force: Annotated[bool, typer.Option(help="Allow apply to already-applied documents.")] = False,
    config: Annotated[Path | None, typer.Option(help="Optional YAML config path.")] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--no-verbose", help="Enable detailed logs. Enabled by default."),
    ] = True,
) -> None:
    """Apply reviewed draft markdown content into a copied template."""
    trace = RunTraceCollector()
    _configure_trace_streaming(trace, verbose)
    _vprint(verbose, "Loading runtime configuration.")
    runtime_config = load_config(
        config_path=config,
        overrides={"output_root": output_root},
    )
    try:
        _vprint(verbose, f"Parsing draft markdown: {draft}")
        parsed_draft = parse_draft_markdown(draft)
        _vprint(verbose, f"Parsed {len(parsed_draft.sections)} draft sections.")
    except DraftParseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc

    run_dir = _make_run_dir(ensure_output_root(runtime_config.output_root))
    try:
        template_format = _template_format_from_path(template)
    except UnsupportedTemplateError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=5) from exc
    out_doc = run_dir / f"applied-document.{_output_extension(template_format)}"
    _vprint(verbose, f"Applying draft to template copy: {out_doc}")
    configured_context = _configured_context_override(runtime_config.context_file)
    context_path, _legacy_context = _resolve_context_path(
        template_stem=template.stem,
        explicit_context_path=configured_context,
    )
    trace.log(
        event_type="run",
        component="cli",
        action="apply_start",
        status="start",
        details={
            "template_path": str(template),
            "template_format": template_format,
            "context_path": str(context_path),
            "output_path": str(out_doc),
        },
    )

    try:
        report = apply_draft_to_template(
            template,
            parsed_draft,
            out_doc,
            force=force,
            context_reference=str(context_path),
        )
    except (UnsupportedTemplateError, AlreadyAppliedError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=5) from exc

    unresolved_count = len(report.unresolved_section_ids)
    _vprint(verbose, f"Apply completed with {unresolved_count} unresolved sections.")
    trace.log(
        event_type="run",
        component="cli",
        action="apply_complete",
        status="ok",
        details={
            "template_path": str(template),
            "template_format": template_format,
            "context_path": str(context_path),
            "output_path": report.output_path,
            "unresolved_count": unresolved_count,
        },
    )
    trace.write_json(run_dir / "trace.json")
    trace.write_csv(run_dir / "trace.csv")
    console.print(f"[green]Applied document created.[/green] {report.output_path}")
    console.print(f"Unresolved sections: {unresolved_count}")


def _make_run_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / stamp
    suffix = 0
    while run_dir.exists():
        suffix += 1
        run_dir = root / f"{stamp}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _resolve_context_path(
    template_stem: str,
    explicit_context_path: str | None,
) -> tuple[Path, Path | None]:
    """Resolve context path, with per-template default and legacy migration handling."""
    if explicit_context_path:
        preferred_path = Path(explicit_context_path)
    else:
        normalized_stem = _slugify_template_stem(template_stem)
        preferred_path = Path("contexts") / f"{normalized_stem}-additional-context.md"

    legacy_path = preferred_path.with_name("additinal-context.md")
    if (
        preferred_path.name == "additional-context.md"
        and not preferred_path.exists()
        and legacy_path.exists()
    ):
        return preferred_path, legacy_path
    return preferred_path, None


def _configured_context_override(context_file_value: str) -> str | None:
    """Treat non-default config context value as an explicit override."""
    if context_file_value == "additional-context.md":
        return None
    return context_file_value


def _template_format_from_path(template_path: Path) -> str:
    suffix = template_path.suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    raise UnsupportedTemplateError(
        f"Unsupported template extension '{template_path.suffix}'. "
        "Supported extensions are .docx and .md."
    )


def _output_extension(template_format: str) -> str:
    if template_format == "docx":
        return "docx"
    if template_format == "markdown":
        return "md"
    return "txt"


def _slugify_template_stem(stem: str) -> str:
    normalized = stem.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "template"


def main() -> None:
    """Script entrypoint."""
    app()


if __name__ == "__main__":
    main()
