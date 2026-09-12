"""Source per-scene visual assets: photos AND short video clips.

Only genuinely free / licensed sources are used, so the channel stays safe
from copyright claims:
  - Pexels  (photos + videos)   -- free, CC0-style
  - Pixabay (photos + videos)   -- free, CC0-style
  - local   -- your own images (assets/images) and clips (assets/clips),
               e.g. AI-generated video you created

Each scene becomes a SceneAsset (image or video). The assembler turns images
into Ken-Burns motion clips and trims videos to the scene duration.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Config

_PEXELS_PHOTO = "https://api.pexels.com/v1/search"
_PEXELS_VIDEO = "https://api.pexels.com/videos/search"
_PIXABAY_PHOTO = "https://pixabay.com/api/"
_PIXABAY_VIDEO = "https://pixabay.com/api/videos/"

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
_VID_EXT = {".mp4", ".mov", ".webm", ".mkv"}


@dataclass
class SceneAsset:
    path: Path
    kind: str  # "image" | "video"


def gather_scene_assets(
    queries: list[str], out_dir: Path, cfg: Config, count: int | None = None
) -> list[SceneAsset]:
    provider = cfg.get("visuals", "provider", default="pexels")
    if count is None:
        count = int(cfg.get("visuals", "max_scenes", default=12))
    queries = queries or ["cinematic nature"]
    out_dir.mkdir(parents=True, exist_ok=True)

    if provider == "local":
        return _from_local(count, cfg)
    if provider == "color":
        return [SceneAsset(_solid_color(i, out_dir), "image") for i in range(count)]

    if not cfg.pexels_api_key and not cfg.pixabay_api_key:
        print("  ! No PEXELS_API_KEY / PIXABAY_API_KEY — using solid-color slides.")
        return [SceneAsset(_solid_color(i, out_dir), "image") for i in range(count)]

    video_ratio = float(cfg.get("visuals", "video_ratio", default=0.5))
    orientation = "portrait" if cfg.is_short else "landscape"
    photo_sources = [_pexels_photos, _pixabay_photos]
    video_sources = [_pexels_videos, _pixabay_videos]
    if provider == "pixabay":
        photo_sources.reverse()
        video_sources.reverse()

    # Cache candidate URL lists per (query, kind) and track what we've used so
    # no two scenes reuse the same clip/photo — even when a query repeats.
    cache: dict[tuple[str, str], list[str]] = {}
    used: set[str] = set()

    def candidates(query: str, kind: str) -> list[str]:
        key = (query, kind)
        if key not in cache:
            urls: list[str] = []
            sources = video_sources if kind == "video" else photo_sources
            for src in sources:
                try:
                    urls += src(query, orientation, cfg)
                except Exception as exc:
                    print(f"  ! {src.__name__} error for '{query}': {exc}")
            # de-dupe preserving order
            seen: set[str] = set()
            cache[key] = [u for u in urls if not (u in seen or seen.add(u))]
        return cache[key]

    assets: list[SceneAsset] = []
    for i in range(count):
        query = queries[i % len(queries)]
        # Alternate video/photo scenes by the configured ratio.
        want_video = video_ratio > 0 and (i % max(1, round(1 / video_ratio))) == 0
        kinds = ["video", "image"] if want_video else ["image", "video"]

        asset = None
        for kind in kinds:
            url = _pick_unused(candidates(query, kind), used)
            # If this query is exhausted, try any other query's pool for variety.
            if not url:
                for alt in queries:
                    url = _pick_unused(candidates(alt, kind), used)
                    if url:
                        break
            if not url:
                continue
            saved = _download(url, out_dir, i, kind)
            if saved:
                used.add(url)
                asset = SceneAsset(saved, kind)
                break
        if asset is None:
            asset = SceneAsset(_solid_color(i, out_dir), "image")
        assets.append(asset)
    return assets


def _pick_unused(urls: list[str], used: set[str]) -> str | None:
    for u in urls:
        if u not in used:
            return u
    return None


def _download(url: str, out_dir: Path, i: int, kind: str) -> Path | None:
    ext = "mp4" if kind == "video" else "jpg"
    dest = out_dir / f"scene_{i:02d}.{ext}"
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest
    except Exception as exc:
        print(f"  ! download failed ({kind}): {exc}")
        return None


# --- candidate lists (return MANY urls so scenes stay distinct) ------------
def _pexels_photos(query: str, orientation: str, cfg: Config) -> list[str]:
    if not cfg.pexels_api_key:
        return []
    r = requests.get(
        _PEXELS_PHOTO,
        headers={"Authorization": cfg.pexels_api_key},
        params={"query": query, "per_page": 15, "orientation": orientation},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for p in r.json().get("photos", []):
        src = p.get("src", {})
        u = src.get("large2x") or src.get("large") or src.get("original")
        if u:
            out.append(u)
    return out


def _pixabay_photos(query: str, orientation: str, cfg: Config) -> list[str]:
    if not cfg.pixabay_api_key:
        return []
    r = requests.get(
        _PIXABAY_PHOTO,
        params={
            "key": cfg.pixabay_api_key, "q": query, "image_type": "photo",
            "orientation": "vertical" if orientation == "portrait" else "horizontal",
            "safesearch": "true", "per_page": 20,
        },
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        u = h.get("largeImageURL") or h.get("webformatURL")
        if u:
            out.append(u)
    return out


def _pexels_videos(query: str, orientation: str, cfg: Config) -> list[str]:
    if not cfg.pexels_api_key:
        return []
    r = requests.get(
        _PEXELS_VIDEO,
        headers={"Authorization": cfg.pexels_api_key},
        params={"query": query, "per_page": 10, "orientation": orientation},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for v in r.json().get("videos", []):
        files = sorted(v.get("video_files", []), key=lambda f: (f.get("width") or 0))
        best = None
        for f in files:
            if (f.get("width") or 0) <= 1920 and f.get("link"):
                best = f["link"]
        best = best or (files[-1]["link"] if files else None)
        if best:
            out.append(best)
    return out


def _pixabay_videos(query: str, orientation: str, cfg: Config) -> list[str]:
    if not cfg.pixabay_api_key:
        return []
    r = requests.get(
        _PIXABAY_VIDEO,
        params={"key": cfg.pixabay_api_key, "q": query, "per_page": 10, "safesearch": "true"},
        timeout=30,
    )
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        v = h.get("videos", {})
        for size in ("large", "medium", "small"):
            if v.get(size, {}).get("url"):
                out.append(v[size]["url"])
                break
    return out


# --- local + fallback ------------------------------------------------------
def _from_local(count: int, cfg: Config) -> list[SceneAsset]:
    img_dir = cfg.path(cfg.get("visuals", "local_dir", default="assets/images"))
    clip_dir = cfg.path(cfg.get("visuals", "clips_dir", default="assets/clips"))
    imgs = sorted(p for p in _iter(img_dir) if p.suffix.lower() in _IMG_EXT)
    clips = sorted(p for p in _iter(clip_dir) if p.suffix.lower() in _VID_EXT)
    pool = [SceneAsset(p, "video") for p in clips] + [SceneAsset(p, "image") for p in imgs]
    if not pool:
        raise RuntimeError(f"No local media in {img_dir} or {clip_dir}")
    return [pool[i % len(pool)] for i in range(count)]


def _iter(path: Path):
    return list(path.iterdir()) if path.exists() else []


def _pad(queries: list[str], count: int) -> list[str]:
    queries = queries[:count]
    while len(queries) < count:
        queries.append(queries[len(queries) % max(1, len(queries))])
    return queries


def _solid_color(index: int, out_dir: Path) -> Path:
    palette = ["1a2a3a", "3a2a1a", "2a3a1a", "3a1a2a", "1a3a3a", "3a3a1a"]
    color = palette[index % len(palette)]
    marker = out_dir / f"color_{index:02d}.{color}.txt"
    marker.write_text(color, encoding="utf-8")
    return marker


def is_color_marker(path: Path) -> str | None:
    if path.suffix == ".txt" and path.stem.count(".") == 1:
        return path.stem.split(".")[-1]
    return None
