"""REPL command handlers and interactive mode helpers."""
from .config import MODEL_ALIASES

HELP = """
  COMMANDS
  /model <name>      Switch model
  /models            List all models
  /discrete on|off   Toggle cleanup on exit
  /new               Start fresh conversation
  /cleanup           Delete session conv NOW
  /agent             Toggle agent mode (tool calling)
  /clear-session     Wipe stored credentials
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


def handle_command(cmd, arg, *, model, discrete, session, creds, cleanup_session_fn):
    """Handle a REPL command. Returns (should_continue, new_model, new_discrete, should_break)."""

    def reset_session():
        cleanup_session_fn()
        session["conv_id"] = None
        session["created"] = False

    if cmd == "/help":
        print_help()

    elif cmd == "/models":
        print_models(model)

    elif cmd == "/model":
        if not arg:
            print(f"  Current: {model}")
            print("  Usage: /model haiku|sonnet|opus|sonnet-4-5")
        else:
            from .config import resolve_model
            new = resolve_model(arg)
            if new != model:
                reset_session()
                model = new
                print(f"  [+] Model -> {model} (new session)")
            else:
                print(f"  [+] Already on {model}")

    elif cmd == "/discrete":
        if arg.lower() in ("on", "1", "true"):
            discrete = True
            print("  [+] discrete ON (cleanup on exit)")
        elif arg.lower() in ("off", "0", "false"):
            discrete = False
            print("  [+] discrete OFF (conversations kept)")
        else:
            print(f"  discrete: {'ON' if discrete else 'OFF'}")
            print("  Usage: /discrete on|off")

    elif cmd == "/new":
        reset_session()
        print("  [+] Fresh conversation (next prompt starts new)")

    elif cmd == "/cleanup":
        cleanup_session_fn()

    elif cmd == "/clear-session":
        creds.clear()
        print("  [!] Session wiped. Re-run --auto-fetch to continue.")
        return True, model, discrete, True

    else:
        print(f"  [!] Unknown command: {cmd}. Try /help")

    return True, model, discrete, False