# DevOrch Code

A premium VS Code extension that integrates the **DevOrch CLI** — an open-source, multi-provider AI coding assistant and agent. Run shell commands, edit files, manage background processes, and orchestrate complex tasks right from your editor.

---

## 🚀 DevOrch CLI Capabilities

DevOrch provides a coding agent in your terminal/editor that executes tools on your system — powered by 13+ AI providers or your own local models.

### Why DevOrch?
* **Provider Freedom** — Switch between OpenAI, Anthropic, Gemini, Mistral, Groq, Together AI, OpenRouter, DeepSeek, local Ollama/LM Studio models, and more. No vendor lock-in!
* **Actually Runs Tools** — Runs shell commands, reads/writes/edits files, manages background processes, and searches the web.
* **Persistent Memory** — Stores preferences, project context, and feedback across conversations (`/remember`, `/memory`).
* **Extensible Skills** — Create custom reusable YAML prompt templates for tasks like deploys, tests, or code reviews.
* **Model Context Protocol (MCP)** — Dynamically connects external tool servers to expand capabilities.

---

## ⚡ Extension Features

### 💬 Sidebar Chat Interface
A premium glassmorphic UI matching VS Code’s native style. Engage in interactive chat sessions, set execution modes, and monitor tool outputs step-by-step.

### ⚠️ Interactive Tool Permissions (`ask` Mode)
The extension fully supports DevOrch's `ask` mode. When a tool requests system execution permissions, a **Permission Required** dialog pops up in your chat panel, giving you four actions:
1. **Allow Once** — Run the current command once.
2. **Allow for Session** — Automatically allow this command format for the rest of the session.
3. **Always Allow** — Persistently allow this tool pattern (saves to `permissions.yaml`).
4. **Deny** — Safely reject execution.

The extension intercepts prompts from the CLI's standard output and translates your selections back into stdout stdin keypresses (`\n`, `\x1b[B\n`, etc.) automatically.

### 🔌 Dedicated Sidebar MCP Tab
Directly manage your Model Context Protocol configurations in the sidebar next to the chat panel:
* **Global Toggle** — Instantly disable all MCP servers.
* **Servers List** — View active MCP servers configured in `~/.devorch/config.yaml`.
* **Add Server Form** — Connect new servers mid-session without manually editing configuration files.

### 🛠️ Dedicated `/model` Dialog
Quickly switch providers and models:
* **Dynamic API Key Detection** — If a selected provider doesn't have an API key configured (status `not_set`), the dialog expands to prompt you for the key, saving it securely in DevOrch's credentials vault.

### 🔄 Advanced Slash Commands
Type `/` in the input prompt to access:
* `/compact` — Compresses conversation history in the SQLite database (`sessions.db`) using LLM summarization.
* `/undo` — Safely reverts the last user prompt and the assistant's reply.
* `/settings` — Opens native VS Code settings directly.
* `/repl` — Opens a native interactive DevOrch terminal window.

---

## 📦 Requirements & Installation

1. **Install DevOrch CLI** via Python:
   ```bash
   pipx install devorch
   # Or
   pip install devorch
   ```
2. **Configure API Keys** (or set them via the extension's `/model` dialog):
   ```bash
   devorch set-key openai
   devorch set-key anthropic
   ```
3. **Install Extension**:
   ```bash
   code --install-extension devorch-code-0.0.1.vsix
   ```

---

## ⚙️ Extension Settings

Accessible via `Ctrl+,` (Settings) searching for `devorch`:

| Setting | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `devorch.executablePath` | `string` | `"devorch"` | Path to the `devorch` CLI executable. |
| `devorch.defaultProvider` | `string` | `""` | Default AI provider override. |
| `devorch.defaultModel` | `string` | `""` | Default model override. |
| `devorch.defaultMode` | `string` | `"auto"` | Default tool mode (`auto`, `ask`, `plan`). |
| `devorch.disableMcp` | `boolean` | `false` | Disable all MCP servers globally. |
| `devorch.activeMcpServers`| `string` | `""` | Comma-separated list of active MCP servers. |

---

## 📂 DevOrch Directory Layout
DevOrch files are stored in your home directory under `~/.devorch/`:
```
~/.devorch/
├── config.yaml          # Provider configurations & MCP servers
├── permissions.yaml     # Allowed/denied tool permission rules
├── sessions.db          # SQLite database containing chat history
├── memory/              # Markdown files storing persistent memory
└── skills/              # YAML custom skill definitions
```
