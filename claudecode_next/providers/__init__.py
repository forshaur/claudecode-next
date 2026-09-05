"""Provider abstraction – Claude or DeepSeek."""

from .claude import stream_prompt as claude_stream
from .deepseek import stream_prompt as deepseek_stream

PROVIDERS = {"claude": claude_stream, "deepseek": deepseek_stream}

def get_stream_function(provider: str):
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}. Choose from {list(PROVIDERS.keys())}")
    return PROVIDERS[provider]