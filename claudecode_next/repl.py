"""REPL command handlers, status line, and completers."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from rich.console import Console
from rich.syntax import Syntax

from .config import (
    MODEL_ALIASES,
    resolve_model,
    EDITOR,
    DEEPSEEK_MODEL_ALIASES,
    DEEPSEEK_MODEL_DISPLAY,
)

# ---- Global streaming status ----
streaming_status = {'active': False, 'start': 0.0}

# ---- Status line with FormattedText ----
def get_status_line(model: str, discrete: bool, agent_mode: bool,
                    workspace: str, conv_id: str, streaming: bool = False,
                    elapsed: float = 0, provider: str = "claude",
                    thinking: bool = False, search: bool = False):
    items = []
    items.append(('bold cyan', f'Provider: {provider}'))
    items.append(('', ' │ '))
    items.append(('bold cyan', f'Model: {model}'))
    items.append(('', ' │ '))

    if provider == "deepseek":
        items.append(('cyan', f'Think: {"ON" if thinking else "OFF"}'))
        items.append(('', ' │ '))
        items.append(('cyan', f'Search: {"ON" if search else "OFF"}'))
        items.append(('', ' │ '))
    else:
        color = 'red' if discrete else 'green'
        items.append((color, f'Discrete: {"ON" if discrete else "OFF"}'))
        items.append(('', ' │ '))

    items.append(('yellow' if agent_mode else 'white', f'Agent: {"ON" if agent_mode else "OFF"}'))
    items.append(('', ' │ '))
    items.append(('magenta', f'Workspace: {workspace}'))
    if conv_id:
        items.append(('', ' │ '))
        items.append(('dim', f'Conv: {conv_id[:8]}…'))
    if streaming:
        spin = "⣾⣽⣻⢿⡿⣟⣯⣷"[int(elapsed * 10) % 8] if elapsed else "⣾"
        items.append(('', ' │ '))
        items.append(('bold yellow', f'{spin} {elapsed:.1f}s'))
    return FormattedText(items)

# ---- Autocomplete ----
COMMANDS = [
    '/help', '/models', '/model', '/discrete', '/new', '/cleanup',
    '/clear-session', '/agent', '/cd', '/pwd', '/inspect', '/rotate',
    '/toggle-confirm', '/system', '/doctor', '/log', '/provider',
    '/think', '/search',
]
cmd_completer = WordCompleter(COMMANDS, ignore_case=True)

# ---- Command handlers ----
def handle_command(cmd: str, arg: str, *,
                   model: str, discrete: bool, session: dict,
                   creds, cleanup_session_fn, executor,
                   confirm_required: bool,
                   provider: str = "claude") -> Tuple[bool, str, bool, bool, bool]:
    console = Console()
    new_model = model
    new_discrete = discrete
    new_confirm = confirm_required

    def reset_session():
        cleanup_session_fn()
        session['conv_id'] = None
        session['conversation_id'] = None

    if cmd == '/help':
        print_help()

    elif cmd == '/models':
        print_models(model, provider)

    elif cmd == '/model':
        if not arg:
            print(f"  Current: {model}")
            print("  Usage: /model <name> (e.g., sonnet, haiku, instant, expert)")
        else:
            new = resolve_model(arg) if arg in MODEL_ALIASES else None
            if new is None:
                new = DEEPSEEK_MODEL_ALIASES.get(arg, arg)
            if new != model:
                reset_session()
                new_model = new
                print(f"  [+] Model -> {new_model} (new session)")
            else:
                print(f"  [+] Already on {model}")

    elif cmd == '/discrete':
        if provider == "deepseek":
            print("  [!] discrete mode is not supported for DeepSeek")
        else:
            if arg.lower() in ('on', '1', 'true'):
                new_discrete = True
                print("  [+] discrete ON (cleanup on exit)")
            elif arg.lower() in ('off', '0', 'false'):
                new_discrete = False
                print("  [+] discrete OFF (conversations kept)")
            else:
                print(f"  discrete: {'ON' if discrete else 'OFF'}")
                print("  Usage: /discrete on|off")

    elif cmd == '/new':
        reset_session()
        print("  [+] Fresh conversation (next prompt starts new)")

    elif cmd == '/cleanup':
        if provider == "deepseek":
            print("  [!] cleanup is not needed for DeepSeek (conversations persist)")
        else:
            cleanup_session_fn()

    elif cmd == '/clear-session':
        print("  Use --clear-session from the command line to wipe all credentials.")

    elif cmd == '/cd':
        if not arg:
            print(f"  Current workspace: {executor.workspace}")
        else:
            new_path = Path(arg)
            if not new_path.is_absolute():
                new_path = Path(os.getcwd()) / new_path
            new_path = new_path.resolve()
            if new_path.exists() and new_path.is_dir():
                executor.workspace = new_path
                os.chdir(new_path)
                print(f"  [+] Workspace changed to {new_path}")
            else:
                print(f"  [!] Not a directory: {arg}")

    elif cmd == '/pwd':
        print(f"  {os.getcwd()}")

    elif cmd == '/inspect':
        print("  Inspect not implemented for DeepSeek yet.")

    elif cmd == '/rotate':
        reset_session()
        import uuid
        session['conv_id'] = str(uuid.uuid4())
        print(f"  [+] Rotated to new conversation: {session['conv_id']}")

    elif cmd == '/toggle-confirm':
        new_confirm = not confirm_required
        print(f"  [+] Tool confirmations {'ENABLED' if new_confirm else 'DISABLED'}")

    elif cmd == '/system':
        if arg == 'edit':
            prompt_path = Path(__file__).parent / 'system_prompt.txt'
            if prompt_path.exists():
                subprocess.call([EDITOR, str(prompt_path)])
                print(f"  [+] Edited system prompt: {prompt_path}")
            else:
                print(f"  [!] System prompt not found at {prompt_path}")
        elif arg == 'show':
            prompt_path = Path(__file__).parent / 'system_prompt.txt'
            if prompt_path.exists():
                console.print(Syntax(prompt_path.read_text(), 'markdown', theme='monokai'))
            else:
                print("  [!] No system_prompt.txt found.")
        else:
            print("  Usage: /system edit|show")

    elif cmd == '/doctor':
        # run_doctor is defined in this module – no import needed
        run_doctor(creds)

    elif cmd == '/log':
        log_file = executor.workspace / "agent.log"
        if log_file.exists():
            lines = log_file.read_text().splitlines()[-20:]
            print("\n".join(lines[-20:]))
        else:
            print("  No agent.log found in workspace.")

    elif cmd == '/think':
        if arg.lower() in ('on', '1', 'true'):
            session['thinking_enabled'] = True
            print("  [+] DeepThink ENABLED (next prompts will show reasoning)")
        elif arg.lower() in ('off', '0', 'false'):
            session['thinking_enabled'] = False
            print("  [+] DeepThink DISABLED")
        else:
            current = session.get('thinking_enabled', False)
            print(f"  DeepThink is {'ON' if current else 'OFF'}")
            print("  Usage: /think on|off")

    elif cmd == '/search':
        if arg.lower() in ('on', '1', 'true'):
            session['search_enabled'] = True
            print("  [+] Web Search ENABLED (will fetch online information)")
        elif arg.lower() in ('off', '0', 'false'):
            session['search_enabled'] = False
            print("  [+] Web Search DISABLED")
        else:
            current = session.get('search_enabled', False)
            print(f"  Web Search is {'ON' if current else 'OFF'}")
            print("  Usage: /search on|off")

    else:
        print(f"  [!] Unknown command: {cmd}. Try /help")

    return True, new_model, new_discrete, False, new_confirm

# ---- Help and models ----
HELP = """
  COMMANDS
  /model <name>      Switch model (haiku/sonnet/opus/instant/expert)
  /models            List all models
  /discrete on|off   Toggle cleanup on exit (Claude only)
  /new               Start fresh conversation
  /cleanup           Delete session conv NOW (Claude only)
  /agent             Toggle agent mode (handled in main)
  /clear-session     Wipe stored credentials (use from CLI)
  /cd <path>         Change workspace
  /pwd               Show current workspace
  /inspect           Show last HTTP request/response (Claude only)
  /rotate            Force new conversation ID
  /toggle-confirm    Toggle tool confirmation prompt
  /system edit|show  Edit or view system prompt
  /doctor            Run environment diagnostics
  /log               Show last 20 lines of agent.log
  /provider          Switch between claude and deepseek
  /think on|off      Toggle DeepSeek DeepThink (reasoning)
  /search on|off     Toggle DeepSeek web search
  /help              Show this help
  exit               Quit (auto-cleans if discrete)
"""

def print_help():
    print(HELP)

def print_models(current, provider="claude"):
    if provider == "claude":
        print("\n  Claude models:")
        for alias, full in MODEL_ALIASES.items():
            marker = " <--" if full == current else ""
            tier = "PRO" if "opus" in alias else "FREE"
            print(f"    {alias:14s}  {full:36s}  [{tier}]{marker}")
    else:
        print("\n  DeepSeek models (API values):")
        api_models = set(DEEPSEEK_MODEL_ALIASES.values())
        for api_model in sorted(api_models):
            display = DEEPSEEK_MODEL_DISPLAY.get(api_model, api_model)
            marker = " <--" if api_model == current else ""
            aliases = [k for k, v in DEEPSEEK_MODEL_ALIASES.items() if v == api_model]
            alias_str = f" (aliases: {', '.join(aliases)})" if len(aliases) > 1 else ""
            print(f"    {display:36s}  [{api_model}]{alias_str}{marker}")
    print()

def run_doctor(creds):
    print("\n🔍 Running diagnostics...")
    from .credentials import CredentialManager
    cm = CredentialManager()
    if cm.is_valid():
        print("  Claude credentials: ✅ valid")
    else:
        print("  Claude credentials: ❌ missing or invalid")
    from pathlib import Path
    from .config import DEEPSEEK_SESSION_FILE
    if DEEPSEEK_SESSION_FILE.exists():
        print("  DeepSeek session: ✅ found")
    else:
        print("  DeepSeek session: ❌ not found (run --deepseek-login)")
    from .chrome import find_chrome
    chrome = find_chrome()
    print(f"  Chrome executable: {'✅ found' if chrome else '❌ not found'}")
    try:
        import curl_cffi
        print("  curl_cffi: ✅ installed")
    except:
        print("  curl_cffi: ❌ not installed")
    try:
        import wasmtime
        print("  wasmtime: ✅ installed")
    except:
        print("  wasmtime: ❌ not installed (required for DeepSeek PoW)")
    print("  Doctor complete.\n")