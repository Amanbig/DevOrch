# Changelog

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
