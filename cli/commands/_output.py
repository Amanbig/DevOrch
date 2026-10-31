"""Output formats for non-interactive commands (ask / run).

    text         human-readable panel (default)
    json         one JSON object on stdout when the run finishes
    stream-json  newline-delimited JSON: one event per tool call, then a final result event

In json modes stdout carries only JSON; all decorative output is redirected to stderr, and the
process exits non-zero on failure so scripts and CI can rely on the exit code.
"""

import json
import sys
import time
from typing import Any

import typer

from utils.logger import get_console, print_error, print_panel, print_warning

FORMATS = ("text", "json", "stream-json")
MAX_TOOL_OUTPUT_CHARS = 2000


def validate_format(output: str) -> str:
    output = (output or "text").lower()
    if output not in FORMATS:
        print_error(f"Unknown output format '{output}'. Choose from: {', '.join(FORMATS)}")
        raise typer.Exit(1)
    return output


def configure_output(output: str) -> None:
    """Keep stdout clean for machine-readable formats by sending UI output to stderr."""
    if output != "text":
        get_console().file = sys.stderr


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def _usage(agent) -> dict[str, Any]:
    stats = agent.context_manager.stats
    usage: dict[str, Any] = {
        "prompt_tokens": stats.prompt_tokens,
        "completion_tokens": stats.completion_tokens,
        "total_tokens": stats.total_tokens,
        "cached_tokens": stats.cached_tokens,
    }
    costs = getattr(agent, "costs", None)
    if costs is not None:
        # Estimate from approximate list prices; null when no used model has a known price
        usage["cost_usd"] = round(costs.total, 6) if costs.has_priced else None
        usage["cost_complete"] = costs.has_priced and not costs.has_unpriced
    return usage


def build_result(
    agent,
    *,
    result: str | None,
    error: str | None,
    provider: str,
    model: str,
    started: float,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "result",
        "is_error": error is not None,
        "result": result if error is None else None,
        "error": error,
        "provider": provider,
        "model": model,
        "duration_ms": int((time.time() - started) * 1000),
        "usage": _usage(agent),
        "tool_calls": tool_calls,
    }


def run_with_output(
    agent,
    prompt: str,
    *,
    output: str,
    provider: str,
    model: str,
    title: str = "DevOrch",
    max_iterations: int = 15,
    images: list | None = None,
) -> None:
    """Run the agent and render the outcome in the requested format."""
    run_kwargs = {"images": images} if images else {}
    if output == "text":
        try:
            result = agent.run(prompt, max_iterations=max_iterations, **run_kwargs)
            interrupted = getattr(agent, "last_run_interrupted", False)
            if not interrupted:
                print_panel(result, title=title, border_style="cyan")
        except Exception as e:
            print_error(str(e))
            return
        if interrupted:
            print_warning("Interrupted.")
            raise typer.Exit(130)
        return

    tool_calls: list[dict[str, Any]] = []
    original_execute = agent.executor.execute

    def recording_execute(tool_name: str, arguments: dict[str, Any]):
        out = original_execute(tool_name, arguments)
        text = str(out)
        entry = {
            "name": tool_name,
            "arguments": arguments,
            "is_error": text.startswith("Error"),
            "output": text[:MAX_TOOL_OUTPUT_CHARS],
        }
        tool_calls.append(entry)
        if output == "stream-json":
            _emit({"type": "tool_call", **entry})
        return out

    agent.executor.execute = recording_execute

    started = time.time()
    result, error, interrupted = None, None, False
    try:
        result = agent.run(prompt, max_iterations=max_iterations, **run_kwargs)
        if getattr(agent, "last_run_interrupted", False):
            error, interrupted = "interrupted", True
    except Exception as e:
        error = str(e) or e.__class__.__name__
    finally:
        agent.executor.execute = original_execute

    _emit(
        build_result(
            agent,
            result=result,
            error=error,
            provider=provider,
            model=model,
            started=started,
            tool_calls=tool_calls,
        )
    )
    if error is not None:
        raise typer.Exit(130 if interrupted else 1)
