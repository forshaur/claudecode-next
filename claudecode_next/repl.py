"""REPL command handlers, status line, and completers."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.syntax import Syntax

from .config import MODEL_ALIASES, resolve_model, EDITOR, DEEPSEEK_MODEL_ALIASES
from .config import DEEPSEEK_SESSION_FILE
if DEEPSEEK_SESSION_FILE.exists():
    print("  DeepSeek session: ✅ found")

    
# ----------------------------------------------------------------------
# Status line
# ----------------------------------------------------------------------

def get_status_line(model: str, discrete: bool, agent_mode: bool,
                    workspace: str, conv_id: str, streaming: bool = False,
                    elapsed: float = 0, provider: str = "claude") -> str:
    """Return a formatted status line for the bottom toolbar."""
    parts = []
    parts.append(f"[bold cyan]Provider:[/] {provider}")
    parts.append(f"[bold cyan]Model:[/] {model}")
    parts.append(f"[{'red' if discrete else 'green'}]Discrete: {'ON' if discrete else 'OFF'}[/]")
    parts.append(f"[{'yellow' if agent_mode else 'white'}]Agent: {'ON' if agent_mode else 'OFF'}[/]")
    parts.append(f"[magenta]Workspace:[/] {workspace}")
    if conv_id:
        parts.append(f"[dim]Conv: {conv_id[:8]}…[/]")
    if streaming:
        spin = "⣾⣽⣻⢿⡿⣟⣯⣷"[int(elapsed * 10) % 8] if elapsed else "⣾"
        parts.append(f"[bold yellow]{spin} {elapsed:.1f}s[/]")
    return " │ ".join(parts)


# ----------------------------------------------------------------------
# Autocomplete
# ----------------------------------------------------------------------

COMMANDS = [
    '/help', '/models', '/model', '/discrete', '/new', '/cleanup',
    '/clear-session', '/agent', '/cd', '/pwd', '/inspect', '/rotate',
    '/toggle-confirm', '/system', '/doctor', '/log', '/provider'
]
cmd_completer = WordCompleter(COMMANDS, ignore_case=True)

# ----------------------------------------------------------------------
# Command handlers
# ----------------------------------------------------------------------

def handle_command(cmd: str, arg: str, *,
                   model: str, discrete: bool, session: dict,
                   creds, cleanup_session_fn, executor,
                   confirm_required: bool) -> Tuple[bool, str, bool, bool, bool]:
    """
    Process a command.

    Returns:
        (should_continue, new_model, new_discrete, should_break, new_confirm_required)
    """
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
        print_models(model)

    elif cmd == '/model':
        if not arg:
            print(f"  Current: {model}")
            print("  Usage: /model <name> (e.g., sonnet, haiku, instant, expert)")
        else:
            # Try Claude aliases first, then DeepSeek
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
        cleanup_session_fn()

    elif cmd == '/clear-session':
        # We'll handle both in main, but we can't delete deepseek from here easily.
        # Let the user use --clear-session from CLI.
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
        from .providers.claude import get_last_request_info   # we need to add this
        # We'll add a simple version; for now skip.
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
        from .repl import run_doctor
        run_doctor(creds)   # we'll adapt

    elif cmd == '/log':
        log_file = executor.workspace / "agent.log"
        if log_file.exists():
            lines = log_file.read_text().splitlines()[-20:]
            print("\n".join(lines[-20:]))
        else:
            print("  No agent.log found in workspace.")

    else:
        print(f"  [!] Unknown command: {cmd}. Try /help")

    return True, new_model, new_discrete, False, new_confirm


# ----------------------------------------------------------------------
# Help and models
# ----------------------------------------------------------------------

HELP = """
  COMMANDS
  /model <name>      Switch model (haiku/sonnet/opus/instant/expert)
  /models            List all models
  /discrete on|off   Toggle cleanup on exit
  /new               Start fresh conversation
  /cleanup           Delete session conv NOW
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
  /help              Show this help
  exit               Quit (auto-cleans if discrete)
"""

def print_help():
    print(HELP)

def print_models(current):
    print("\n  Claude models:")
    for alias, full in MODEL_ALIASES.items():
        marker = " <--" if full == current else ""
        tier = "PRO" if "opus" in alias else "FREE"
        print(f"    {alias:14s}  {full:36s}  [{tier}]{marker}")
    print("\n  DeepSeek models:")
    for alias, full in DEEPSEEK_MODEL_ALIASES.items():
        marker = " <--" if full == current else ""
        print(f"    {alias:14s}  {full:36s}{marker}")
    print()

# ----------------------------------------------------------------------
# Doctor (simplified)
# ----------------------------------------------------------------------

def run_doctor(creds):
    print("\n🔍 Running diagnostics...")
    # Check Claude creds if available
    from .credentials import CredentialManager
    cm = CredentialManager()
    if cm.is_valid():
        print("  Claude credentials: ✅ valid")
    else:
        print("  Claude credentials: ❌ missing or invalid")
    # Check DeepSeek session
    from pathlib import Path
    from .config import DEEPSEEK_SESSION_FILE
    if DEEPSEEK_SESSION_FILE.exists():
        print("  DeepSeek session: ✅ found")
    else:
        print("  DeepSeek session: ❌ not found (run --deepseek-login)")
    # Check Chrome
    from .chrome import find_chrome
    chrome = find_chrome()
    print(f"  Chrome executable: {'✅ found' if chrome else '❌ not found'}")
    # Check libraries
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