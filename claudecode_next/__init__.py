__version__ = "1.0.1"
__all__ = [
    "CredentialManager",
    "stream_prompt",
    "build_payload",
    "do_login",
    "find_chrome",
    "resolve_model",
    "MODEL_ALIASES",
    "DEFAULT_MODEL",
    "streaming_status",          # added
]

from .config import resolve_model, MODEL_ALIASES, DEFAULT_MODEL
from .credentials import CredentialManager
from .http import stream_prompt, build_payload
from .chrome import do_login, find_chrome
from .agent import streaming_status    # added