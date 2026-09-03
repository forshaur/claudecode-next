#!/usr/bin/env python3
"""
Claude.ai RE Client v4 — REST/SSE Security Research Tool
Features: Real-time streaming, model selection, stealth mode, credit optimizer.
Architecture: Capture creds once → Replay via CLI (no browser during prompts).
v4: Dynamic timezone, secure CDP (localhost-only), encrypted credential path.

Entry point: delegates to the modular package.
"""
import sys

if __package__ is None and not hasattr(sys, "frozen"):
    # Direct script execution — ensure the package is importable
    import os.path
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if _pkg_dir not in sys.path:
        sys.path.insert(0, _pkg_dir)

from claudecode_next.main import main

if __name__ == "__main__":
    main()