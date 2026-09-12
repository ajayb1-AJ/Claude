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


def gather_scene_assets(queries: list[str], out_dir: Path, cfg: Config) -> list[SceneAsset]:
    provider = cfg.get("visuals", "provider", default="pexels")
    count = cfg.get("visuals", "images_per_video", default=8)
    queries = _pad(queries or ["nature"], count)
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
    # Photo source order (fallback across providers).
    photo_sources = [_pexels_photo, _pixabay_photo]
    video_sources = [_pexels_video, _pixabay_video]
    if provider == "pixabay":
        photo_sources.reverse()
        video_sources.reverse()

    assets: list[SceneAsset] = []
    for i, query in enumerate(queries):
        want_video = (i % max(1, round(1 / video_ratio))) == 0 if video_ratio > 0 else False
        asset = None
        if want_video:
            asset = _try_fetch(video_sources, query, orientation, out_dir, i, "video", cfg)
        if asset is None:
            asset = _try_fetch(photo_sources, query, orientation, out_dir, i, "image", cfg)
        if asset is None:
            asset = SceneAsset(_solid_color(i, out_dir), "image")
        assets.append(asset)
    return assets


def _try_fetch(sources, query, orientation, out_dir, i, kind, cfg) -> SceneAsset | None:
    ext = "mp4" if kind == "video" else "jpg"
    dest = out_dir / f"scene_{i:02d}.{ext}"
    for source in sources:
        try:
            url = source(query, orientation, cfg)
        except Exception as exc:
            print(f"  ! {source.__name__} error for '{query}': {exc}")
            url = None
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return SceneAsset(dest, kind)
        except Exception as exc:
            print(f"  ! download failed ({source.__name__}, '{query}'): {exc}")
    return None


# --- photo sources ---------------------------------------------------------
def _pexels_photo(query: str, orientation: str, cfg: Config) -> str | None:
    if not cfg.pexels_api_key:
        return None
    r = requests.get(
        _PEXELS_PHOTO,
        headers={"Authorization": cfg.pexels_api_key},
        params={"query": query, "per_page": 1, "orientation": orientation},
        timeout=30,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        return None
    src = photos[0]["src"]
    return src.get("large2x") or src.get("large") or src["original"]


def _pixabay_photo(query: str, orientation: str, cfg: Config) -> str | None:
    if not cfg.pixabay_api_key:
        return None
    r = requests.get(
        _PIXABAY_PHOTO,
        params={
            "key": cfg.pixabay_api_key, "q": query, "image_type": "photo",
            "orientation": "vertical" if orientation == "portrait" else "horizontal",
            "safesearch": "true", "per_page": 3,
        },
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    return hits[0].get("largeImageURL") or hits[0].get("webformatURL")


# --- video sources ---------------------------------------------------------
def _pexels_video(query: str, orientation: str, cfg: Config) -> str | None:
    if not cfg.pexels_api_key:
        return None
    r = requests.get(
        _PEXELS_VIDEO,
        headers={"Authorization": cfg.pexels_api_key},
        params={"query": query, "per_page": 3, "orientation": orientation},
        timeout=30,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None
    # Choose an HD file no wider than 1920 (keeps download/encode reasonable).
    files = sorted(
        videos[0].get("video_files", []),
        key=lambda f: (f.get("width") or 0),
    )
    best = None
    for f in files:
        if (f.get("width") or 0) <= 1920 and f.get("link"):
            best = f["link"]
    return best or (files[-1]["link"] if files else None)


def _pixabay_video(query: str, orientation: str, cfg: Config) -> str | None:
    if not cfg.pixabay_api_key:
        return None
    r = requests.get(
        _PIXABAY_VIDEO,
        params={"key": cfg.pixabay_api_key, "q": query, "per_page": 3, "safesearch": "true"},
        timeout=30,
    )
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        return None
    v = hits[0].get("videos", {})
    for size in ("large", "medium", "small"):
        if v.get(size, {}).get("url"):
            return v[size]["url"]
    return None


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
