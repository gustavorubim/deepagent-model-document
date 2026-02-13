# MRM Deep Agent

CLI-first deep agent to draft and apply model risk management document updates from a codebase.

## Stack

- LangChain `deepagents`
- Gemini via `langchain-google-genai` and `GOOGLE_API_KEY`
- `uv` for environment and dependency management
- `ruff` for linting
- `pytest` + `pytest-cov` with `>=90%` line coverage

## Quickstart

```bash
uv sync --all-groups
uv run mrm-agent validate-template --template examples/fictitious_mrm_template.docx
uv run mrm-agent draft --codebase examples/regression_model --template examples/fictitious_mrm_template.docx
# Edit outputs/<run_id>/draft.md if needed
uv run mrm-agent apply --draft outputs/<run_id>/draft.md --template examples/fictitious_mrm_template.docx
```

## Contracts

### Template markers

- `[FILL][ID:<section_id>] <title>`
- `[SKIP][ID:<section_id>] <title>`
- `[VALIDATOR][ID:<section_id>] <title>`
- checkbox token: `[[CHECK:<name>]]`

### Draft markdown

Each generated section must contain:

1. `## [ID:<section_id>] <title>`
2. A YAML block with keys:
   - `status`
   - `checkboxes`
   - `attachments`
   - `evidence`
   - `missing_items`
3. Section body text

For each section, at least one of `evidence` or `missing_items` must be present.

### Missing context file

`additinal-context.md` is generated/updated with unresolved questions:

```md
## <missing_item_id>
section_id: <section_id>
question: <what is missing>
user_response: <filled by user>
```

Next `draft` run includes `user_response` values as source context.
