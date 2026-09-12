"""Source background images for each scene.

Providers (config `visuals.provider`):
  - pexels : stock photos from Pexels, with automatic Pixabay fallback
  - pixabay: stock photos from Pixabay only
  - local  : pick images from assets/images/ in order
  - color  : generate a solid-color placeholder (no network, for testing)

For "pexels", each scene is tried on Pexels first; if it has no match (or no
key), the same query is tried on Pixabay; only then does it fall back to a
solid-color slide. Provide PEXELS_API_KEY and/or PIXABAY_API_KEY in .env.
"""
from __future__ import annotations

from pathlib import Path

import requests

from .config import Config

_PEXELS_SEARCH = "https://api.pexels.com/v1/search"
_PIXABAY_SEARCH = "https://pixabay.com/api/"


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

    # Build the fetch order. "pixabay" -> Pixabay first; otherwise Pexels first,
    # then Pixabay. Whichever keys exist are used; the rest are skipped.
    if provider == "pixabay":
        sources = [_fetch_pixabay, _fetch_pexels]
    else:
        sources = [_fetch_pexels, _fetch_pixabay]

    if not cfg.pexels_api_key and not cfg.pixabay_api_key:
        print("  ! No PEXELS_API_KEY or PIXABAY_API_KEY set — using solid-color slides.")
        return _solid_colors(count, out_dir)

    orientation = "portrait" if cfg.is_short else "landscape"
    paths: list[Path] = []
    for i, query in enumerate(queries):
        dest = out_dir / f"scene_{i:02d}.jpg"
        img_url = None
        for source in sources:
            try:
                img_url = source(query, orientation, cfg)
            except Exception as exc:
                print(f"  ! {source.__name__} error for '{query}': {exc}")
                img_url = None
            if img_url:
                break
        if not img_url:
            paths.append(_solid_color(i, out_dir))
            continue
        try:
            img = requests.get(img_url, timeout=60)
            img.raise_for_status()
            dest.write_bytes(img.content)
            paths.append(dest)
        except Exception as exc:
            print(f"  ! image download failed for '{query}': {exc}")
            paths.append(_solid_color(i, out_dir))
    return paths


def _fetch_pexels(query: str, orientation: str, cfg: Config) -> str | None:
    """Return a photo URL from Pexels, or None if no key/no match."""
    if not cfg.pexels_api_key:
        return None
    resp = requests.get(
        _PEXELS_SEARCH,
        headers={"Authorization": cfg.pexels_api_key},
        params={"query": query, "per_page": 1, "orientation": orientation},
        timeout=30,
    )
    resp.raise_for_status()
    photos = resp.json().get("photos", [])
    if not photos:
        return None
    src = photos[0]["src"]
    return src.get("large2x") or src.get("large") or src["original"]


def _fetch_pixabay(query: str, orientation: str, cfg: Config) -> str | None:
    """Return a photo URL from Pixabay, or None if no key/no match."""
    if not cfg.pixabay_api_key:
        return None
    resp = requests.get(
        _PIXABAY_SEARCH,
        params={
            "key": cfg.pixabay_api_key,
            "q": query,
            "image_type": "photo",
            "orientation": "vertical" if orientation == "portrait" else "horizontal",
            "safesearch": "true",
            "per_page": 3,
        },
        timeout=30,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    if not hits:
        return None
    hit = hits[0]
    return hit.get("largeImageURL") or hit.get("webformatURL")


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
