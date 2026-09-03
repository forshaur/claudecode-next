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


def _make_headers(creds):
    return {
        "User-Agent": UA,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
        "Cookie": creds.cookie_header(),
    }


def _delete_conversation(creds, conv_id):
    """Delete a conversation so it doesn't appear in browser sidebar."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations/{conv_id}"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Cookie": creds.cookie_header(),
    }
    try:
        if HAS_CFFI:
            cffi_requests.delete(url, headers=headers, impersonate="chrome", timeout=10)
        elif std_requests:
            std_requests.delete(url, headers=headers, timeout=10)
    except:  # noqa: E722
        pass  # best-effort cleanup


def _create_conversation(creds, conv_id, model):
    """Create a new conversation on the server (required before posting completion)."""
    url = f"{URL_BASE}/api/organizations/{creds.org_id}/chat_conversations"
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
        "Cookie": creds.cookie_header(),
    }
    payload = {"name": "", "model": model, "uuid": conv_id}
    try:
        if HAS_CFFI:
            resp = cffi_requests.post(
                url, json=payload, headers=headers, impersonate="chrome", timeout=15
            )
        else:
            resp = std_requests.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201)
    except:  # noqa: E722
        return False


def stream_prompt(creds, prompt, model=DEFAULT_MODEL, stealth=True, session_state=None):
    """Send prompt with real-time streaming. Returns full response text.

    Session memory: uses ONE conversation for the entire session.
    If stealth=True, that conversation is deleted when the session ends (not per-prompt).
    session_state dict tracks: {'conv_id': str, 'created': bool}
    """

    # Determine conv_id: session-persistent or creds-based
    if session_state is not None:
        if not session_state.get("conv_id"):
            # First prompt in session â€” create a new conversation
            conv_id = str(uuid.uuid4())
            if not _create_conversation(creds, conv_id, model):
                print("\n[!] Failed to create conversation. Session may be expired.")
                return None
            session_state["conv_id"] = conv_id
            session_state["created"] = True
        conv_id = session_state["conv_id"]
    else:
        conv_id = creds.conv_id

    payload = build_payload(prompt, model)
    endpoint = (
        f"{URL_BASE}/api/organizations/{creds.org_id}"
        f"/chat_conversations/{conv_id}/completion"
    )
    headers = _make_headers(creds)

    parts = []
    buffer = ""
    raw_body = []  # capture everything for error detection
    error_body = ""
    status_code = [0]  # mutable for callback scope

    def on_chunk(chunk: bytes):
        nonlocal buffer
        text = chunk.decode("utf-8", errors="replace")
        raw_body.append(text)
        buffer += text
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data.strip() == "[DONE]":
                return
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            t = obj.get("type", "")
            if t == "content_block_delta":
                delta = obj.get("delta", {})
                if delta.get("type") == "text_delta":
                    txt = delta.get("text", "")
                    parts.append(txt)
                    sys.stdout.write(txt)
                    sys.stdout.flush()
            elif t == "error":
                err = obj.get("error", {})
                print(f"\n[!] {err.get('message', str(obj))}")
            elif t == "message_stop":
                return

    # â”€â”€ Send request â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    resp = None
    try:
        if HAS_CFFI:
            resp = cffi_requests.post(
                endpoint,
                json=payload,
                headers=headers,
                impersonate="chrome",
                content_callback=on_chunk,
                timeout=120,
            )
        else:
            # Fallback: standard requests with full body parse
            resp = std_requests.post(
                endpoint, json=payload, headers=headers, timeout=120
            )
    except Exception as e:
        print(f"\n[!] Request error: {e}")

    # â”€â”€ Handle non-streaming fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if resp and not HAS_CFFI:
        if resp.status_code == 200:
            text = resp.text
            for line in text.split("\n"):
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except:  # noqa: E722
                    continue
                t = obj.get("type", "")
                if t == "content_block_delta":
                    delta = obj.get("delta", {})
                    if delta.get("type") == "text_delta":
                        txt = delta.get("text", "")
                        parts.append(txt)
                        sys.stdout.write(txt)
                        sys.stdout.flush()

    # â”€â”€ Check status / detect errors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if resp:
        status_code[0] = resp.status_code

    # If callback got data but no SSE parts, check raw body for errors
    if not parts:
        full_raw = "".join(raw_body) + buffer
        if full_raw:
            # Try parsing as JSON error
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

    # â”€â”€ Error handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if error_body and not parts:
        sc = status_code[0]
        if "Just a moment" in error_body or "cloudflare" in error_body.lower():
            print(f"\n[!] Cloudflare blocked â€” run --auto-fetch again.")
        elif sc == 401:
            print(f"\n[!] Session expired. Run --auto-fetch")
        elif sc == 403:
            if "model" in error_body.lower():
                print(f"\n[!] Model '{model}' not available on your account tier.")
                print(f"    Try: /model sonnet")
            else:
                print(f"\n[!] 403: {error_body[:200]}")
        elif sc == 429:
            return _handle_rate_limit(resp, creds, prompt, model, stealth)
        else:
            print(f"\n[!] HTTP {sc}: {error_body[:200]}")
        return None

    full = "".join(parts)
    print()

    # â”€â”€ Save last response â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if full:
        with open(os.path.join(DIR, "last_response.txt"), "w", encoding="utf-8") as f:
            f.write(full)
    return full


def _handle_rate_limit(resp, creds, prompt, model, stealth):
    """Handle 429: show wait time, auto-fallback to haiku if on heavier model."""
    retry = "unknown"
    try:
        retry = resp.headers.get("Retry-After", "")
        if not retry:
            body = resp.text[:500]
            m = re.search(r'"retry_after":\s*(\d+)', body)
            if m:
                retry = m.group(1)
    except:  # noqa: E722
        pass

    print(f"\n[!] Rate limited. Retry after: {retry}s")

    # Auto-fallback to haiku if not already on it
    if model != "claude-haiku-4-5":
        print(f"[*] Falling back to haiku...")
        return stream_prompt(creds, prompt, "claude-haiku-4-5", stealth)

    # Already on haiku â€” wait and retry
    wait = 30
    try:
        wait = int(retry)
    except:  # noqa: E722
        pass
    wait = min(wait, 300)
    print(f"[*] Waiting {wait}s...")
    time.sleep(wait)
    return stream_prompt(creds, prompt, model, stealth)