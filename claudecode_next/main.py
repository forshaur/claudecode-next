"""CLI entry point with enhanced REPL, status bar, and commands."""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

# UTF‑8 reconfiguration for Windows
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

# Rich
from rich.console import Console
from rich.panel import Panel

from .config import (
    DIR,
    CRED_FILE,
    HAS_CFFI,
    resolve_model,
    DEFAULT_MODEL,
    DEEPSEEK_SESSION_FILE,
    DEEPSEEK_PROFILE_DIR,
    DEFAULT_PROVIDER,
)
from .credentials import CredentialManager
from .providers.claude import stream_prompt as claude_stream, _delete_conversation
from .providers.deepseek import stream_prompt as deepseek_stream
from .providers import get_stream_function
from .deepseek import login as deepseek_login, get_session as deepseek_get_session
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
# Cleanup helper (Claude-specific)
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

    ap = argparse.ArgumentParser(description="Claude.ai & DeepSeek Security Research Client")
    # Claude
    ap.add_argument("--login", action="store_true", help="Browser login for Claude (save profile)")
    ap.add_argument("--auto-fetch", action="store_true", help="Auto-extract Claude creds via Chrome+CDP")
    ap.add_argument("--manual", action="store_true", help="Manual Claude credential input")
    # DeepSeek
    ap.add_argument("--deepseek-login", action="store_true", help="Login to DeepSeek (opens browser once)")
    # General
    ap.add_argument("--prompt", type=str, help="Single prompt to send")
    ap.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Model: haiku/sonnet/opus (Claude) or instant/expert (DeepSeek)",
    )
    ap.add_argument("--org-id", type=str, help="Organization ID (Claude)")
    ap.add_argument("--conv-id", type=str, help="Conversation ID (Claude)")
    ap.add_argument("--cookie", type=str, help="Full Cookie header string (Claude)")
    ap.add_argument("--jailbreak", type=str, help="Read prompt from file")
    ap.add_argument("--batch", type=str, help="Send multiple prompts from file")
    ap.add_argument("--no-discrete", action="store_true", help="Disable discrete mode (Claude)")
    ap.add_argument("--clear-session", action="store_true", help="Delete stored credentials (both)")
    ap.add_argument("--workspace", type=str, default=".", help="Workspace directory for agent mode")
    ap.add_argument("--dangerously-skip-permissions", action="store_true", help="Auto-approve all tool calls")
    ap.add_argument("--provider", type=str, default=DEFAULT_PROVIDER,
                    help="Provider: claude or deepseek (default: claude)")
    args = ap.parse_args()

    # ── Clear session ──────────────────────────────────────────────────────────
    if args.clear_session:
        # Clear Claude
        creds = CredentialManager()
        creds.clear()
        # Clear DeepSeek
        if DEEPSEEK_SESSION_FILE.exists():
            os.remove(DEEPSEEK_SESSION_FILE)
            console.print(f"[+] DeepSeek session deleted: {DEEPSEEK_SESSION_FILE}")
        return

    # ── Login (Claude) ────────────────────────────────────────────────────────
    if args.login:
        do_login()
        return

    # ── DeepSeek Login ────────────────────────────────────────────────────────
    if args.deepseek_login:
        console.print("[*] Starting DeepSeek login (browser will open)...")
        session = deepseek_login(profile_dir=DEEPSEEK_PROFILE_DIR)
        console.print(f"[+] DeepSeek session saved to {DEEPSEEK_SESSION_FILE}")
        return

    # ── Credential resolution ──────────────────────────────────────────────────
    # Claude credentials
    claude_creds = CredentialManager()

    if args.auto_fetch:
        if not claude_creds.auto_fetch():
            console.print("[!] Auto-fetch failed")
            return
    elif args.manual:
        claude_creds.manual_input()
    elif args.org_id and args.cookie:
        claude_creds.org_id = args.org_id
        claude_creds.conv_id = args.conv_id or str(uuid.uuid4())
        claude_creds._parse_cookies(args.cookie)
        claude_creds.save()
    elif not claude_creds.load():
        console.print("[!] No Claude credentials. Use --manual, --auto-fetch, or --login")
        # If provider is deepseek, we might not need Claude creds.
        if args.provider == "deepseek":
            console.print("[*] Provider set to deepseek – Claude credentials not required.")
        else:
            return

    # DeepSeek session: load or create
    deepseek_session = None
    if args.provider == "deepseek":
        try:
            deepseek_session = deepseek_get_session(
                profile_dir=DEEPSEEK_PROFILE_DIR,
                session_file=DEEPSEEK_SESSION_FILE,
                allow_interactive=False
            )
        except Exception as e:
            console.print(f"[!] DeepSeek session not found or invalid. Run --deepseek-login first.")
            return

    # Validate credentials for the chosen provider
    if args.provider == "claude" and not claude_creds.is_valid():
        console.print("[!] Invalid Claude credentials")
        return

    # ── State ──────────────────────────────────────────────────────────────────
    # Resolve model name (Claude only; DeepSeek aliases are resolved inside the provider)
    model = resolve_model(args.model) if args.provider == "claude" else args.model
    discrete = not args.no_discrete
    agent_mode = False
    confirm_required = not args.dangerously_skip_permissions
    provider = args.provider

    # Session state (Claude: conv_id; DeepSeek: conversation_id)
    session = {"conv_id": None, "created": False, "conversation_id": None}
    if provider == "deepseek":
        session["conv_id"] = None   # unused

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    # ── Information display ────────────────────────────────────────────────────
    if provider == "claude":
        lib = "curl_cffi" if HAS_CFFI else "requests"
        creds_path = str(CRED_FILE)
        discrete_label = "discrete" if discrete else "visible"
    else:  # deepseek
        lib = "httpx"
        creds_path = str(DEEPSEEK_SESSION_FILE)
        discrete_label = "N/A (DeepSeek keeps conversations)"

    console.print(f"[+] provider: {provider}")
    console.print(f"[+] model:    {model}")
    console.print(f"[+] tz:       (auto-detected)")
    console.print(f"[+] http:     {lib}")
    console.print(f"[+] discrete: {discrete_label}")
    console.print(f"[+] creds:    {creds_path}")
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
        streaming_status['active'] = True
        streaming_status['start'] = time.time()
        try:
            stream_fn = get_stream_function(provider)
            stream_fn(claude_creds if provider=='claude' else deepseek_session,
                      prompt, model, discrete, session)
        finally:
            streaming_status['active'] = False
        if provider == "claude":
            _cleanup_session(claude_creds, session, discrete)
        return

    if args.batch:
        if not os.path.exists(args.batch):
            console.print(f"[!] File not found: {args.batch}")
            return
        with open(args.batch, "r", encoding="utf-8") as f:
            prompts = [l.strip() for l in f if l.strip()]
        results = []
        stream_fn = get_stream_function(provider)
        for i, p in enumerate(prompts):
            console.print(f"  [{i+1}/{len(prompts)}] {p[:60]}")
            streaming_status['active'] = True
            streaming_status['start'] = time.time()
            try:
                r = stream_fn(claude_creds if provider=='claude' else deepseek_session,
                              p, model, discrete, session)
            finally:
                streaming_status['active'] = False
            results.append({"prompt": p, "response": r or ""})
            if i < len(prompts) - 1:
                time.sleep(2)
        out = os.path.join(DIR, "batch_results.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        console.print(f"[+] Saved -> {out}")
        if provider == "claude":
            _cleanup_session(claude_creds, session, discrete)
        return

    if args.prompt:
        stream_fn = get_stream_function(provider)
        streaming_status['active'] = True
        streaming_status['start'] = time.time()
        try:
            stream_fn(claude_creds if provider=='claude' else deepseek_session,
                      args.prompt, model, discrete, session)
        finally:
            streaming_status['active'] = False
        if provider == "claude":
            _cleanup_session(claude_creds, session, discrete)
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────

    # History file
    history_file = os.path.join(DIR, ".claude_history")
    session_pt = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
        completer=cmd_completer,
        bottom_toolbar=lambda: get_status_line(
            model=model,
            discrete=discrete,
            agent_mode=agent_mode,
            workspace=str(workspace),
            conv_id=session.get('conv_id') or session.get('conversation_id', ''),
            streaming=streaming_status['active'],
            elapsed=time.time() - streaming_status['start'] if streaming_status['active'] else 0,
            provider=provider,
        )
    )

    try:
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

            # Handle /agent toggle
            if inp.startswith('/agent'):
                agent_mode = not agent_mode
                console.print(f"[+] Agent mode {'ON' if agent_mode else 'OFF'}")
                continue

            # Handle /provider switch
            if inp.startswith('/provider'):
                parts = inp.split()
                if len(parts) != 2:
                    console.print(f"  Usage: /provider claude|deepseek (current: {provider})")
                    continue
                new_provider = parts[1].lower()
                if new_provider not in ('claude', 'deepseek'):
                    console.print(f"  Invalid provider: {new_provider}. Choose claude or deepseek.")
                    continue
                if new_provider == provider:
                    console.print(f"  Already using {provider}")
                    continue
                # Switch provider
                if new_provider == 'deepseek':
                    # Ensure deepseek session exists
                    try:
                        ds = deepseek_get_session(
                            profile_dir=DEEPSEEK_PROFILE_DIR,
                            session_file=DEEPSEEK_SESSION_FILE,
                            allow_interactive=False
                        )
                        deepseek_session = ds
                        provider = 'deepseek'
                        session['conv_id'] = None
                        session['conversation_id'] = None
                        console.print("[+] Switched to DeepSeek")
                    except Exception as e:
                        console.print(f"[!] DeepSeek session not available. Run --deepseek-login first.")
                else:
                    # Switch to Claude
                    if not claude_creds.is_valid():
                        console.print("[!] Claude credentials invalid. Use --auto-fetch or --manual.")
                    else:
                        provider = 'claude'
                        session['conv_id'] = None
                        session['conversation_id'] = None
                        console.print("[+] Switched to Claude")
                continue

            # Other commands
            if inp.startswith('/'):
                parts = inp.split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                from .agent import ToolExecutor
                temp_executor = ToolExecutor(workspace)

                should_continue, new_model, new_discrete, should_break, new_confirm = handle_command(
                    cmd, arg,
                    model=model,
                    discrete=discrete,
                    session=session,
                    creds=claude_creds if provider=='claude' else deepseek_session,
                    cleanup_session_fn=lambda: _cleanup_session(claude_creds, session, discrete),
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
            stream_fn = get_stream_function(provider)
            if agent_mode:
                skip = not confirm_required
                streaming_status['active'] = True
                streaming_status['start'] = time.time()
                try:
                    process_task(
                        claude_creds if provider=='claude' else deepseek_session,
                        inp, model, discrete, session,
                        workspace=str(workspace),
                        provider=provider,
                        skip_confirm=skip
                    )
                finally:
                    streaming_status['active'] = False
            else:
                streaming_status['active'] = True
                streaming_status['start'] = time.time()
                try:
                    stream_fn(claude_creds if provider=='claude' else deepseek_session,
                              inp, model, discrete, session)
                finally:
                    streaming_status['active'] = False
    finally:
        if provider == "claude":
            _cleanup_session(claude_creds, session, discrete)


if __name__ == "__main__":
    main()