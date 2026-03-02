# DevPilot

A multi-provider AI coding assistant CLI, similar to Claude Code and Gemini CLI.

## Features

- **Multi-Provider Support** - OpenAI, Anthropic, Google Gemini, Groq, Mistral, Together AI, OpenRouter, Ollama (local), and LM Studio
- **Secure API Key Storage** - Uses system keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Session Persistence** - SQLite-based chat history with resume capability
- **Tool Execution** - Shell commands, file operations, search, grep, and code editing
- **Permission System** - Configurable allow/deny rules for tool execution
- **Interactive Commands** - Full support for interactive CLI tools (npx, npm init, etc.)
- **Multiple Modes** - Plan mode, Auto mode, and Ask mode

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/devpilot.git
cd devpilot

# Install with pip
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

## Quick Start

```bash
# Start DevPilot (first run will prompt for provider setup)
devpilot

# Or specify a provider
devpilot -p openai
devpilot -p anthropic
devpilot -p groq
devpilot -p local  # Ollama
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
| `/mode` | Show or change mode (plan/auto/ask) |
| `/plan` | Switch to plan mode |
| `/auto` | Switch to auto mode |
| `/ask` | Switch to ask mode (default) |
| `/clear` | Clear conversation history |
| `/status` | Show current provider, model, and mode |
| `/models` | List available models |
| `/model <name>` | Switch to a different model |
| `/providers` | List all available providers |
| `/provider <name>` | Switch to a different provider |
| `/session` | Show current session info |
| `/history` | Show conversation history |
| `/compact` | Summarize and compact history |
| `/save` | Save conversation to file |
| `/undo` | Undo last message |

### Modes

- **ASK** (default) - Asks before each tool execution
- **AUTO** - Executes tools automatically (dangerous commands still blocked)
- **PLAN** - Shows plan before executing, asks for approval

## Configuration

### API Keys

```bash
# Store API key securely in system keychain
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

- **shell** - Execute shell commands (supports interactive commands)
- **filesystem** - Read, write, and list files
- **search** - Find files by name patterns
- **grep** - Search for text patterns in files
- **edit** - Make targeted edits to files

## Tool Permissions

When DevPilot wants to use a tool, you'll see a prompt:

```
DevPilot wants to use shell:
  npx create-next-app@latest

  y/1 - Allow once
  a/2 - Allow for this session
  s/3 - Always allow (save to config)
  n/4 - Deny

y/a/s/n [y]:
```

- Press **Enter** or **y** to allow once
- Type **a** to allow for the current session
- Type **s** to always allow (saves to config)
- Type **n** to deny

## Config Files

DevPilot stores configuration in `~/.devpilot/`:

```
~/.devpilot/
  config.yaml       # Provider settings and default models
  permissions.yaml  # Tool permission rules
  sessions.db       # SQLite database for chat history
```

## Requirements

- Python 3.10+
- Dependencies: typer, rich, pydantic, openai, anthropic, google-generativeai, httpx, keyring, prompt_toolkit, pyyaml

## License

MIT
