
"""Claude.ai RE Client v4 — REST/SSE Security Research Tool.

Features: Real-time streaming, model selection, discrete mode, credit optimizer.
Architecture: Capture creds once → Replay via CLI (no browser during prompts).
v4: Dynamic timezone, secure CDP (localhost-only), encrypted credential path.
"""

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
from .http import stream_prompt, build_payload
from .chrome import do_login, find_chrome