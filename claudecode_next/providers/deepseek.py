"""DeepSeek streaming – uses the local deepseek client with PoW."""

import sys
from ..deepseek import get_session, LoginRequired
from ..deepseek.client import DeepSeekClient
from ..config import DEEPSEEK_MODEL_ALIASES


def stream_prompt(creds, prompt, model, discrete, session_state,
                  quiet=False, system_prompt=None):
    # Resolve model alias, fallback to "default"
    resolved = DEEPSEEK_MODEL_ALIASES.get(model)
    if resolved is None:
        resolved = "default"
    model = resolved

    if creds is None:
        try:
            creds = get_session(allow_interactive=False)
        except LoginRequired:
            print("[!] DeepSeek session not found. Run `--deepseek-login` first.")
            raise

    if system_prompt:
        prompt = system_prompt + "\n\n" + prompt

    client = DeepSeekClient(session=creds, allow_interactive=False)
    try:
        conversation_id = session_state.get('conversation_id')
        if conversation_id is None:
            stream = client.stream(prompt, model=model, thinking=False, search=False)
        else:
            stream = client.stream(prompt, conversation_id=conversation_id,
                                   thinking=False, search=False)

        full_text = ""
        for chunk in stream:
            if not quiet:
                sys.stdout.write(chunk)
                sys.stdout.flush()
            full_text += chunk
        session_state['conversation_id'] = stream.conversation_id
        if not quiet:
            print()
        return full_text
    finally:
        client.close()