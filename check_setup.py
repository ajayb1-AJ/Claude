#!/usr/bin/env python3
"""Preflight check — run this to verify your setup before the first video.

    python check_setup.py

Prints a pass/fail checklist for Python, ffmpeg, dependencies, your .env keys,
and the Gujarati subtitle font. Exit code 0 = ready to go.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results: list[bool] = []


def check(ok: bool, label: str, hint: str = "", warn_only: bool = False) -> None:
    tag = OK if ok else (WARN if warn_only else FAIL)
    print(f"{tag}  {label}")
    if not ok and hint:
        print(f"        -> {hint}")
    if not warn_only:
        results.append(ok)


def main(live: bool = False) -> int:
    print("=" * 60)
    print(" Gujarati YouTube automation — setup check")
    if live:
        print(" (live mode: contacting Anthropic + ElevenLabs to verify keys)")
    print("=" * 60)

    # 1. Python version -----------------------------------------------------
    v = sys.version_info
    check(
        v >= (3, 10),
        f"Python {v.major}.{v.minor}.{v.micro}",
        "Install Python 3.10+ from python.org and re-run.",
    )

    # 2. Are we in a virtualenv? (nice to have) -----------------------------
    in_venv = sys.prefix != sys.base_prefix
    check(in_venv, "Running inside a virtual environment",
          "Recommended: python -m venv .venv && .venv\\Scripts\\activate",
          warn_only=True)

    # 3. ffmpeg on PATH -----------------------------------------------------
    check(
        shutil.which("ffmpeg") is not None,
        "ffmpeg is installed and on PATH",
        "Install it (winget install Gyan.FFmpeg) then REOPEN your terminal.",
    )

    # 4. Python dependencies ------------------------------------------------
    deps = {
        "anthropic": "anthropic",
        "requests": "requests",
        "yaml": "PyYAML",
        "dotenv": "python-dotenv",
        "googleapiclient": "google-api-python-client",
        "google_auth_oauthlib": "google-auth-oauthlib",
    }
    missing = [pip_name for mod, pip_name in deps.items() if not _importable(mod)]
    check(
        not missing,
        "Python dependencies installed",
        f"Run: pip install -r requirements.txt  (missing: {', '.join(missing)})",
    )

    # 5. .env exists + is well-formed + keys present -----------------------
    env_path = ROOT / ".env"
    check(env_path.exists(), ".env file exists",
          "Run: copy .env.example .env   then edit it.")
    if env_path.exists():
        bad = _env_problems(env_path)
        check(
            not bad,
            ".env is well-formed (every line is NAME=value)",
            "These lines are not NAME=value — fix or delete them: "
            + "; ".join(f"line {n}: {ln!r}" for n, ln in bad),
        )
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except Exception:
            pass
        _reload_env(env_path)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    check(
        anthropic_key.startswith("sk-ant-"),
        "ANTHROPIC_API_KEY is set (only needed for auto script generation)",
        "Not required if you use manual scripts: main.py --script-file story.txt",
        warn_only=True,
    )
    check(
        eleven_key.startswith("sk_") and len(eleven_key) > 20,
        "ELEVENLABS_API_KEY is set",
        "Add ELEVENLABS_API_KEY=sk_... to .env (one line, no tabs/labels/quotes)",
    )

    # 5b. Optionally verify the keys actually work (network) ----------------
    if live:
        _live_check("ANTHROPIC_API_KEY", anthropic_key, _verify_anthropic)
        _live_check("ELEVENLABS_API_KEY", eleven_key, _verify_elevenlabs)

    # 6. Optional keys ------------------------------------------------------
    has_stock = bool(
        os.getenv("PEXELS_API_KEY", "").strip() or os.getenv("PIXABAY_API_KEY", "").strip()
    )
    check(
        has_stock,
        "PEXELS_API_KEY or PIXABAY_API_KEY is set (optional — real stock photos)",
        "Free keys at pexels.com/api / pixabay.com/api; without them you get color slides.",
        warn_only=True,
    )

    # 7. Subtitle font ------------------------------------------------------
    font_ok = _font_present()
    check(
        font_ok,
        "Gujarati subtitle font present in assets/fonts/",
        "Download Noto Sans Gujarati (.ttf) into assets/fonts/",
    )

    # 8. config.yaml loads --------------------------------------------------
    cfg_ok = True
    try:
        sys.path.insert(0, str(ROOT))
        from src.config import Config
        cfg = Config.load()
        voice = cfg.get("voiceover", "default_voice_id")
        print(f"        (voice id: {voice}, format: {cfg.get('channel','format')})")
    except Exception as exc:
        cfg_ok = False
        print(f"        config error: {exc}")
    check(cfg_ok, "config.yaml loads")

    # 9. YouTube client secrets (only needed for upload) -------------------
    secrets = ROOT / os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
    check(
        secrets.exists(),
        "YouTube client_secrets.json present (needed only for upload)",
        "See README 'YouTube setup'. Not needed for --no-upload test runs.",
        warn_only=True,
    )

    # Summary ---------------------------------------------------------------
    print("-" * 60)
    if all(results):
        print("✅ All required checks passed — you're ready!")
        print('   Try:  python main.py --topic "સાચી મહેનતનું ફળ" --no-upload')
        return 0
    n_fail = results.count(False)
    print(f"❌ {n_fail} required check(s) failed. Fix the [FAIL] items above and re-run.")
    return 1


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _reload_env(env_path: Path) -> None:
    """Load .env manually too, in case python-dotenv isn't installed.
    utf-8-sig strips a BOM that editors (or PowerShell) may prepend."""
    for line in env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def _env_problems(env_path: Path) -> list[tuple[int, str]]:
    """Return (line_no, text) for every .env line that is not blank, not a
    comment, and not a valid NAME=value (the cause of dotenv parse errors).
    Reads with utf-8-sig so a leading BOM is not mistaken for a bad line."""
    bad: list[tuple[int, str]] = []
    for n, raw in enumerate(env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines(), 1):
        s = raw.strip().lstrip("﻿")
        if not s or s.startswith("#"):
            continue
        name, sep, _ = s.partition("=")
        name = name.strip()
        # Valid: NAME=... where NAME is a plain identifier (no spaces/tabs/labels).
        if not sep or not name or not all(c.isalnum() or c == "_" for c in name):
            bad.append((n, raw))
    return bad


def _live_check(label: str, key: str, verifier) -> None:
    if not key:
        check(False, f"{label} works (live)", "key not set, so nothing to test")
        return
    ok, detail = verifier(key)
    check(ok, f"{label} works (live)", detail)


def _verify_anthropic(key: str) -> tuple[bool, str]:
    try:
        from anthropic import Anthropic
        Anthropic(api_key=key).models.list()
        return True, ""
    except Exception as exc:
        return False, f"Anthropic rejected the key: {str(exc)[:160]}"


def _verify_elevenlabs(key: str) -> tuple[bool, str]:
    """A valid key should reach /v1/user or /v1/voices. A 401 'missing the
    permission' means the key is restricted — make a full-access key."""
    try:
        import requests
        for ep in ("https://api.elevenlabs.io/v1/user", "https://api.elevenlabs.io/v1/voices"):
            r = requests.get(ep, headers={"xi-api-key": key}, timeout=20)
            if r.status_code == 200:
                return True, ""
            last = (r.status_code, r.text[:160])
        if last[0] == 401 and "permission" in last[1].lower():
            return False, ("key is RESTRICTED. In ElevenLabs, create an API key with "
                           "full access (or at least Text-to-Speech + Voices), then update .env.")
        return False, f"ElevenLabs returned HTTP {last[0]}: {last[1]}"
    except Exception as exc:
        return False, f"ElevenLabs request failed: {str(exc)[:160]}"


def _font_present() -> bool:
    fonts = ROOT / "assets" / "fonts"
    if not fonts.exists():
        return False
    return any(p.suffix.lower() in {".ttf", ".otf"} for p in fonts.iterdir())


if __name__ == "__main__":
    raise SystemExit(main(live="--live" in sys.argv))
