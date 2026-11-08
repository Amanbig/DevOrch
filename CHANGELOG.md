# Changelog

## 0.5.4

Approve DevOrch's actions inside VS Code, and sub-agents no longer skip your approvals.

### Upgrade notes
- **Sub-agents now follow the permission mode of the agent that started them.** Before, the `agent` tool ran its
  sub-agent in Auto mode even in Ask mode, so approving one `agent` call approved every command inside it. Now, in
  Ask (or Plan) mode the sub-agent asks for each edit or command too; in Auto mode nothing changes. The VS Code
  extension needs 0.5.4 for its Ask mode.

### Added
- `devorch ask --approvals stdio` (with `--output stream-json`) lets an editor answer permission questions: DevOrch
  writes a `permission_request` JSON line and waits for `{"id": N, "choice": "once|session|always|deny"}` on stdin.
  No answer means deny.
- `devorch ask --save-session` in text mode now prints the session id and how to continue it.
- **VS Code extension 0.1.1: Ask mode.** The panel now has Ask, Auto and Plan. Ask (the new default) shows each edit
  or command as a card with Allow once / This session / Always / Deny, so DevOrch no longer changes things without
  asking. Older DevOrch versions start in Auto. Provider errors such as a 429 rate limit or a rejected API key are
  explained in plain words.
- README: how to continue conversations from scripts and editors, and a VS Code section.

## 0.5.3

Install DevOrch with one command, use it from VS Code, and continue a conversation from scripts and editors.

### Upgrade notes
- **DevOrch now installs as a single `devorch` package.** Before, the wheel put seven generic top-level packages
  (`cli`, `config`, `core`, `providers`, `schemas`, `tools`, `utils`) into `site-packages`, where they could clash
  with other software. The `devorch` command, config and data are unchanged. Only code that imports DevOrch's
  internals is affected: `from core.agent import Agent` becomes `from devorch.core.agent import Agent`.

### Added
- **One-line installers.** Linux and macOS: `curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh`.
  Windows: `irm https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.ps1 | iex`. They use uv, then pipx,
  then a private virtual environment, and offer to install uv if none is available. They never use sudo or
  administrator rights, print every command, and leave `~/.devorch` alone (also on uninstall). Options:
  `--version`, `--method`, `--from`, `--bin-dir`, `--yes`, `--dry-run`, `--uninstall`. CI installs the built wheel
  with them on Ubuntu, macOS and Windows.
- **VS Code extension** (in `vscode-extension/`, moved from the DevOrch-Code repo and rewritten): a chat panel in the
  side bar with Auto and Plan modes, tool calls shown as they happen, a stop button, the open file or selection as
  context, a conversations list, a `/` menu (panel commands and your skills), `@` file suggestions, and help to
  install or update the `devorch` command. Terminal commands to start, continue or resume a session. Install it from
  the `.vsix` attached to the GitHub release.
- `devorch ask --save-session`, `--resume <id>` and `--continue` keep a conversation going across `ask` runs; the
  `--output json` / `stream-json` result now includes `session_id`.
- `devorch sessions list --output json`, `devorch sessions messages <id>` and `devorch skills --output json`, for
  editors and scripts.
- `python -m devorch` works.

### Changed
- The version lives in one place, `devorch/__init__.py` (it used to be in two files).
- CI checks that the built wheel contains only the `devorch` package, and builds, lints and tests the extension.

## 0.5.2

DevOrch behaves better out of the box: a rewritten system prompt, a long-standing loop-safeguard bug fixed, and limits
that follow the model instead of being fixed for everyone.

### Upgrade notes
- **Long sessions send larger requests.** History is now compacted at 60% of the model's context window (capped at
  64k tokens) instead of a fixed 16k, so models with big windows keep more of the conversation. Models DevOrch does
  not know, and local servers (Ollama, LM Studio, custom), keep the old 16k. Lower it per model with `context_windows:`
  in `~/.devorch/config.yaml`.

### Changed
- **System prompt rewritten** (about 870 tokens instead of 1,500). It now separates questions from requests (a
  question is answered with read-only tools, not acted on), asks before installing packages, creating environments or
  deleting files, tells the model to verify instead of guessing and to stop repeating failed calls, and asks for short
  reports. `shell` is for commands that finish and `terminal_session` only for long-running or interactive processes
  (it no longer opens a GUI terminal to run a test suite). The `terminal_session` tool description and the sub-agent
  prompt were corrected the same way.
- **History compaction follows the model's context window** (see upgrade notes); the `ctx` gauge follows `/model`.
- **Anthropic requests use the model's own output limit** instead of a fixed 4096 tokens, and a reply cut off by the
  output limit now produces a warning (also for OpenAI-style and Gemini providers).

### Added
- **Retries with backoff** for rate limits, server errors, overloads and dropped connections (up to 3, honouring
  `Retry-After`). Nothing is retried once streamed text has been shown, and auth or bad-request errors fail at once.
- **`--max-turns N`** on `ask`, `run` and `edit`; the stop message now names the real limit.
- `context_windows:` overrides in `config.yaml`.
- `scripts/prompt_eval.py` and `docs/PROMPT_EVALUATION.md`: behavioural scenarios for judging a prompt change on a real
  model.

### Fixed
- **Every tool result no longer ends with a false "You have already executed this exact command" notice.** The agent
  recorded each call twice in the loop safeguard, which also blocked the *second* repeat instead of the third and reset
  the error streak so "3 failures in a row" could never fire. Warnings now reach the model only when they are true.
- The safeguard's error detection looks at how a result *starts*, so reading a file that mentions `error:` no longer
  counts as a failure; a command that only printed to stderr does.
- `search` tolerates the directory name inside the pattern (`**/cli/commands/*.py` in `cli`), and a search that finds
  nothing now says what the directory contains instead of a bare "No files found", which small models read as
  "the folder is empty".
- The placeholder text some providers invent for a reply with no text ("Calling tool...") is no longer saved as the
  assistant's words (models imitated it), and an empty final answer is reported as such.
- A blocked-call message containing text like `[/x]` could crash the turn.

## 0.5.1

### Added
- **`devorch --continue` / `-c`**: continue the latest conversation started in this directory. Sessions now record
  their directory (older sessions have none and are not matched by `--continue`).
- **`devorch --resume` with no ID** opens a session picker (this directory first, with an option for all); **`/resume`**
  switches session inside the REPL.
- **`devorch --version` / `-V`**.
- **`devorch doctor`** (and `/doctor`): a read-only health report (providers, keys, permissions, project trust,
  terminal). It never prints key values, and it warns when `edit`/`filesystem` are pre-approved.
- `devorch sessions list --here`, and a Directory column in session listings.

### Fixed
- Messages in a resumed session could come back out of order when saved within the same second; they are now loaded
  in the order they were saved.
- A stray `pytest` run no longer overwrites your real `~/.devorch` (it replaced saved permissions with
  `edit: allow` / `filesystem: allow`); each test also starts with an empty home.

## 0.5.0

A large feature release: hooks, checkpoints, project settings, image input, streaming, prompt caching,
cost estimates, and a much more robust terminal UI.

### Upgrade notes
- **Project hooks and some project settings now need `devorch trust`.** `.devorch/hooks.yaml`, a project's
  `mcp_servers`, permission `allow` rules and `default_mode: auto` are ignored (with a warning) until you review the
  files and run `devorch trust`. Editing either file revokes trust.
- **Ctrl+C no longer quits.** It cancels the current turn; press it twice at an idle prompt (or type `exit`) to quit.
- **`/undo` now also restores files** the agent changed with `edit` / `filesystem write` (not shell commands).
- **The REPL clears the visible screen on start** (scrollback is kept). Set `DEVORCH_NO_CLEAR=1` to disable.
- `devorch run --mode` now defaults to the project setting, falling back to `auto`.
- Requires `prompt_toolkit>=3.0.28`.

### Added
- **Hooks**: `PreToolUse` / `PostToolUse` shell hooks (`~/.devorch/hooks.yaml`, `.devorch/hooks.yaml`).
- **Checkpoints**: file snapshots per turn, restored by `/undo`; `/checkpoints` lists them.
- **Custom slash commands** from Markdown files (`~/.devorch/commands`, `.devorch/commands`) with `$ARGUMENTS`.
- **`@file` mentions** with line ranges, directories and tab completion.
- **Image input**: `@screenshot.png` for vision models across providers; large images are downscaled
  (optional `devorch[images]`) and old images are pruned from context to save tokens.
- **`--output json` / `stream-json`** for `ask` and `run`, with usage, tool calls and cost.
- **Structured `git` tool** (status, diff, log, show, branch, switch, add, commit); no push/reset/force.
- **Per-project settings** (`.devorch/settings.yaml`) with a trust model.
- **Streaming** replies for every provider.
- **Prompt caching** for Anthropic (and `anthropic/*` via OpenRouter); tests guard prompt-prefix stability so
  OpenAI/DeepSeek/Kimi/Gemini automatic caches keep hitting.
- **`/cost`** and cost estimates in the per-turn line, `/tokens`, the bottom bar and JSON output; prices are
  approximate and overridable under `pricing:` in `config.yaml`.
- **More slash commands**, matching the CLI: `/permissions allow|deny|set|reset`, `/sessions`, `/hooks`, `/trust`,
  `/untrust`, `/exit`.
- **`--mode` for `devorch` / `devorch chat`, and `--dangerously-skip-permissions`** on every entry point (same as
  `--mode auto`: no prompts; dangerous-command blocks and deny rules still apply).
- **Input surface**: open input box with a coloured mode label, `Shift+Tab` mode cycling, `Ctrl+J` newline, a
  width-aware placeholder and bottom bar, context-usage gauge.

### Fixed
- **Anthropic: the base system prompt was overwritten** by plan-mode / loop-advisory system messages.
- **Tool output crashed the turn** (`MarkupError`) when a command, path, result or diff contained text like `[/x]`,
  and silently lost brackets (`app/[id]/page.tsx`, `List[int]`). Message helpers now escape their text.
- Reading a file that merely contained `Error:` was shown as a red failure.
- Ctrl+C inside a sub-agent was swallowed and the parent kept running.
- The bottom toolbar re-ran `git` on every keystroke; it is now cached.
- The bottom toolbar rendered as a bright reversed bar, and was clipped on narrow terminals, hiding the mode.
- Saving config no longer drops a `pricing:` section.
- The slash-command dropdown vanished when a command was fully typed (`/cost`, `/models`).

### Changed
- CI runs on pull requests only.
