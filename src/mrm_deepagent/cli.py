"""CLI entrypoint for MRM deep agent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console

from mrm_deepagent.agent_runtime import build_agent
from mrm_deepagent.config import ensure_output_root, load_config
from mrm_deepagent.context_manager import load_context, merge_missing_items, write_context
from mrm_deepagent.docx_applier import apply_draft_to_template
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
    UnsupportedTemplateError,
)
from mrm_deepagent.repo_indexer import index_repo
from mrm_deepagent.template_parser import parse_template, validate_template
from mrm_deepagent.tracing import RunTraceCollector

app = typer.Typer(help="Deep agent for model risk document drafting and application.")
console = Console()


def _vprint(enabled: bool, message: str) -> None:
    """Print verbose progress messages."""
    if enabled:
        console.print(f"[cyan]verbose:[/cyan] {message}")


@app.command("validate-template")
def validate_template_cmd(
    template: Annotated[Path, typer.Option(help="Path to DOCX template.")],
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--no-verbose", help="Enable detailed logs. Enabled by default."),
    ] = True,
) -> None:
    """Validate template marker correctness."""
    _vprint(verbose, f"Loading template: {template}")
    parsed = parse_template(template)
    _vprint(verbose, f"Parsed {len(parsed.sections)} sections. Running validation checks.")
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
    template: Annotated[Path, typer.Option(help="Path to DOCX template.")],
    output_root: Annotated[str, typer.Option(help="Root output directory.")] = "outputs",
    context_file: Annotated[str, typer.Option(help="Path to missing-context markdown file.")] = (
        "additional-context.md"
    ),
    model: Annotated[str, typer.Option(help="Gemini model name override.")] = (
        "gemini-3-flash-preview"
    ),
    auth_mode: Annotated[
        Literal["api", "m2m"],
        typer.Option(help="Authentication mode: 'api' or 'm2m'."),
    ] = "api",
    vertexai: Annotated[
        bool | None,
        typer.Option(
            "--vertexai/--no-vertexai",
            help="Enable Vertex AI mode. If omitted, uses config/.env value.",
        ),
    ] = None,
    google_project: Annotated[
        str | None,
        typer.Option(help="Google Cloud project ID for Vertex AI."),
    ] = None,
    google_location: Annotated[
        str | None,
        typer.Option(help="Google Cloud location for Vertex AI."),
    ] = None,
    https_proxy: Annotated[
        str | None,
        typer.Option(help="HTTPS proxy URL (for example https://proxy.corp:8443)."),
    ] = None,
    ssl_cert_file: Annotated[
        str | None,
        typer.Option(help="Path to PEM certificate bundle for TLS verification."),
    ] = None,
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
    try:
        _vprint(verbose, "Loading runtime configuration (.env + YAML + CLI overrides).")
        runtime_config = load_config(
            config_path=config,
            overrides={
                "model": model,
                "output_root": output_root,
                "context_file": context_file,
                "auth_mode": auth_mode,
                "vertexai": vertexai,
                "google_project": google_project,
                "google_location": google_location,
                "https_proxy": https_proxy,
                "ssl_cert_file": ssl_cert_file,
            },
            require_api_key=True,
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
            "auth_mode": runtime_config.auth_mode.value,
            "vertexai": runtime_config.vertexai,
            "model": runtime_config.model,
        },
    )

    parsed_template = parse_template(template)
    _vprint(verbose, f"Template parsed with {len(parsed_template.sections)} sections.")
    trace.log(
        event_type="run",
        component="cli",
        action="template_parsed",
        status="ok",
        details={"sections": len(parsed_template.sections), "template": str(template)},
    )
    errors = validate_template(parsed_template)
    if errors:
        for error in errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=2)

    _vprint(
        verbose,
        "Auth settings: "
        f"mode={runtime_config.auth_mode.value}, "
        f"vertexai={runtime_config.vertexai}, "
        f"project={runtime_config.google_project or 'n/a'}, "
        f"location={runtime_config.google_location}, "
        f"proxy={'set' if runtime_config.https_proxy else 'unset'}, "
        f"cert={'set' if runtime_config.ssl_cert_file else 'unset'}.",
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
        details={"codebase": str(codebase), "file_count": len(repo_index.files)},
    )
    context_path, legacy_context_path = _resolve_context_path(Path(runtime_config.context_file))
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
        details={"context_path": str(context_path), "count": len(existing_context)},
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
        details={"run_dir": str(run_dir), "context_path": str(context_path)},
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
    template: Annotated[Path, typer.Option(help="Path to DOCX template.")],
    output_root: Annotated[str, typer.Option(help="Root output directory.")] = "outputs",
    force: Annotated[bool, typer.Option(help="Allow apply to already-applied documents.")] = False,
    config: Annotated[Path | None, typer.Option(help="Optional YAML config path.")] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--no-verbose", help="Enable detailed logs. Enabled by default."),
    ] = True,
) -> None:
    """Apply reviewed draft markdown content into copied DOCX template."""
    _vprint(verbose, "Loading runtime configuration.")
    runtime_config = load_config(
        config_path=config,
        overrides={"output_root": output_root},
        require_api_key=False,
    )
    try:
        _vprint(verbose, f"Parsing draft markdown: {draft}")
        parsed_draft = parse_draft_markdown(draft)
        _vprint(verbose, f"Parsed {len(parsed_draft.sections)} draft sections.")
    except DraftParseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc

    run_dir = _make_run_dir(ensure_output_root(runtime_config.output_root))
    out_doc = run_dir / "applied-document.docx"
    _vprint(verbose, f"Applying draft to template copy: {out_doc}")

    try:
        report = apply_draft_to_template(template, parsed_draft, out_doc, force=force)
    except (UnsupportedTemplateError, AlreadyAppliedError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=5) from exc

    unresolved_count = len(report.unresolved_section_ids)
    _vprint(verbose, f"Apply completed with {unresolved_count} unresolved sections.")
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


def _resolve_context_path(preferred_path: Path) -> tuple[Path, Path | None]:
    """Resolve preferred context path and detect legacy misspelled file."""
    legacy_path = preferred_path.with_name("additinal-context.md")
    if (
        preferred_path.name == "additional-context.md"
        and not preferred_path.exists()
        and legacy_path.exists()
    ):
        return preferred_path, legacy_path
    return preferred_path, None


def main() -> None:
    """Script entrypoint."""
    app()


if __name__ == "__main__":
    main()
