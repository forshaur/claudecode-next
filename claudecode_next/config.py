"""Configuration, constants, and model definitions."""
import datetime
import os
import sys

# â”€â”€ Dependency Check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import requests as std_requests
except ImportError:
    std_requests = None

if not HAS_CFFI and not std_requests:
    print("[!] pip install curl_cffi")
    sys.exit(1)

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(DIR, "claude_profile")

if sys.platform == "win32":
    _CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "claude_re")
else:
    _CONFIG_DIR = os.path.expanduser("~/.config/claude_re")
os.makedirs(_CONFIG_DIR, exist_ok=True)
CRED_FILE = os.path.join(_CONFIG_DIR, "claude_session.json")

# â”€â”€ Network Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

URL_BASE = "https://claude.ai"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_MODEL = "claude-sonnet-4-6"

# â”€â”€ Model Aliases â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

MODEL_ALIASES = {
    # Current generation (FREE)
    "haiku":        "claude-haiku-4-5",
    "sonnet":       "claude-sonnet-4-6",
    "sonnet-4-5":   "claude-sonnet-4-5",
    # Dated snapshots (FREE)
    "haiku-snap":   "claude-haiku-4-5-20251001",
    "sonnet-snap":  "claude-sonnet-4-5-20250929",
    # Premium (PRO/MAX only)
    "opus":         "claude-opus-4-7",
    "opus-3":       "claude-3-opus-20240229",
}


def resolve_model(name):
    """Resolve shorthand or full model name."""
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    return name


# â”€â”€ Timezone Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _detect_timezone():
    """Detect system IANA timezone. Falls back to UTC with warning."""
    # Method 1: Python 3.9+ datetime.astimezone()
    try:
        tz = datetime.datetime.now().astimezone().tzinfo
        if hasattr(tz, 'key'):
            return tz.key
        name = tz.tzname(datetime.datetime.now())
        if name and '/' in name:
            return name
    except:  # noqa: E722
        pass

    # Method 2: try tzlocal (if installed)
    try:
        from tzlocal import get_localzone
        tz = str(get_localzone())
        if tz and '/' in tz:
            return tz
    except ImportError:
        pass

    # Method 3: Windows registry
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"
            )
            tz_name, _ = winreg.QueryValueEx(key, "TimeZoneKeyName")
            winreg.CloseKey(key)
            _win_to_iana = {
                "India Standard Time": "Asia/Kolkata",
                "Eastern Standard Time": "America/New_York",
                "Pacific Standard Time": "America/Los_Angeles",
                "Central Standard Time": "America/Chicago",
                "Mountain Standard Time": "America/Denver",
                "GMT Standard Time": "Europe/London",
                "Central European Standard Time": "Europe/Berlin",
                "Tokyo Standard Time": "Asia/Tokyo",
                "China Standard Time": "Asia/Shanghai",
                "AUS Eastern Standard Time": "Australia/Sydney",
            }
            if tz_name in _win_to_iana:
                return _win_to_iana[tz_name]
        except:  # noqa: E722
            pass

    # Method 4: /etc/timezone (Linux)
    try:
        with open("/etc/timezone") as f:
            tz = f.read().strip()
            if tz and '/' in tz:
                return tz
    except:  # noqa: E722
        pass

    print("[!] WARNING: Could not detect system timezone. Falling back to UTC.")
    return "Etc/UTC"


SYSTEM_TIMEZONE = _detect_timezone()

# â”€â”€ Payload Template â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

PAYLOAD_TEMPLATE = {
    "prompt": "",
    "model": DEFAULT_MODEL,
    "timezone": SYSTEM_TIMEZONE,
    "locale": "en-US",
    "rendering_mode": "messages",
    "turn_message_uuids": {
        "human_message_uuid": "",
        "assistant_message_uuid": ""
    },
    "attachments": [],
    "files": [],
    "sync_sources": []
}