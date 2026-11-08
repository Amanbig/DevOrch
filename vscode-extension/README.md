# DevOrch for VS Code

Chat with the [DevOrch](https://github.com/Amanbig/DevOrch) AI coding assistant from the side bar. It works in your open
folder, with any model provider DevOrch supports (OpenAI, Anthropic, Gemini, Mistral, Groq, Ollama and more).

## Get started

1. Install the DevOrch command (the panel shows the command if it is missing):
   - Linux / macOS: `curl -fsSL https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.sh | sh`
   - Windows: `irm https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.ps1 | iex`
2. Run `devorch` once in a terminal to pick a provider and save your API key.
3. Open the **DevOrch** icon in the activity bar and ask something.

## What you can do

- **Chat** in the side panel. Each chat is a DevOrch session: it continues where you left off and shows up in
  `devorch --resume` in the terminal too.
- **Ask, Auto or Plan.** Ask (the default) shows each edit or command with Allow once / This session / Always / Deny
  before it runs; Auto runs without asking; Plan is read-only. Ask needs DevOrch 0.5.4 or newer.
- **Attach the open file**, or right-click a selection: *Add Selection to Chat*, *Explain*, *Review*, *Fix*.
- **Conversations** (☰ button): everything you started in this folder; open or delete one.
- **Terminal.** *DevOrch: Start Interactive Session*, *Continue Last Conversation* and *Resume Past Session* open the
  full terminal interface, where DevOrch asks before each action.

## Settings

| Setting | |
|---|---|
| `devorch.executablePath` | The `devorch` command (default `devorch`) |
| `devorch.defaultProvider` / `devorch.defaultModel` | Override the provider and model for the panel |
| `devorch.defaultMode` | `ask`, `auto` or `plan` |
| `devorch.disableMcp`, `devorch.activeMcpServers` | MCP servers used by the panel |

DevOrch's built-in blocks on dangerous commands and your deny rules apply in every mode, and the terminal commands open the
full interface.

## Develop

```
npm ci
npm test            # lint + unit tests
npm run package     # bundle into dist/
npx @vscode/vsce package --no-dependencies
```
