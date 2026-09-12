"""Source background images for each scene.

Providers:
  - pexels : download stock photos matching each scene query (free API key)
  - local  : pick images from assets/images/ in order
  - color  : generate a solid-color placeholder (no network, for testing)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import requests

from .config import Config

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"


def gather_images(queries: list[str], out_dir: Path, cfg: Config) -> list[Path]:
    provider = cfg.get("visuals", "provider", default="pexels")
    count = cfg.get("visuals", "images_per_video", default=6)
    # Ensure we have exactly `count` queries (pad by cycling).
    queries = (queries or ["nature"])[:count]
    while len(queries) < count:
        queries.append(queries[len(queries) % max(1, len(queries))])

    out_dir.mkdir(parents=True, exist_ok=True)

    if provider == "local":
        return _from_local(count, cfg)
    if provider == "color":
        return _solid_colors(count, out_dir)
    return _from_pexels(queries, out_dir, cfg)


def _from_pexels(queries: list[str], out_dir: Path, cfg: Config) -> list[Path]:
    if not cfg.pexels_api_key:
        print("  ! PEXELS_API_KEY not set — falling back to solid-color slides.")
        return _solid_colors(len(queries), out_dir)

    headers = {"Authorization": cfg.pexels_api_key}
    orientation = "portrait" if cfg.is_short else "landscape"
    paths: list[Path] = []
    for i, query in enumerate(queries):
        try:
            resp = requests.get(
                _PEXELS_SEARCH,
                headers=headers,
                params={"query": query, "per_page": 1, "orientation": orientation},
                timeout=30,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if not photos:
                paths.append(_solid_color(i, out_dir))
                continue
            src = photos[0]["src"]
            img_url = src.get("large2x") or src.get("large") or src["original"]
            img = requests.get(img_url, timeout=60)
            img.raise_for_status()
            dest = out_dir / f"scene_{i:02d}.jpg"
            dest.write_bytes(img.content)
            paths.append(dest)
        except Exception as exc:  # keep the pipeline moving on a single failure
            print(f"  ! Pexels fetch failed for '{query}': {exc}")
            paths.append(_solid_color(i, out_dir))
    return paths


def _from_local(count: int, cfg: Config) -> list[Path]:
    local_dir = cfg.path(cfg.get("visuals", "local_dir", default="assets/images"))
    imgs = sorted(
        p for p in local_dir.glob("*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not imgs:
        raise RuntimeError(f"No images found in {local_dir}")
    # Cycle through available images to fill `count` slots.
    return [imgs[i % len(imgs)] for i in range(count)]


def _solid_colors(count: int, out_dir: Path) -> list[Path]:
    return [_solid_color(i, out_dir) for i in range(count)]


def _solid_color(index: int, out_dir: Path) -> Path:
    """Write a 1-pixel-encodable PPM-free placeholder using ffmpeg-friendly PNG.

    We avoid extra deps by writing a tiny SVG the assembler can rasterize; but
    since ffmpeg can't read SVG without librsvg, we emit a colored PNG via a
    minimal raw approach only if Pillow is available. Otherwise we return a
    marker path and let the assembler generate the color with lavfi.
    """
    palette = ["1a2a3a", "3a2a1a", "2a3a1a", "3a1a2a", "1a3a3a", "3a3a1a"]
    color = palette[index % len(palette)]
    marker = out_dir / f"color_{index:02d}.{color}.txt"
    marker.write_text(color, encoding="utf-8")
    return marker


def is_color_marker(path: Path) -> str | None:
    """If `path` is a solid-color placeholder, return its hex color."""
    if path.suffix == ".txt" and path.stem.count(".") == 1:
        return path.stem.split(".")[-1]
    return None
