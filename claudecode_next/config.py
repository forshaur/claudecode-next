"""Configuration, constants, and model definitions."""
import datetime
import os
import sys
from pathlib import Path

# ---- Dependency check ----
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

# ---- Paths ----
DIR = Path(__file__).resolve().parent.parent   # project root

if sys.platform == "win32":
    _CONFIG_DIR = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "claude_re"
else:
    _CONFIG_DIR = Path(os.path.expanduser("~/.config/claude_re"))
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CRED_FILE = _CONFIG_DIR / "claude_session.json"
DEEPSEEK_SESSION_FILE = _CONFIG_DIR / "deepseek_session.json"
DEEPSEEK_PROFILE_DIR = DIR / "deepseek_profile"
PROFILE = DIR / "claude_profile"

# ---- Network Constants ----
URL_BASE = "https://claude.ai"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_MODEL = "claude-sonnet-4-6"

# ---- Claude Model Aliases ----
MODEL_ALIASES = {
    "haiku":        "claude-haiku-4-5",
    "sonnet":       "claude-sonnet-4-6",
    "sonnet-4-5":   "claude-sonnet-4-5",
    "haiku-snap":   "claude-haiku-4-5-20251001",
    "sonnet-snap":  "claude-sonnet-4-5-20250929",
    "opus":         "claude-opus-4-7",
    "opus-3":       "claude-3-opus-20240229",
}

def resolve_model(name):
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    return name

# ---- DeepSeek Aliases & Display Names ----
DEEPSEEK_MODEL_ALIASES = {
    "instant": "default",
    "expert": "expert",
    "deepseek": "default",
    "default": "default",
}

# Display names shown in /models
DEEPSEEK_MODEL_DISPLAY = {
    "default": "Instant (fast)",
    "expert": "Expert (powerful)",
}

DEFAULT_PROVIDER = "claude"
PROVIDERS = ["claude", "deepseek"]

# ---- Timezone detection ----
def _detect_timezone():
    try:
        tz = datetime.datetime.now().astimezone().tzinfo
        if hasattr(tz, 'key'):
            return tz.key
        name = tz.tzname(datetime.datetime.now())
        if name and '/' in name:
            return name
    except:  # noqa: E722
        pass

    try:
        from tzlocal import get_localzone
        tz = str(get_localzone())
        if tz and '/' in tz:
            return tz
    except ImportError:
        pass

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

# ---- Payload Template (Claude) ----
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

# ---- Editor ----
EDITOR = os.environ.get('EDITOR', 'nano')