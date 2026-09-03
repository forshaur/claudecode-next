"""HTTP operations: payload building, headers, streaming SSE."""
import copy
import json
import os
import re
import sys
import time
import uuid

from .config import (
    URL_BASE,
    UA,
    DEFAULT_MODEL,
    PAYLOAD_TEMPLATE,
    HAS_CFFI,
    cffi_requests,
    std_requests,
    DIR,
)


def build_payload(prompt, model=DEFAULT_MODEL):
    """Build a fresh payload with new UUIDs."""
    p = copy.deepcopy(PAYLOAD_TEMPLATE)
    p["prompt"] = prompt
    p["model"] = model
    p["turn_message_uuids"]["human_message_uuid"] = str(uuid.uuid4())
    p["turn_message_uuids"]["assistant_message_uuid"] = str(uuid.uuid4())
    return p


def _make_headers(creds, streaming=True):
    h = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Cookie": creds.cookie_header(),
    }
    if streaming:
        h["Accept"] = "text/event-stream"
        h["Referer"] = "https://claude.ai/"
        h["Origin"] = "https://claude.ai"
    return h


def _request(method, url, creds, streaming=False, **kw):
    headers = _make_headers(creds, streaming)
    fn = getattr(cffi_requests if HAS_CFFI else std_requests, method)
    if HAS_CFFI:
        kw["impersonate"] = "chrome"
    return fn(url, headers=headers, timeout=kw.pop("timeout", 15), **kw)


def _delete_conversation(creds, conv_id):
    """Delete a conversation."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations/{conv_id}"
    try:
        _request("delete", url, creds, timeout=10)
    except:  # noqa: E722
        pass  # best-effort cleanup


def _create_conversation(creds, conv_id, model):
    """Create a new conversation on the server (required before posting completion)."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations"
    payload = {"name": "", "model": model, "uuid": conv_id}
    try:
        resp = _request("post", url, creds, streaming=True, json=payload, timeout=15)
        return resp.status_code in (200, 201)
    except:  # noqa: E722
        return False


def _feed_sse_line(line, parts):
    """Parse one SSE 'data: ...' line, appending any streamed text to parts.
    Returns True if the stream is done (message_stop or [DONE])."""
    line = line.strip()
    if not line.startswith("data: "):
        return False
    data = line[6:]
    if data.strip() == "[DONE]":
        return True
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return False
    t = obj.get("type", "")
    if t == "content_block_delta":
        delta = obj.get("delta", {})
        if delta.get("type") == "text_delta":
            txt = delta.get("text", "")
            parts.append(txt)
            sys.stdout.write(txt)
            sys.stdout.flush()
    elif t == "error":
        print(f"\n[!] {obj.get('error', {}).get('message', str(obj))}")
    elif t == "message_stop":
        return True
    return False


def _handle_rate_limit(resp, creds, prompt, model, discrete, quiet=False, system_prompt=None):
    """Handle 429: show wait time, auto-fallback to haiku if on heavier model."""
    retry = ""
    try:
        retry = resp.headers.get("Retry-After", "")
        if not retry:
            m = re.search(r'"retry_after":\s*(\d+)', resp.text[:500])
            if m:
                retry = m.group(1)
    except:  # noqa: E722
        pass

    print(f"\n[!] Rate limited. Retry after: {retry or 'unknown'}s")

    if model != "claude-haiku-4-5":
        print("[*] Falling back to haiku...")
        return stream_prompt(creds, prompt, "claude-haiku-4-5", discrete, quiet=quiet, system_prompt=system_prompt)

    try:
        wait = min(int(retry), 300)
    except (ValueError, TypeError):
        wait = 30
    print(f"[*] Waiting {wait}s...")
    time.sleep(wait)
    return stream_prompt(creds, prompt, model, discrete, quiet=quiet, system_prompt=system_prompt)


def stream_prompt(creds, prompt, model=DEFAULT_MODEL, discrete=True, session_state=None, quiet=False, system_prompt=None):
    """Send prompt with real-time streaming. Returns full response text.

    Session memory: uses ONE conversation for the entire session.
    If discrete=True, that conversation is deleted when the session ends (not per-prompt).
    session_state dict tracks: {'conv_id': str, 'created': bool}.
    If quiet=True, no output to stdout. If system_prompt given, prepended to prompt.
    """
    if session_state is not None:
        if not session_state.get("conv_id"):
            conv_id = str(uuid.uuid4())
            if not _create_conversation(creds, conv_id, model):
                print("\n[!] Failed to create conversation. Session may be expired.")
                return None
            session_state["conv_id"] = conv_id
            session_state["created"] = True
        conv_id = session_state["conv_id"]
    else:
        conv_id = creds.conv_id

    full_prompt = (system_prompt + "\n\n" + prompt) if system_prompt else prompt
    payload = build_payload(full_prompt, model)
    endpoint = (
        f"{URL_BASE}/api/organizations/{creds.org_id}"
        f"/chat_conversations/{conv_id}/completion"
    )
    headers = _make_headers(creds)

    parts = []
    buffer = ""
    raw_body = []

    def on_chunk(chunk: bytes):
        nonlocal buffer
        text = chunk.decode("utf-8", errors="replace")
        raw_body.append(text)
        buffer += text
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if _feed_sse_line(line, parts):
                return

    resp = None
    try:
        if HAS_CFFI:
            resp = cffi_requests.post(
                endpoint, json=payload, headers=headers, impersonate="chrome",
                content_callback=on_chunk, timeout=120,
            )
        else:
            resp = std_requests.post(endpoint, json=payload, headers=headers, timeout=120)
            if resp.status_code == 200:
                for line in resp.text.split("\n"):
                    if _feed_sse_line(line, parts):
                        break
    except Exception as e:
        print(f"\n[!] Request error: {e}")

    status_code = resp.status_code if resp else 0

    error_body = ""
    if not parts:
        full_raw = "".join(raw_body) + buffer
        if full_raw:
            try:
                err_obj = json.loads(full_raw.strip())
                if err_obj.get("type") == "error":
                    msg = err_obj.get("error", {}).get("message", str(err_obj))
                    code = err_obj.get("error", {}).get("error_code", "")
                    if "model" in code or "model" in msg.lower():
                        print(f"\n[!] Model '{model}' not available: {msg}")
                    else:
                        print(f"\n[!] Error: {msg}")
                    return None
            except json.JSONDecodeError:
                pass
            error_body = full_raw[:500]
        elif resp and resp.status_code != 200:
            try:
                error_body = resp.text[:500]
            except:  # noqa: E722
                pass

    if error_body and not parts:
        if "Just a moment" in error_body or "cloudflare" in error_body.lower():
            print("\n[!] Cloudflare blocked — run --auto-fetch again.")
        elif status_code == 401:
            print("\n[!] Session expired. Run --auto-fetch")
        elif status_code == 403:
            if "model" in error_body.lower():
                print(f"\n[!] Model '{model}' not available on your account tier.")
                print("    Try: /model sonnet")
            else:
                print(f"\n[!] 403: {error_body[:200]}")
        elif status_code == 429:
            return _handle_rate_limit(resp, creds, prompt, model, discrete, quiet=quiet, system_prompt=system_prompt)
        else:
            print(f"\n[!] HTTP {status_code}: {error_body[:200]}")
        return None

    full = "".join(parts)
    if not quiet:
        print()
    if full:
        with open(os.path.join(DIR, "last_response.txt"), "w", encoding="utf-8") as f:
            f.write(full)
    return full