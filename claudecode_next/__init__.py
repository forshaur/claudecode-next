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
]

from .config import resolve_model, MODEL_ALIASES, DEFAULT_MODEL
from .credentials import CredentialManager
# We don't need to import stream_prompt here anymore – it's in providers
from .providers.claude import stream_prompt, build_payload
from .chrome import do_login, find_chrome