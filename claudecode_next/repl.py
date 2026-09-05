# repl.py
"""REPL command handlers, status line, and completers."""
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from .config import MODEL_ALIASES, resolve_model, EDITOR

# ----------------------------------------------------------------------
# Status line
# ----------------------------------------------------------------------

def get_status_line(model: str, discrete: bool, agent_mode: bool,
                    workspace: str, conv_id: str, streaming: bool = False,
                    elapsed: float = 0) -> str:
    """Return a formatted status line for the bottom toolbar."""
    parts = []
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
    '/toggle-confirm', '/system', '/doctor', '/log'
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
        session['created'] = False

    if cmd == '/help':
        print(HELP)

    elif cmd == '/models':
        print_models(model)

    elif cmd == '/model':
        if not arg:
            print(f"  Current: {model}")
            print("  Usage: /model haiku|sonnet|opus|sonnet-4-5")
        else:
            new = resolve_model(arg)
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
        creds.clear()
        print("  [!] Session wiped. Re-run --auto-fetch to continue.")
        return True, new_model, new_discrete, True, new_confirm

    elif cmd == '/agent':
        # toggled in main, but we handle it here
        pass

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
        from .http import get_last_request_info
        info = get_last_request_info()
        if not info['url']:
            print("  No request has been sent yet.")
        else:
            console.print(f"[bold]URL:[/] {info['url']}")
            console.print(f"[bold]Method:[/] {info['method']}")
            console.print(f"[bold]Timestamp:[/] {info['timestamp']}")
            console.print("[bold]Headers:[/]")
            for k, v in info['headers'].items():
                console.print(f"  {k}: {v}")
            console.print("[bold]Payload:[/]")
            console.print(info['payload'])
            console.print(f"[bold]Response Status:[/] {info['response_status']}")
            console.print("[bold]Response Headers:[/]")
            if info['response_headers']:
                for k, v in info['response_headers'].items():
                    console.print(f"  {k}: {v}")
            console.print("[bold]Response Preview:[/]")
            if info['response_body_preview']:
                console.print(info['response_body_preview'][:500])
            else:
                console.print("  (empty)")

    elif cmd == '/rotate':
        reset_session()
        # Generate new conv_id
        import uuid
        session['conv_id'] = str(uuid.uuid4())
        print(f"  [+] Rotated to new conversation: {session['conv_id']}")

    elif cmd == '/toggle-confirm':
        new_confirm = not confirm_required
        print(f"  [+] Tool confirmations {'ENABLED' if new_confirm else 'DISABLED'}")
        # Store in executor? We'll pass around.

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
        run_doctor(creds)

    elif cmd == '/log':
        # Tail agent.log
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
  /model <name>      Switch model (haiku/sonnet/opus)
  /models            List all models
  /discrete on|off   Toggle cleanup on exit
  /new               Start fresh conversation
  /cleanup           Delete session conv NOW
  /agent             Toggle agent mode (handled in main)
  /clear-session     Wipe stored credentials
  /cd <path>         Change workspace
  /pwd               Show current workspace
  /inspect           Show last HTTP request/response
  /rotate            Force new conversation ID
  /toggle-confirm    Toggle tool confirmation prompt
  /system edit|show  Edit or view system prompt
  /doctor            Run environment diagnostics
  /log               Show last 20 lines of agent.log
  /help              Show this help
  exit               Quit (auto-cleans if discrete)
"""

def print_help():
    print(HELP)

def print_models(current):
    print("\n  Available models:")
    for alias, full in MODEL_ALIASES.items():
        marker = " <--" if full == current else ""
        tier = "PRO" if "opus" in alias else "FREE"
        print(f"    {alias:14s}  {full:36s}  [{tier}]{marker}")
    print()

# ----------------------------------------------------------------------
# Doctor
# ----------------------------------------------------------------------

def run_doctor(creds):
    print("\n🔍 Running diagnostics...")
    # Check Chrome
    from .chrome import find_chrome
    chrome = find_chrome()
    print(f"  Chrome executable: {'✅ found' if chrome else '❌ not found'}")
    # Check credentials
    valid = creds.is_valid()
    print(f"  Credentials: {'✅ valid (sessionKey present)' if valid else '❌ missing or invalid'}")
    # Check network
    try:
        import socket
        socket.gethostbyname('claude.ai')
        print("  DNS resolution: ✅ claude.ai resolves")
    except:
        print("  DNS resolution: ❌ failed")
    # Check libraries
    try:
        import curl_cffi
        print("  curl_cffi: ✅ installed")
    except:
        print("  curl_cffi: ❌ not installed (fallback to requests)")
    # Check conversation creation
    if valid:
        print("  Testing conversation creation (requires active session)...")
        # We'll attempt a simple request? Not to spam.
        print("  (skipping to avoid rate limits)")
    print("  Doctor complete.\n")