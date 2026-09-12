"""Load configuration from config.yaml + environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional at runtime
    pass

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    """Merged view of config.yaml plus secrets from the environment."""

    data: dict[str, Any]
    root: Path = ROOT

    # --- secrets (from .env / environment) ---
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", ""))
    pexels_api_key: str = field(default_factory=lambda: os.getenv("PEXELS_API_KEY", ""))
    pixabay_api_key: str = field(default_factory=lambda: os.getenv("PIXABAY_API_KEY", ""))
    youtube_client_secrets: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
    )
    youtube_token_file: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
    )

    @classmethod
    def load(cls, path: str | Path = ROOT / "config.yaml") -> "Config":
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(data=data)

    # Convenience accessors -------------------------------------------------
    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def resolution(self) -> tuple[int, int]:
        fmt = self.get("channel", "format", default="long")
        return (1080, 1920) if fmt == "short" else (1920, 1080)

    @property
    def is_short(self) -> bool:
        return self.get("channel", "format", default="long") == "short"

    def path(self, *parts: str) -> Path:
        """Resolve a path relative to the project root."""
        return self.root.joinpath(*parts)
