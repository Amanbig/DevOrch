# DevPilot

A multi-provider AI coding assistant CLI, similar to Claude Code and Gemini CLI.

![DevPilot Banner](https://img.shields.io/badge/DevPilot-AI%20Coding%20Assistant-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Multi-Provider Support** - OpenAI, Anthropic, Google Gemini, Groq, Mistral, Together AI, OpenRouter, Ollama (local), and LM Studio
- **Secure API Key Storage** - Uses system keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Session Persistence** - SQLite-based chat history with resume capability
- **Tool Execution** - Shell commands, file operations, search, grep, and code editing
- **Interactive UI** - Arrow-key navigation for selections, syntax-highlighted output
- **Permission System** - Configurable allow/deny rules with interactive prompts
- **Interactive Commands** - Full support for interactive CLI tools (npx, npm create, etc.)
- **Multiple Modes** - Plan mode, Auto mode, and Ask mode

## Installation

```bash
# Clone the repository
git clone https://github.com/Amanbig/DevPilot.git
cd DevPilot

# Install with pip
pip install -e .
```

## Quick Start

```bash
# Start DevPilot (first run will show interactive setup)
devpilot

# Or specify a provider
devpilot -p openai
devpilot -p anthropic
devpilot -p groq
devpilot -p local  # Ollama
```

## Interactive Onboarding

On first run, DevPilot guides you through setup with an interactive UI:

```
╭─────────────────────────────────────────────────╮
│ Welcome to DevPilot!                            │
│                                                 │
│ Let's set up your AI provider to get started.  │
╰─────────────────────────────────────────────────╯

? Select your AI provider: (Use arrow keys)
 ❯ OpenAI (GPT-4o, GPT-4, etc.)
   Anthropic (Claude Sonnet, Opus, etc.)
   Google Gemini (Gemini Pro, Flash, etc.)
   Groq (Ultra-fast Llama, Mixtral)
   ──────────────
   Ollama - Local (No API key needed)
   LM Studio - Local (No API key needed)
```

## Usage

### Interactive REPL

```bash
devpilot                    # Start interactive session
devpilot -p groq            # Use specific provider
devpilot -m gpt-4o          # Use specific model
devpilot --resume abc123    # Resume a previous session
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/mode` | Interactive mode selection (plan/auto/ask) |
| `/model` | Interactive model selection |
| `/provider` | Interactive provider switching |
| `/models` | List available models for current provider |
| `/providers` | List all available providers |
| `/status` | Show current provider, model, and mode |
| `/session` | Show current session info |
| `/history` | Show conversation history |
| `/clear` | Clear conversation history |
| `/compact` | Summarize and compact history |
| `/save` | Save conversation to file |
| `/undo` | Undo last message |
| `/tasks` | Show current task list |

### Modes

- **ASK** (default) - Asks before each tool execution
- **AUTO** - Executes tools automatically (dangerous commands still blocked)
- **PLAN** - Shows plan before executing, asks for approval

Switch modes interactively:
```
? Select mode: (Use arrow keys)
 ❯ PLAN - Shows plan before executing, asks for approval
   AUTO - Executes tools automatically (trusted mode)
   ASK - Asks before each tool execution (default)
```

## Tool Permissions

DevPilot uses an interactive permission system with arrow-key navigation:

```
╭─────────── Permission Required ───────────╮
│ Tool: shell                               │
│ Command: npm create vite@latest           │
╰───────────────────────────────────────────╯

? Choose an action: (Use arrow keys)
 ❯ Allow once
   Allow for this session
   Always allow (save to config)
   Deny
```

## Tool Output Display

Tool calls and results are displayed with syntax highlighting:

```
╭─────── Tool Call (shell) ───────╮
│ npm create vite@latest my-app   │
╰─────────────────────────────────╯

╭─────────── Result ──────────────╮
│ STDOUT:                         │
│ Scaffolding project in ./my-app │
│ Done!                           │
╰─────────────────────────────────╯
```

## Configuration

### API Keys

```bash
# Store API key securely (also sets as default provider)
devpilot set-key openai
devpilot set-key anthropic
devpilot set-key groq

# Or use environment variables
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GROQ_API_KEY=gsk_...
```

### View Configuration

```bash
devpilot config
```

### Session Management

```bash
devpilot sessions list           # List all sessions
devpilot sessions show <id>      # Show session details
devpilot sessions delete <id>    # Delete a session
devpilot sessions clear          # Delete all sessions
```

### Permissions

```bash
devpilot permissions list                    # Show permissions
devpilot permissions set shell allow         # Always allow shell commands
devpilot permissions allow shell "git *"     # Allow git commands
devpilot permissions deny shell "rm -rf *"   # Block dangerous commands
devpilot permissions reset                   # Reset to defaults
```

## Supported Providers

| Provider | Models | API Key Env Var |
|----------|--------|-----------------|
| OpenAI | gpt-4o, gpt-4, gpt-3.5-turbo | `OPENAI_API_KEY` |
| Anthropic | claude-sonnet-4, claude-opus-4 | `ANTHROPIC_API_KEY` |
| Google Gemini | gemini-1.5-pro, gemini-1.5-flash | `GOOGLE_API_KEY` |
| Groq | llama-3.1-70b, mixtral-8x7b | `GROQ_API_KEY` |
| Mistral | mistral-large, codestral | `MISTRAL_API_KEY` |
| Together AI | llama-3-70b, mixtral | `TOGETHER_API_KEY` |
| OpenRouter | 100+ models | `OPENROUTER_API_KEY` |
| Ollama (local) | llama3, codellama, mistral | None (local) |
| LM Studio | Any loaded model | None (local) |

## Tools

DevPilot has access to these tools:

| Tool | Description |
|------|-------------|
| **shell** | Execute shell commands (supports interactive commands like `npm create`) |
| **filesystem** | Read, write, and list files |
| **search** | Find files by name patterns (glob) |
| **grep** | Search for text patterns in files |
| **edit** | Make targeted edits to existing files |
| **task** | Track progress on multi-step work with visual task list |

## Task Tracking

DevPilot can track progress on complex tasks:

```
╭─────────── Tasks (2/4) ───────────╮
│   ✓ Create project structure      │
│   ✓ Set up dependencies           │
│   ● Installing packages           │
│   ○ Run initial build             │
╰───────────────────────────────────╯
```

Use `/tasks` to view current task list anytime.

## Config Files

DevPilot stores configuration in `~/.devpilot/`:

```
~/.devpilot/
├── config.yaml       # Provider settings and default models
├── permissions.yaml  # Tool permission rules
└── sessions.db       # SQLite database for chat history
```

## Requirements

- Python 3.10+
- Dependencies:
  - typer, rich, pydantic
  - openai, anthropic, google-genai
  - httpx, keyring, prompt_toolkit
  - questionary, pyyaml

## License

MIT
