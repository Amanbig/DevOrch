# DevOrch - AI Coding Assistant CLI

## Overview
DevOrch is an enterprise-ready, multi-provider AI coding assistant CLI with support for 13+ LLM providers, interactive REPL, persistent sessions, tool execution, MCP servers, and background terminal processes.

## Tech Stack
- **Language**: Python 3.10+ (tested on Python 3.10-3.13)
- **CLI Framework**: Typer, Questionary, Prompt Toolkit, Rich
- **AI / SDKs**: OpenAI, Anthropic, Google GenAI SDK, HTTPX
- **Data Validation**: Pydantic v2
- **Testing & Quality**: Pytest, Pytest-asyncio, Ruff, Mypy

## Architecture & Project Structure
- `cli/`: CLI entrypoints, Typer commands (`ask`, `edit`, `run`, `init`), slash command handlers, banners, and REPL.
- `core/`: Agent orchestration engine:
  - `agent.py`: Main agentic loop, tool calling, execution loop, plan mode approval.
  - `context.py`: Token estimation, context compaction, tool output pruning, token usage tracking.
  - `loop_detector.py`: Duplicate call detection, oscillation detection, error thrashing prevention, turn advisories.
  - `project_context.py`: Auto-discovers and loads repository instructions (`DEVORCH.md`, `CLAUDE.md`, `AGENTS.md`).
  - `executor.py`: Tool permission enforcement and invocation.
  - `planner.py`: Message preparation and system prompt injection.
  - `sessions.py`: Session persistence, continuation, and summarization.
  - `modes.py`: Agent execution modes (`ASK`, `AUTO`, `PLAN`).
  - `memory.py` & `skills.py`: Persistent memory and skill definitions.
- `tools/`: Built-in tools:
  - `filesystem.py`: File reading with pagination, writing, directory listing.
  - `edit.py`: Surgical find/replace, line-based editing, diff generation.
  - `grep.py`: Fast regex pattern search across text files.
  - `search.py`: Glob-based file and directory search.
  - `shell.py` & `terminal_session.py`: Shell execution and persistent terminal sessions.
- `providers/`: Unified LLM provider adapters (`openai`, `anthropic`, `gemini`, `groq`, `deepseek`, etc.).
- `schemas/`: Dataclasses for `Message`, `ToolCall`, `LLMResponse`, `TokenUsage`.

## Common Commands
- **Run Tests**: `pytest` or `python -m pytest`
- **Run Single Test**: `pytest tests/test_context.py`
- **Lint**: `ruff check .`
- **Format**: `ruff format .`
- **Type Check**: `mypy .`
- **Run DevOrch Locally**: `devorch` or `python -m cli.main`

## Coding Standards & Minimal Token Guidelines
1. **Find Before Reading**: Always use `search` (to find file paths) or `grep` (to find symbols/definitions) before reading file contents.
2. **Inspect Surgically**: Use `filesystem` with `action="read_lines"` or specific line ranges rather than dumping huge files.
3. **Edit Surgically**: Use `edit` with `action="replace"` or `action="replace_lines"` to generate clean unified diffs. Avoid full file rewrites whenever possible.
4. **Prevent Loops**: Never repeat identical tool calls with the same arguments. If a tool fails or finds nothing, alter the query or check file paths.
5. **Verify Changes**: After modifying code, always run the relevant pytest test suite to verify correctness before reporting completion.
6. **Preserve Compatibility**: Keep type hints compatible with Python 3.10+ (use `|` for unions or `Optional`/`Union`).
