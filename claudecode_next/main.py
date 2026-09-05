# main.py
"""CLI entry point with enhanced REPL, status bar, and commands."""
import argparse
import json
import os
import sys
import time
import uuid
import threading
from pathlib import Path

# UTF-8 reconfiguration for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except:  # noqa: E722
        pass

# Prompt toolkit
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.shortcuts import prompt as ptk_prompt
from prompt_toolkit.validation import Validator, ValidationError

# Rich
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .config import (
    DIR,
    CRED_FILE,
    HAS_CFFI,
    resolve_model,
    DEFAULT_MODEL,
)
from .credentials import CredentialManager
from .http import stream_prompt, _delete_conversation, get_last_request_info
from .chrome import do_login
from .repl import (
    get_status_line,
    cmd_completer,
    handle_command,
    print_help,
    print_models,
)
from .agent import process_task, streaming_status

console = Console()

# ----------------------------------------------------------------------
# Cleanup helper
# ----------------------------------------------------------------------

def _cleanup_session(creds, session, discrete):
    if discrete and session.get("conv_id") and session.get("created"):
        console.print("\n[*] Cleaning up session conversation...")
        _delete_conversation(creds, session["conv_id"])
        console.print("[+] Session cleaned (invisible in browser)")
        session["conv_id"] = None
        session["created"] = False

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    console.print()
    console.print(Panel.fit(
        "ClaudeCode-Next | Github: https://github.com/forshaur/claudecode-next",
        style="bold cyan"
    ))
    console.print()

    ap = argparse.ArgumentParser(description="Claude.ai Security Research Client v4")
    ap.add_argument("--login", action="store_true", help="Browser login (save profile)")
    ap.add_argument("--auto-fetch", action="store_true", help="Auto-extract creds via Chrome+CDP")
    ap.add_argument("--manual", action="store_true", help="Manual credential input")
    ap.add_argument("--prompt", type=str, help="Single prompt to send")
    ap.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Model: haiku/sonnet (default: sonnet)",
    )
    ap.add_argument("--org-id", type=str, help="Organization ID")
    ap.add_argument("--conv-id", type=str, help="Conversation ID")
    ap.add_argument("--cookie", type=str, help="Full Cookie header string")
    ap.add_argument("--jailbreak", type=str, help="Read prompt from file")
    ap.add_argument("--batch", type=str, help="Send multiple prompts from file")
    ap.add_argument("--no-discrete", action="store_true", help="Disable discrete mode")
    ap.add_argument("--clear-session", action="store_true", help="Delete stored credentials")
    ap.add_argument("--workspace", type=str, default=".", help="Workspace directory for agent mode")
    ap.add_argument("--dangerously-skip-permissions", action="store_true", help="Auto-approve all tool calls")
    args = ap.parse_args()

    # ── Clear session ──────────────────────────────────────────────────────────
    if args.clear_session:
        creds = CredentialManager()
        creds.clear()
        return

    # ── Login ──────────────────────────────────────────────────────────────────
    if args.login:
        do_login()
        return

    # ── Credential resolution ──────────────────────────────────────────────────
    creds = CredentialManager()

    if args.auto_fetch:
        if not creds.auto_fetch():
            console.print("[!] Auto-fetch failed")
            return
    elif args.manual:
        creds.manual_input()
    elif args.org_id and args.cookie:
        creds.org_id = args.org_id
        creds.conv_id = args.conv_id or str(uuid.uuid4())
        creds._parse_cookies(args.cookie)
        creds.save()
    elif not creds.load():
        console.print("[!] No credentials. Use --manual, --auto-fetch, or --login")
        return

    if not creds.is_valid():
        console.print("[!] Invalid credentials")
        return

    # ── State ──────────────────────────────────────────────────────────────────
    model = resolve_model(args.model)
    discrete = not args.no_discrete
    agent_mode = False
    confirm_required = not args.dangerously_skip_permissions

    # Session state
    session = {"conv_id": None, "created": False}

    # Workspace
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    lib = "curl_cffi" if HAS_CFFI else "requests"
    mode = "discrete" if discrete else "visible"
    console.print(f"[+] model:   {model}")
    console.print(f"[+] tz:      (auto-detected)")
    console.print(f"[+] http:    {lib}")
    console.print(f"[+] discrete: {mode}  (memory ON, cleanup on exit)")
    console.print(f"[+] creds:   {CRED_FILE}")
    console.print(f"[+] Type /help for commands")
    console.print(f"[+] Agent mode: /agent to toggle (workspace: {workspace})")
    console.print()

    # ── Single / batch / jailbreak mode ──────────────────────────────────────
    if args.jailbreak:
        if not os.path.exists(args.jailbreak):
            console.print(f"[!] File not found: {args.jailbreak}")
            return
        with open(args.jailbreak, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        # Set streaming status for UI
        streaming_status['active'] = True
        streaming_status['start'] = time.time()
        try:
            stream_prompt(creds, prompt, model, discrete, session)
        finally:
            streaming_status['active'] = False
        _cleanup_session(creds, session, discrete)
        return

    if args.batch:
        if not os.path.exists(args.batch):
            console.print(f"[!] File not found: {args.batch}")
            return
        with open(args.batch, "r", encoding="utf-8") as f:
            prompts = [l.strip() for l in f if l.strip()]
        results = []
        for i, p in enumerate(prompts):
            console.print(f"  [{i+1}/{len(prompts)}] {p[:60]}")
            streaming_status['active'] = True
            streaming_status['start'] = time.time()
            try:
                r = stream_prompt(creds, p, model, discrete, session)
            finally:
                streaming_status['active'] = False
            results.append({"prompt": p, "response": r or ""})
            if i < len(prompts) - 1:
                time.sleep(2)
        out = os.path.join(DIR, "batch_results.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        console.print(f"[+] Saved -> {out}")
        _cleanup_session(creds, session, discrete)
        return

    if args.prompt:
        streaming_status['active'] = True
        streaming_status['start'] = time.time()
        try:
            stream_prompt(creds, args.prompt, model, discrete, session)
        finally:
            streaming_status['active'] = False
        _cleanup_session(creds, session, discrete)
        return

    # ── Interactive REPL (with prompt_toolkit) ──────────────────────────────

    # History file
    history_file = os.path.join(DIR, ".claude_history")
    session_pt = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        completer=cmd_completer,
        # Bottom toolbar
        bottom_toolbar=lambda: get_status_line(
            model=model,
            discrete=discrete,
            agent_mode=agent_mode,
            workspace=str(workspace),
            conv_id=session.get('conv_id', ''),
            streaming=streaming_status['active'],
            elapsed=time.time() - streaming_status['start'] if streaming_status['active'] else 0,
        )
    )

    # Thread to update toolbar during streaming
    def update_toolbar():
        # This will be called periodically to refresh the toolbar
        # We can't easily force a refresh from outside; prompt_toolkit will
        # call the bottom_toolbar function on each key press.
        # For continuous updates during streaming, we need a different approach:
        # we can use a thread that calls app.invalidate() if we have the app instance.
        # We'll skip this for now and rely on the toolbar updating when user presses a key.
        # But we can at least update the streaming_status and the toolbar will refresh on next input.
        pass

    # We'll implement a simple spinner: we'll print a dot each second in the status bar
    # Actually, we can't print to status bar without user input. So we'll just let the
    # toolbar show the elapsed time, but it won't update until the user types.
    # For a real spinner, we would need to use a separate thread and call app.invalidate().
    # To keep it simple, we'll accept that the status bar shows the current state at the last prompt.

    try:
        # Import the app reference to invalidate? Not necessary for now.
        while True:
            try:
                inp = session_pt.prompt('You> ')
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            if not inp:
                continue
            if inp.lower() in ('exit', 'quit', 'q'):
                break

            # Handle /agent toggle specially
            if inp.startswith('/agent'):
                agent_mode = not agent_mode
                console.print(f"[+] Agent mode {'ON' if agent_mode else 'OFF'}")
                continue

            # Other commands
            if inp.startswith('/'):
                parts = inp.split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                # For commands that need the executor, we create a temporary one if in agent mode?
                # We'll pass the workspace path and let handle_command use it.
                # We'll instantiate an executor just for commands like /cd, /pwd, /log
                from .agent import ToolExecutor
                temp_executor = ToolExecutor(workspace)

                should_continue, new_model, new_discrete, should_break, new_confirm = handle_command(
                    cmd, arg,
                    model=model,
                    discrete=discrete,
                    session=session,
                    creds=creds,
                    cleanup_session_fn=lambda: _cleanup_session(creds, session, discrete),
                    executor=temp_executor,
                    confirm_required=confirm_required,
                )
                model = new_model
                discrete = new_discrete
                confirm_required = new_confirm
                if should_break:
                    break
                continue

            # ── Send prompt ────────────────────────────────────────────────────
            console.print()
            if agent_mode:
                # For agent mode, we need to pass confirm_required
                # The agent's _confirm uses self.confirm_required which is set from skip_confirm
                # We'll pass the flag to process_task
                # We'll set skip_confirm = not confirm_required
                skip = not confirm_required
                streaming_status['active'] = True
                streaming_status['start'] = time.time()
                try:
                    process_task(
                        creds, inp, model, discrete, session,
                        workspace=str(workspace),
                        skip_confirm=skip
                    )
                finally:
                    streaming_status['active'] = False
            else:
                streaming_status['active'] = True
                streaming_status['start'] = time.time()
                try:
                    stream_prompt(creds, inp, model, discrete, session)
                finally:
                    streaming_status['active'] = False
    finally:
        _cleanup_session(creds, session, discrete)

if __name__ == "__main__":
    main()