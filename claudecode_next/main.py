"""CLI entry point for Claude.ai RE Client v4."""
import argparse
import json
import os
import sys
import time
import uuid

# UTF-8 reconfiguration for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except:  # noqa: E722
        pass

from .config import (
    DIR,
    CRED_FILE,
    HAS_CFFI,
    resolve_model,
    DEFAULT_MODEL,
)
from .credentials import CredentialManager
from .http import stream_prompt, _delete_conversation
from .chrome import do_login
from .repl import print_help, print_models, handle_command
from .agent import process_task


def _cleanup_session(creds, session, discrete):
    """Delete the session conversation if discrete is on."""
    if discrete and session.get("conv_id") and session.get("created"):
        print("\n[*] Cleaning up session conversation...")
        _delete_conversation(creds, session["conv_id"])
        print("[+] Session cleaned (invisible in browser)")
        session["conv_id"] = None
        session["created"] = False


def main():
    print()
    print("  ╔══════════════════════════════════════════════════════════════════════╗")
    print("  ║  ClaudeCode-Next | Github:https://github.com/forshaur/claudecode-next║")
    print("  ╚══════════════════════════════════════════════════════════════════════╝")
    print()

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
    ap.add_argument("--skip-dangerous-permissions", action="store_true", help="Auto-approve all tool calls")
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
            print("[!] Auto-fetch failed")
            return
    elif args.manual:
        creds.manual_input()
    elif args.org_id and args.cookie:
        creds.org_id = args.org_id
        creds.conv_id = args.conv_id or str(uuid.uuid4())
        creds._parse_cookies(args.cookie)
        creds.save()
    elif not creds.load():
        print("[!] No credentials. Use --manual, --auto-fetch, or --login")
        return

    if not creds.is_valid():
        print("[!] Invalid credentials")
        return

    # ── State ──────────────────────────────────────────────────────────────────
    model = resolve_model(args.model)
    discrete = not args.no_discrete

    # Session state: tracks the current conversation for memory
    session = {"conv_id": None, "created": False}

    lib = "curl_cffi" if HAS_CFFI else "requests"
    mode = "discrete" if discrete else "visible"
    agent_mode = False  # toggle for agent mode
    print(f"[+] model:   {model}")
    print(f"[+] tz:      (auto-detected)")
    print(f"[+] http:    {lib}")
    print(f"[+] discrete: {mode}  (memory ON, cleanup on exit)")
    print(f"[+] creds:   {CRED_FILE}")
    print(f"[+] Type /help for commands")
    print(f"[+] Agent mode: /agent to toggle (workspace: {args.workspace})")
    print()

    # ── Jailbreak mode ─────────────────────────────────────────────────────────
    if args.jailbreak:
        if not os.path.exists(args.jailbreak):
            print(f"[!] File not found: {args.jailbreak}")
            return
        with open(args.jailbreak, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
        stream_prompt(creds, prompt, model, discrete, session)
        _cleanup_session(creds, session, discrete)
        return

    # ── Batch mode ─────────────────────────────────────────────────────────────
    if args.batch:
        if not os.path.exists(args.batch):
            print(f"[!] File not found: {args.batch}")
            return
        with open(args.batch, "r", encoding="utf-8") as f:
            prompts = [l.strip() for l in f if l.strip()]
        results = []
        for i, p in enumerate(prompts):
            print(f"  [{i+1}/{len(prompts)}] {p[:60]}")
            r = stream_prompt(creds, p, model, discrete, session)
            results.append({"prompt": p, "response": r or ""})
            if i < len(prompts) - 1:
                time.sleep(2)
        out = os.path.join(DIR, "batch_results.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved -> {out}")
        _cleanup_session(creds, session, discrete)
        return

    # ── Single prompt ──────────────────────────────────────────────────────────
    if args.prompt:
        stream_prompt(creds, args.prompt, model, discrete, session)
        _cleanup_session(creds, session, discrete)
        return

    # ── Interactive REPL ──────────────────────────────────────────────────────
    try:
        while True:
            try:
                inp = input("  You> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not inp:
                continue
            if inp.lower() in ("exit", "quit", "q"):
                break

            # Toggle agent mode
            if inp.startswith("/agent"):
                agent_mode = not agent_mode
                print(f"[+] Agent mode {'ON' if agent_mode else 'OFF'}")
                continue

            # ── REPL commands ──────────────────────────────────────────────────
            if inp.startswith("/"):
                parts = inp.split(None, 1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                should_continue, model, discrete, should_break = handle_command(
                    cmd,
                    arg,
                    model=model,
                    discrete=discrete,
                    session=session,
                    creds=creds,
                    cleanup_session_fn=lambda: _cleanup_session(creds, session, discrete),
                )
                if should_break:
                    break
                continue

            # ── Send prompt ────────────────────────────────────────────────────
            if agent_mode:
                print()
                process_task(creds, inp, model, discrete, session, workspace=args.workspace, skip_confirm=args.skip_dangerous_permissions)
            else:
                print()
                stream_prompt(creds, inp, model, discrete, session)
    finally:
        # Always cleanup on exit
        _cleanup_session(creds, session, discrete)


if __name__ == "__main__":
    main()