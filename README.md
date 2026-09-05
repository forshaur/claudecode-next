# ClaudeCode-Next

**An unofficial CLI coding agent that runs on the Claude.ai web interface.**

This tool lets you use Claude as a coding assistant from your terminal – reading files, running commands, refactoring code – without needing an API key or paying per-token. It extracts your Claude.ai session from your browser once, then works entirely from the CLI and it's completely free.

**Demo**



https://github.com/user-attachments/assets/f690f6cd-2f60-4755-83b5-9110b93d3147




## What it does

- Read/write files in your project
- Run shell commands (git, npm, tests, builds)
- Search code and refactor across multiple files
- Interactive REPL with agent mode
- Workspace-restricted operations with confirmation

## How it's different

**Claude Code (official)** : Uses API keys, per-token billing, offers paid models like opus and fable.
**ClaudeCode-Next** : Uses your browser session, completely free, offers models like haiku and sonnet.

## Best Practices

- Use gemini pro for reasoning and use claudecode-next with --prompt flag to use claude as a slave for coding.
- Use your favourite models for whatever tasks you like but save your tokens for the tasks that require less reasoning and effort - like generating summary of a page or a document, rephrasing a text or a code, minimizing code, etc.

## Installation

```bash
pip install claudecode-next
```

For browser automation and automated cookie extraction:
```bash
pip install "claudecode-next[browser]"
playwright install chromium
```

## Quick Start

```bash
claudecode-next --auto-fetch
```

### Direct Prompts
```bash
claudecode-next --prompt "Explain quantum computing in simple terms"
```

Specify a model:
```bash
claudecode-next --model opus --prompt "Write a high-performance HTTP server in Rust"
```

> you may use claude as a slave using --prompt flag as discussed in this [reddit post](https://www.reddit.com/r/ChatGPTCoding/s/4KJ7NL8bf6)

### Agent Mode
Run the autonomous coding agent on a task:
```bash
claudecode-next --agent "Refactor utils.py to use pathlib"
```

### Credential Setup
Login via browser to capture session credentials:
```bash
claudecode-next --login
```
Or auto-fetch cookies from an existing Chrome session:
```bash
claudecode-next --auto-fetch
```
Or enter credentials manually:
```bash
claudecode-next --manual
```

## ⚠️ Disclaimer

This is an **unofficial, research-grade tool**. It's not endorsed by Anthropic, uses the Claude.ai web interface (which may violate ToS), and can break at any time, **developers won't be responsible for any misuse and damage caused by it**. Use responsibly and at your own risk.

### Credits
This is fork of [claude-ai-reclient](https://github.com/Adithyan-Defender/claude-ai-re-client). I have taken the liberty to implement agentic capabilities into it. I would like to thank the original author for providing the base code.
