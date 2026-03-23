# DevOrch

A multi-provider AI coding assistant CLI, similar to Claude Code and Gemini CLI.

![DevOrch Banner](https://img.shields.io/badge/DevOrch-AI%20Coding%20Assistant-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **13 AI Providers** - OpenAI, Anthropic, Gemini, Groq, Mistral, Together AI, OpenRouter, GitHub Copilot, DeepSeek, Kimi, Ollama, LM Studio, and Custom
- **Memory System** - Persistent memory across conversations (user preferences, feedback, project context)
- **MCP Support** - Connect Model Context Protocol servers for extensible tools
- **Skills System** - Built-in and custom skills (`/commit`, `/review`, `/test`, `/fix`, `/explain`, `/simplify`)
- **Persistent Terminal Sessions** - Background processes survive across DevOrch restarts with unique names
- **Dynamic Model Listing** - Fetches latest available models from provider APIs
- **Secure API Key Storage** - Uses system keychain (Windows, macOS, Linux)
- **Session Persistence** - SQLite-based chat history with resume capability
- **Powerful Tools** - Shell, terminal sessions, file operations, search, grep, code editing, web access, memory
- **Interactive UI** - Arrow-key navigation, completion menu, bottom status bar, markdown-rendered responses
- **Permission System** - Configurable allow/deny rules with interactive prompts
- **Multiple Modes** - Plan mode, Auto mode, and Ask mode

## Installation

### Option 1: Install with pipx (Recommended)

```bash
pip install pipx
pipx install devorch
```

### Option 2: Install with pip

```bash
pip install devorch
```

### Option 3: Install from source

```bash
git clone https://github.com/Amanbig/DevOrch.git
cd DevOrch
pip install -e .
```

## Quick Start

```bash
# Start DevOrch (first run shows interactive setup)
devorch

# Specify a provider
devorch -p openai
devorch -p anthropic
devorch -p local  # Ollama
```

## Slash Commands

### Navigation & Switching

| Command | Description |
|---------|-------------|
| `/help` | Show all commands grouped by category |
| `/models` | Browse and switch models (interactive) |
| `/model <name>` | Switch model (supports partial match, e.g. `/model opus`) |
| `/providers` | Browse and switch providers (interactive) |
| `/provider <name>` | Switch provider directly |
| `/mode` | Switch between Plan/Auto/Ask modes |
| `/status` | Show provider, model, mode, memories, skills, MCP |

### Memory

| Command | Description |
|---------|-------------|
| `/memory` | Show all saved memories |
| `/remember <text>` | Save something to memory |
| `/forget` | Delete a memory (interactive) |

Memories persist across conversations in `~/.devorch/memory/`. Types:
- **user** - Your role, preferences, expertise
- **feedback** - Corrections and guidance for the AI
- **project** - Project decisions, context, ongoing work
- **reference** - Links to external resources

### Skills

| Command | Description |
|---------|-------------|
| `/skills` | List all available skills |
| `/skill <name>` | Run a skill |
| `/commit` | Create a git commit with a descriptive message |
| `/review` | Review code changes for bugs and issues |
| `/test` | Run project tests and analyze results |
| `/fix` | Fix the last error or failing test |
| `/explain` | Explain the current project structure |
| `/simplify` | Simplify recent code changes |

Custom skills can be added as YAML files in `~/.devorch/skills/`:

```yaml
# ~/.devorch/skills/deploy.yaml
name: deploy
description: Deploy to production
prompt: |
  Run the deploy script and verify it succeeds.
  Check the deploy logs for any errors.
```

### Session

| Command | Description |
|---------|-------------|
| `/session` | Show current session info |
| `/history` | Show conversation history |
| `/clear` | Clear conversation history |
| `/compact` | Summarize and compact history |
| `/save` | Save conversation to file |
| `/undo` | Undo last message |

### MCP

| Command | Description |
|---------|-------------|
| `/mcp` | Show connected MCP servers and their tools |

## MCP (Model Context Protocol)

Connect external tool servers via MCP. Configure in `~/.devorch/config.yaml`:

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "ghp_xxx"
  sqlite:
    command: uvx
    args: ["mcp-server-sqlite", "--db-path", "mydb.sqlite"]
```

MCP tools automatically appear alongside built-in tools and can be used by the AI.

## Modes

- **ASK** (default) - Asks before each tool execution
- **AUTO** - Executes tools automatically (dangerous commands still blocked)
- **PLAN** - Shows plan before executing, asks for approval

## Terminal Sessions

Background processes with unique auto-generated names that persist across restarts:

```
> Start a dev server
  > terminal_session start command="npm run dev"
    ✓ Session 'swift-fox-a3f2' started (PID 12345)

> Check the server
  > terminal_session read session_id="swift-fox-a3f2"
    ✓ [Session 'swift-fox-a3f2' — running]

> Stop it
  > terminal_session stop session_id="swift-fox-a3f2"
    ✓ Session 'swift-fox-a3f2' stopped.
```

Sessions are tracked in `~/.devorch/sessions/` and can be reconnected after restarting DevOrch.

## Tool Permissions

Interactive permission system with arrow-key navigation:

```
╭─────────── Permission Required ───────────╮
│ Tool: shell                               │
│ Command: npm install                      │
╰───────────────────────────────────────────╯

? Choose an action:
  » Allow once
    Allow for this session
    Always allow (save to config)
    Deny
```

```bash
devorch permissions list                    # Show permissions
devorch permissions set shell allow         # Always allow shell
devorch permissions allow shell "git *"     # Allow git commands
devorch permissions deny shell "rm -rf *"   # Block dangerous commands
```

## Supported Providers

### Cloud Providers

| Provider | Models | API Key |
|----------|--------|---------|
| **OpenAI** | GPT-4o, GPT-4, o1 | `OPENAI_API_KEY` |
| **Anthropic** | Claude 4, Claude 3.5 | `ANTHROPIC_API_KEY` |
| **Google Gemini** | Gemini 2.0, 1.5 Pro/Flash | `GOOGLE_API_KEY` |
| **Groq** | Llama 3.3, Mixtral | `GROQ_API_KEY` |
| **Mistral** | Large, Codestral | `MISTRAL_API_KEY` |
| **Together AI** | Llama 3, Mixtral, Qwen | `TOGETHER_API_KEY` |
| **OpenRouter** | 100+ models | `OPENROUTER_API_KEY` |
| **GitHub Copilot** | GPT-4o, Claude 3.5 | `GITHUB_TOKEN` |
| **DeepSeek** | Chat, Coder, Reasoner | `DEEPSEEK_API_KEY` |
| **Kimi (Moonshot)** | 8K, 32K, 128K context | `MOONSHOT_API_KEY` |

### Local & Self-Hosted

| Provider | Setup |
|----------|-------|
| **Ollama** | Install Ollama, run models locally |
| **LM Studio** | Install LM Studio, GUI for local models |
| **Custom** | Any OpenAI-compatible API (vLLM, TGI, llama.cpp) |

## Tools

| Tool | Description |
|------|-------------|
| **shell** | Execute shell commands |
| **open_terminal** | Open new terminal window for servers/scaffolds |
| **terminal_session** | Persistent background sessions (start, read, send, stop) |
| **filesystem** | Read, write, and list files |
| **search** | Find files by name patterns (glob) |
| **grep** | Search for text patterns in files |
| **edit** | Make targeted edits to existing files |
| **task** | Track progress on multi-step work |
| **memory** | Save/search persistent memories across conversations |
| **websearch** | Search the web (DuckDuckGo) |
| **webfetch** | Fetch content from a URL |

## Configuration

### API Keys

```bash
# Store securely in system keyring
devorch set-key openai
devorch set-key anthropic

# Or use environment variables
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=...
export GROQ_API_KEY=gsk_...
```

### Config File

`~/.devorch/config.yaml`:

```yaml
default_provider: openai

providers:
  openai:
    default_model: gpt-4o
  anthropic:
    default_model: claude-sonnet-4-20250514

# MCP servers
mcp_servers:
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "ghp_xxx"
```

### Directory Structure

```
~/.devorch/
├── config.yaml          # Provider settings, MCP servers
├── permissions.yaml     # Tool permission rules
├── sessions.db          # Chat history (SQLite)
├── memory/              # Persistent memories
│   ├── MEMORY.md        # Memory index
│   ├── user_*.md        # User profile memories
│   ├── feedback_*.md    # Feedback memories
│   └── project_*.md     # Project context memories
├── skills/              # Custom skill definitions
│   └── *.yaml           # User-defined skills
└── sessions/            # Terminal session logs
    ├── registry.json    # Session registry
    └── *.log            # Session output logs
```

## Requirements

- Python 3.10+
- Dependencies: typer, rich, pydantic, openai, anthropic, google-genai, httpx, keyring, prompt_toolkit, questionary, pyyaml, duckduckgo-search

## License

MIT
