"""REPL command handlers and interactive mode helpers."""
from .config import MODEL_ALIASES


def print_help():
    print("""
  â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
  â•‘                    COMMANDS                         â•‘
  â• â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•£
  â•‘  /model <name>     Switch model                     â•‘
  â•‘  /models           List all models                  â•‘
  â•‘  /stealth on|off   Toggle cleanup on exit           â•‘
  â•‘  /new              Start fresh conversation         â•‘
  â•‘  /cleanup          Delete session conv NOW          â•‘
  â•‘  /clear-session    Wipe stored credentials          â•‘
  â•‘  /help             Show this help                   â•‘
  â•‘  exit              Quit (auto-cleans if stealth)    â•‘
  â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
""")


def print_models(current):
    print("\n  Available models:")
    for alias, full in MODEL_ALIASES.items():
        marker = " <--" if full == current else ""
        tier = "PRO" if "opus" in alias else "FREE"
        print(f"    {alias:14s}  {full:36s}  [{tier}]{marker}")
    print()


def handle_command(
    cmd,
    arg,
    *,
    model,
    stealth,
    session,
    creds,
    cleanup_session_fn,
):
    """Handle a REPL command. Returns (should_continue, new_model, new_stealth, should_break).

    The caller should check should_break to exit the REPL loop.
    """
    if cmd == "/help":
        print_help()
        return True, model, stealth, False

    elif cmd == "/models":
        print_models(model)
        return True, model, stealth, False

    elif cmd == "/model":
        if not arg:
            print(f"  Current: {model}")
            print(f"  Usage: /model haiku|sonnet|opus|sonnet-4-5")
        else:
            from .config import resolve_model
            new = resolve_model(arg)
            if new != model:
                cleanup_session_fn()
                session["conv_id"] = None
                session["created"] = False
                model = new
                print(f"  [+] Model -> {model} (new session)")
            else:
                print(f"  [+] Already on {model}")
        return True, model, stealth, False

    elif cmd == "/stealth":
        if arg.lower() in ("on", "1", "true"):
            stealth = True
            print("  [+] Stealth ON (cleanup on exit)")
        elif arg.lower() in ("off", "0", "false"):
            stealth = False
            print("  [+] Stealth OFF (conversations kept)")
        else:
            print(f"  Stealth: {'ON' if stealth else 'OFF'}")
            print(f"  Usage: /stealth on|off")
        return True, model, stealth, False

    elif cmd == "/new":
        cleanup_session_fn()
        session["conv_id"] = None
        session["created"] = False
        print("  [+] Fresh conversation (next prompt starts new)")
        return True, model, stealth, False

    elif cmd == "/cleanup":
        cleanup_session_fn()
        return True, model, stealth, False

    elif cmd == "/clear-session":
        creds.clear()
        print("  [!] Session wiped. Re-run --auto-fetch to continue.")
        return True, model, stealth, True  # signal to break

    else:
        print(f"  [!] Unknown command: {cmd}. Try /help")
        return True, model, stealth, False