import os
from typing import Any, Dict, List
from langchain_openai import ChatOpenAI  # Or your preferred LLM provider
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from jinja2 import Environment, FileSystemLoader  # For template rendering if using Jinja

# Custom Tool: Execute Tests (safe, sandboxed code exec)
# Note: For real exec, integrate a sandbox like Modal or subprocess with isolation.
# Here, simulate with subprocess for pytest/unittest; harden for prod.
import subprocess
def execute_tests(test_paths: List[str]) -> Dict[str, Any]:
    """Run tests at given paths (e.g., ['tests/test_model.py']) and return results."""
    results = {}
    for path in test_paths:
        try:
            output = subprocess.run(["pytest", path], capture_output=True, text=True, timeout=300)
            results[path] = {
                "success": output.returncode == 0,
                "stdout": output.stdout,
                "stderr": output.stderr
            }
        except Exception as e:
            results[path] = {"error": str(e)}
    return results

# Custom Tool: Fill Template
# Assumes templates are Jinja2 files with placeholders like {{ model_name }}, {{ accuracy }}.
def fill_template(template_path: str, data: Dict[str, Any], output_path: str) -> str:
    """Render a Jinja template with data and write to output_path."""
    env = Environment(loader=FileSystemLoader(os.path.dirname(template_path)))
    template = env.get_template(os.path.basename(template_path))
    rendered = template.render(data)
    with open(output_path, "w") as f:
        f.write(rendered)
    return f"Template filled and saved to {output_path}"

# System Prompt (core framing: instructs step-by-step reasoning)
system_prompt = """You are a Documentation Generator Agent for ML models.
Task: Given model doc templates, scan the code base, README, results dirs, execute tests, then fill templates accurately.

Always:
1. Plan with write_todos: Scan code/README/results → Analyze key details (model arch, params, metrics) → Run tests → Synthesize findings → Fill templates.
2. Use filesystem tools to read code/files (e.g., grep for model defs, read results.json).
3. Execute tests only if relevant (e.g., to verify metrics); capture outputs.
4. Extract facts: Model name, architecture, training data, eval metrics, usage examples.
5. Fill templates with precise, factual data; write outputs to /docs/filled_{template_name}.
6. If info missing/inconsistent, note assumptions or gaps.
7. Delegate to sub-agents for complex parts (e.g., test-runner for isolation).

Templates provided: {template_paths}  # Inject paths here."""

# Sub-Agent: Test Runner (isolated for exec-heavy tasks)
test_runner_subagent = {
    "name": "test-runner",
    "description": "Executes and analyzes tests",
    "system_prompt": "You run tests and parse results for metrics/errors. Output structured JSON.",
    "tools": [execute_tests]
}

# Create the Agent
def create_doc_gen_agent(template_paths: List[str]) -> Any:
    formatted_prompt = system_prompt.format(template_paths=", ".join(template_paths))
    
    checkpointer = MemorySaver()  # For persistence across runs
    
    agent = create_deep_agent(
        model=ChatOpenAI(model="gpt-4o", temperature=0.1),  # Low temp for accuracy
        tools=[execute_tests, fill_template],  # Customs + built-ins auto-added
        system_prompt=formatted_prompt,
        subagents=[test_runner_subagent],
        backend=FilesystemBackend(root_dir=".", virtual_mode=False),  # Real FS access
        memory=["ANALYSIS_NOTES.md", "MODEL_INSIGHTS.md"],  # Persistent summaries
        checkpointer=checkpointer,
        interrupt_on={"execute_tests": True, "write_file": True},  # HITL for safety
        debug=True
    )
    return agent

# Usage Example
if __name__ == "__main__":
    templates = ["templates/model_doc_template.md", "templates/api_ref_template.md"]  # Your templates
    agent = create_doc_gen_agent(templates)
    
    # Interactive run (or invoke one-shot)
    inputs = {"messages": [{"role": "user", "content": "Generate docs for my ML model codebase."}]}
    for event in agent.astream_events(inputs, version="v2", subgraphs=True):
        # Handle streaming/output (as in prior examples)
        pass
    
    # Final output: Check /docs/ for filled templates