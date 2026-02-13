# AGENTS.md

Guidance for agents working in this repository.

## Project purpose

Build and maintain a CLI-first deep agent that:

1. Reads a codebase and an MRM DOCX template.
2. Uses LangChain `deepagents` with Gemini (Google AI Studio API).
3. Produces draft documentation plus missing-context prompts.
4. Applies reviewed draft content into a copied DOCX template.

## Required stack

- Python `3.11`
- Package/env manager: `uv`
- Linting: `ruff`
- Testing: `pytest` + `pytest-cov` with `>=90%` line coverage
- LLM provider: Gemini via `langchain-google-genai`
  - API mode: `MRM_AUTH_MODE=api` + `GOOGLE_API_KEY`
  - M2M mode: `MRM_AUTH_MODE=m2m` + Vertex + M2M OAuth fields

## Contracts to preserve

### CLI

- `mrm-agent validate-template --template <path.docx>`
- `mrm-agent draft --codebase <path> --template <path.docx> --output-root outputs --context-file additional-context.md --model gemini-3-flash-preview --auth-mode api|m2m`
- `mrm-agent apply --draft <draft.md> --template <path.docx> --output-root outputs`

### Exit codes

- `0`: success
- `2`: invalid template markers/schema
- `3`: missing required runtime config (for example `GOOGLE_API_KEY`)
- `4`: invalid/unparseable draft markdown
- `5`: unsupported/unsafe apply operation

### Template marker format

- `[FILL][ID:<section_id>] <title>`
- `[SKIP][ID:<section_id>] <title>`
- `[VALIDATOR][ID:<section_id>] <title>`
- checkbox tokens in body: `[[CHECK:<name>]]`
- optional narrative placeholder: `[[SECTION_CONTENT]]`

### Draft markdown format

Each section must be:

1. `## [ID:<section_id>] <title>`
2. YAML block with keys:
   - `status`
   - `checkboxes`
   - `attachments`
   - `evidence`
   - `missing_items`
3. Section body text

Rule: each generated fill section must include at least one `evidence` entry or one `missing_items` entry.

### Missing context file

Use exact filename: `additional-context.md`.

Entry format:

```md
## <missing_item_id>
section_id: <section_id>
question: <prompt for human>
user_response: <filled by user>
```

## Development workflow

1. `uv sync --all-groups`
2. `uv run ruff check src tests`
3. `uv run pytest`

Optional local smoke (requires `.env` with `GOOGLE_API_KEY`):

1. `uv run mrm-agent validate-template --template examples/fictitious_mrm_template.docx`
2. `uv run mrm-agent draft --codebase examples/regression_model --template examples/fictitious_mrm_template.docx`
3. Review `outputs/<run_id>/draft.md`
4. `uv run mrm-agent apply --draft outputs/<run_id>/draft.md --template examples/fictitious_mrm_template.docx`

## Safety and behavior rules

- Never modify the input template in place; always write to a copied output DOCX.
- Never overwrite validator-only sections (`[VALIDATOR]`) or skipped sections (`[SKIP]`).
- Do not fabricate facts or metrics; create `missing_items` when evidence is insufficient.
- Preserve determinism in orchestration (section-by-section processing in template order).
- Keep outputs in timestamped folders under `outputs/`.

## Repository layout (high level)

- `src/mrm_deepagent/` core implementation
- `tests/` unit/integration/CLI tests
- `examples/regression_model/` fictitious codebase
- `examples/fictitious_mrm_template.docx` fictitious MRM template
- `outputs/` runtime artifacts
