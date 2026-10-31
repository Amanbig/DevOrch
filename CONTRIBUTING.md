# Contributing to DevOrch

Thanks for helping out! DevOrch is a multi-provider AI coding assistant CLI, and contributions of all sizes
are welcome: bug reports, docs, tests, new providers, tools and features.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security problem,
see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Getting set up

```bash
git clone https://github.com/Amanbig/DevOrch.git
cd DevOrch
python -m venv .venv && source .venv/bin/activate      # or: uv venv && source .venv/bin/activate
pip install -e ".[dev]"                                 # or: uv pip install -e ".[dev]"

pytest                  # the whole suite; no network or API keys needed
ruff check .            # lint
ruff format .           # format (CI runs `ruff format --check .`)
devorch                 # run your working copy
```

Python 3.10+ is required; CI runs the tests on Linux, macOS and Windows for 3.10-3.13, so avoid
platform-specific assumptions (paths, shells, terminal behaviour) and keep type hints 3.10-compatible.

## Workflow

1. Open an issue first for anything large, so we can agree on the approach.
2. Create a branch per change (`feat/...`, `fix/...`, `docs/...`, `chore/...`).
3. Keep PRs focused: one feature or fix per PR.
4. Use clear, conventional-style commit messages (`feat(hooks): ...`, `fix(ui): ...`).
5. Open a PR against `main`. CI must pass (lint + tests on all platforms).

A good PR includes:

- **Tests** for new behaviour and for the bug it fixes. A regression test should fail without your fix.
- **Docs**: update the README for user-facing changes and add a line to `CHANGELOG.md`.
- An honest description: what changed, why, what you did **not** test.

## Where things live

See [`DEVORCH.md`](DEVORCH.md) and the project structure in the README. In short: `cli/` (commands, REPL, UI),
`core/` (agent loop, executor, hooks, memory, sessions), `providers/` (one file per LLM provider), `tools/`
(built-in tools), `config/` (settings, permissions, project settings), `tests/`.

### Adding a provider

Subclass `LLMProvider` in `providers/<name>.py`, implement `generate()`, and register it in
`providers/__init__.py`. Set the capability flags honestly: `supports_images` and `supports_streaming`
(`generate()` then accepts `on_text` and streams deltas). OpenAI-compatible APIs can reuse `chat_create` /
`post_chat` and `openai_user_content` from `providers/base.py`. Add tests with a mocked client.

### Adding a tool

Subclass `Tool` in `tools/`, give it a pydantic `args_schema`, register it in `build_tools` /
`start_repl`, and describe what the user sees in `utils/tool_display.py`. If it changes files, make sure
checkpoints can snapshot it (`core/checkpoints.py`). Tools that can do damage need permission handling in
`config/permissions.py`.

### Adding a slash command

Add it to `SLASH_COMMANDS` in `cli/constants.py` (that feeds the dropdown and `/help`) and handle it in the
REPL in `cli/main.py`; put non-trivial logic in `cli/repl_commands.py` so it can be tested. A test fails if a
command appears in the dropdown without a handler.

## Testing notes

- Tests must not touch your real `~/.devorch`: monkeypatch `Path.home()` and the config paths (see
  `tests/test_repl_commands.py` for a fixture).
- Do not assert on `--help` text; it is colourised and wrapped differently per terminal. Inspect the
  registered options instead.
- Terminal UI behaviour (layout, colours, key bindings) is tested on a virtual terminal with
  `tests/_screen.py` (uses `pyte`), so it can be verified without a real terminal.
- Mock the model: provider tests use fake clients, never live APIs.

## Releasing (maintainers)

1. Bump the version in `pyproject.toml` **and** `cli/constants.py`, and add the `CHANGELOG.md` entry.
2. Merge to `main`, then push a `vX.Y.Z` tag. The publish workflow builds, uploads to PyPI and creates the
   GitHub release. Published versions cannot be reused, so double-check before tagging.
