# DevPilot

A multi-provider AI coding assistant CLI, similar to Claude Code and Gemini CLI.

![DevPilot Banner](https://img.shields.io/badge/DevPilot-AI%20Coding%20Assistant-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **13 AI Providers** - OpenAI, Anthropic, Gemini, Groq, Mistral, Together AI, OpenRouter, GitHub Copilot, DeepSeek, Kimi, Ollama, LM Studio, and Custom
- **Custom Provider Support** - Connect to ANY OpenAI-compatible API (vLLM, TGI, llama.cpp, etc.)
- **Dynamic Model Listing** - Fetches latest available models from provider APIs
- **Secure API Key Storage** - Uses system keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Session Persistence** - SQLite-based chat history with resume capability
- **Powerful Tools** - Shell, terminal sessions, file operations, search, grep, code editing, and web access
- **Interactive UI** - Arrow-key navigation for selections, syntax-highlighted output
- **Permission System** - Configurable allow/deny rules with interactive prompts
- **Terminal Session Management** - Run long-running servers and background processes
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

Tool calls are displayed in a clean, compact format:

```
╭──────────── Shell ────────────╮
│ npm create vite@latest my-app │
╰───────────────────────────────╯

╭─────────── Output ────────────╮
│ STDOUT:                       │
│ Scaffolding project in ./my-  │
│ app                           │
│ Done!                         │
╰───────────────────────────────╯

  > write 45 lines to src/App.tsx
    ✓ Successfully wrote 45 lines to src/App.tsx

  > read package.json
    ✓ Read 32 lines
```

## New Provider Features

### GitHub Copilot Integration

Use your GitHub Copilot subscription to access multiple premium models:

```bash
# Get GitHub token with 'copilot' scope from:
# https://github.com/settings/tokens

export GITHUB_TOKEN=ghp_your_token

# Use Copilot
devpilot -p github_copilot
devpilot -p github_copilot -m claude-3.5-sonnet
```

**Available models:** GPT-4o, GPT-4o-mini, Claude 3.5 Sonnet, o1-preview, o1-mini

### DeepSeek AI

Powerful reasoning and coding models from DeepSeek:

```bash
export DEEPSEEK_API_KEY=sk-...
devpilot -p deepseek -m deepseek-reasoner
```

**Models:** deepseek-chat, deepseek-coder, deepseek-reasoner (R1)

### Kimi (Moonshot AI)

Long context models with up to 128K tokens:

```bash
export MOONSHOT_API_KEY=sk-...
devpilot -p kimi -m moonshot-v1-128k
```

**Models:** moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k

### Custom Providers

Connect to ANY OpenAI-compatible API:

#### Self-Hosted vLLM

```yaml
# ~/.devpilot/config.yaml
providers:
  my_vllm:
    default_model: meta-llama/Meta-Llama-3-70B-Instruct
    base_url: http://localhost:8000/v1
```

```bash
# Start vLLM server
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Meta-Llama-3-70B-Instruct \
    --port 8000

# Use it
devpilot -p my_vllm
```

#### Text Generation Inference (TGI)

```yaml
providers:
  my_tgi:
    default_model: mistralai/Mistral-7B-Instruct
    base_url: http://localhost:8080/v1
```

#### llama.cpp Server

```yaml
providers:
  llamacpp:
    default_model: llama-3-8b
    base_url: http://localhost:8080/v1
```

#### Private API Endpoint

```yaml
providers:
  company_api:
    default_model: custom-model-v1
    base_url: https://api.company.com/v1
    # Set CUSTOM_API_KEY environment variable
```

### Dynamic Model Listing

All providers now fetch available models from their APIs automatically:

```bash
# List available models
devpilot models list -p deepseek
devpilot models list -p github_copilot
devpilot models list -p my_vllm
```

Models are fetched in real-time from provider APIs, so you always see the latest available models!

## Configuration

### API Keys

```bash
# Store API keys securely in system keyring
devpilot set-key openai
devpilot set-key anthropic
devpilot set-key groq
devpilot set-key github_copilot  # Uses GITHUB_TOKEN
devpilot set-key deepseek
devpilot set-key kimi

# Or use environment variables
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=...
export GROQ_API_KEY=gsk_...
export MISTRAL_API_KEY=...
export OPENROUTER_API_KEY=sk-or-...
export TOGETHER_API_KEY=...
export GITHUB_TOKEN=ghp_...
export DEEPSEEK_API_KEY=sk-...
export MOONSHOT_API_KEY=sk-...
```

### View Configuration

```bash
devpilot config
```

### Configuration File

Create `~/.devpilot/config.yaml` to configure providers:

```yaml
# Set default provider
default_provider: openai

# Configure each provider
providers:
  openai:
    default_model: gpt-4o

  anthropic:
    default_model: claude-sonnet-4-20250514

  github_copilot:
    default_model: gpt-4o

  deepseek:
    default_model: deepseek-chat

  kimi:
    default_model: moonshot-v1-32k

  # Custom providers
  my_vllm:
    default_model: meta-llama/Meta-Llama-3-70B-Instruct
    base_url: http://localhost:8000/v1

  company_api:
    default_model: custom-model-v1
    base_url: https://api.company.com/v1
```

**Note:** Don't put API keys in config files! Use environment variables or keyring.

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

### Cloud Providers

| Provider | Models | API Key | Notes |
|----------|--------|---------|-------|
| **OpenAI** | GPT-4o, GPT-4, o1-preview | `OPENAI_API_KEY` | Full support with tool calling |
| **Anthropic** | Claude 4.5, Claude 3.5, Claude 3 | `ANTHROPIC_API_KEY` | Best for coding tasks |
| **Google Gemini** | Gemini 2.0, 1.5 Pro/Flash | `GOOGLE_API_KEY` | 2M token context |
| **Groq** | Llama 3.3, Mixtral, Gemma | `GROQ_API_KEY` | Ultra-fast inference |
| **Mistral** | Large, Medium, Codestral | `MISTRAL_API_KEY` | Specialized for code |
| **Together AI** | Llama 3, Mixtral, Qwen | `TOGETHER_API_KEY` | Open source models |
| **OpenRouter** | 100+ models | `OPENROUTER_API_KEY` | Access many providers via one API |

### Developer Tools

| Provider | Models | API Key | Notes |
|----------|--------|---------|-------|
| **GitHub Copilot** ⭐ | GPT-4o, Claude 3.5, o1 | `GITHUB_TOKEN` | Requires Copilot subscription |

### International Providers

| Provider | Models | API Key | Notes |
|----------|--------|---------|-------|
| **DeepSeek** ⭐ | Chat, Coder, Reasoner | `DEEPSEEK_API_KEY` | Powerful reasoning models |
| **Kimi (Moonshot)** ⭐ | 8K, 32K, 128K | `MOONSHOT_API_KEY` | Long context (128K tokens) |

### Local & Self-Hosted

| Provider | Models | Setup | Notes |
|----------|--------|-------|-------|
| **Ollama** | Llama 3, Mistral, CodeLlama | Install Ollama | Run models locally |
| **LM Studio** | Any GGUF model | Install LM Studio | GUI for local models |
| **Custom** ⭐ | Your choice | Configure endpoint | vLLM, TGI, llama.cpp, etc. |

⭐ = New providers

## Tools

DevPilot has access to these tools:

| Tool | Description |
|------|-------------|
| **shell** | Execute shell commands (quick commands with output capture) |
| **open_terminal** ⭐ | Open new terminal window for interactive/long-running commands |
| **terminal_session** ⭐ | Managed background sessions (start, read, send input, stop) |
| **filesystem** | Read, write, and list files |
| **search** | Find files by name patterns (glob) |
| **grep** | Search for text patterns in files |
| **edit** | Make targeted edits to existing files |
| **task** | Track progress on multi-step work with visual task list |
| **websearch** | Search the web for current information (uses DuckDuckGo) |
| **webfetch** | Fetch and read content from a URL |

### Terminal Session Management

Run long-running servers and interact with them without blocking the chat:

```bash
# LLM can start a dev server in background
> terminal_session start vite_server "npm run dev"
✓ Session 'vite_server' started (PID 12345)

# Continue chatting while server runs

# Check server output
> terminal_session read vite_server
[Session 'vite_server' — running]
VITE v5.0.0 ready in 450 ms
➜ Local: http://localhost:5173/

# Send input to the process
> terminal_session send vite_server "rs\n"  # Restart

# Stop when done
> terminal_session stop vite_server
```

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
  - questionary, pyyaml, duckduckgo-search

## License

MIT
