"""Generate a Gujarati narration script + YouTube metadata using Claude.

Returns a structured dict so downstream stages (voice, visuals, upload) can
consume the same object.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

from .config import Config


@dataclass
class VideoScript:
    topic: str
    title: str          # Gujarati YouTube title
    narration: str      # the full Gujarati voiceover text
    description: str    # YouTube description (Gujarati + a little English)
    tags: list[str]
    scenes: list[str]   # English image-search queries, one per visual beat
    moral: str          # the takeaway (also spoken at the end of narration)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


_PROMPT = """\
તમારે નીચેના વિષય પર એક ટૂંકી ગુજરાતી પ્રેરક/બોધક વાર્તા YouTube વિડિયો માટે \
બનાવવાની છે.

વિષય: {topic}

નિયમો:
- narration આશરે {max_words} શબ્દોમાં હોય (વિડિયો ~{duration} સેકન્ડ ચાલે).
- narration એ ફક્ત બોલવાનો ટેક્સ્ટ હોય — કોઈ stage directions, કૌંસ કે \
"scene 1" જેવા લેબલ નહીં.
- અંતે એક સ્પષ્ટ moral વાક્ય narration માં જ આવવું જોઈએ.
- બરાબર {scene_count} scenes આપો; દરેક scene એ ANGREJI (English) માં એક \
stock-image/video search query હોય જે વાર્તાના એ ભાગને દ્રશ્ય રૂપે બતાવે.
- દરેક query એકબીજાથી અલગ (DISTINCT) અને ચોક્કસ (specific) હોય — કોઈ બે \
scene એકસરખા ન હોય, જેથી વિડિયોમાં એક પણ દ્રશ્ય પુનરાવર્તિત ન થાય. \
Visual theme: {visual_theme}
- title: {title_style}

ફક્ત નીચેના JSON format માં જ જવાબ આપો, બીજું કંઈ નહીં:
{{
  "title": "...",
  "narration": "...",
  "description": "...",
  "tags": ["...", "..."],
  "scenes": ["english query 1", "english query 2"],
  "moral": "..."
}}
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of the model response, tolerating fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if not brace:
            raise ValueError(f"No JSON object found in model response:\n{text[:500]}")
        raw = brace.group(0)
    return json.loads(raw)


def _scene_queries_from_theme(cfg: Config, count: int) -> list[str]:
    """Build English image-search queries WITHOUT an LLM, from the niche's
    visual theme. Used by manual-script mode."""
    theme = cfg.get("niche", "visual_theme", default="cinematic nature")
    base = [t.strip() for t in theme.replace(";", ",").split(",") if t.strip()]
    if not base:
        base = ["cinematic indian village", "temple", "nature", "elderly wisdom"]
    modifiers = ["", "close up", "wide shot", "golden hour", "cinematic",
                 "morning light", "dramatic", "aerial view", "detail"]
    queries: list[str] = []
    i = 0
    while len(queries) < count:
        b = base[i % len(base)]
        m = modifiers[(i // len(base)) % len(modifiers)]
        queries.append(f"{b} {m}".strip())
        i += 1
    return queries


def manual_script(narration: str, cfg: Config, title: str | None = None) -> VideoScript:
    """Build a VideoScript from narration text the user wrote — no LLM/API call.

    Title/tags/scene-queries are derived locally so the rest of the pipeline
    (voice, visuals, assembly, upload) runs exactly the same."""
    raw = narration.strip()
    if not raw:
        raise ValueError("Manual script is empty.")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # Line 1 is the TITLE (metadata only). The narration starts at line 2 so the
    # first SPOKEN words are the hook — critical for Shorts/Reels retention.
    if not title:
        title = (lines[0][:70] or "ગુજરાતી વાર્તા")
    narration = "\n".join(lines[1:]).strip() if len(lines) > 1 else raw
    footer = cfg.get("upload", "description_footer", default="")
    description = (title + ("\n" + footer if footer else "")).strip()
    from_dur = cfg.get("channel", "target_duration_sec", default=90)
    scenes = _scene_queries_from_theme(cfg, _target_scene_count(cfg))
    return VideoScript(
        topic=title,
        title=title,
        narration=narration,
        description=description,
        tags=_dedupe(list(cfg.get("upload", "default_tags", default=[]))),
        scenes=scenes,
        moral="",
    )


def _target_scene_count(cfg: Config) -> int:
    """How many distinct visual beats to ask for, from the target duration
    and the desired pace (scene every ~seconds_per_scene)."""
    duration = cfg.get("channel", "target_duration_sec", default=90)
    sps = float(cfg.get("visuals", "seconds_per_scene", default=3.5))
    lo = int(cfg.get("visuals", "min_scenes", default=6))
    hi = int(cfg.get("visuals", "max_scenes", default=45))
    return max(lo, min(hi, round(duration / max(1.5, sps))))


def scene_count_for_duration(duration_sec: float, cfg: Config) -> int:
    """Actual number of scenes for the real narration duration."""
    sps = float(cfg.get("visuals", "seconds_per_scene", default=3.5))
    lo = int(cfg.get("visuals", "min_scenes", default=6))
    hi = int(cfg.get("visuals", "max_scenes", default=45))
    return max(lo, min(hi, round(max(3.0, duration_sec) / max(1.5, sps))))


def generate_script(topic: str, cfg: Config) -> VideoScript:
    if not cfg.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")

    from anthropic import Anthropic

    client = Anthropic(api_key=cfg.anthropic_api_key)

    prompt = _PROMPT.format(
        topic=topic,
        max_words=cfg.get("script", "max_words", default=210),
        duration=cfg.get("channel", "target_duration_sec", default=90),
        scene_count=_target_scene_count(cfg),
        visual_theme=cfg.get("niche", "visual_theme", default=""),
        title_style=cfg.get("niche", "title_style", default="short Gujarati title"),
    )

    resp = client.messages.create(
        model=cfg.get("script", "model", default="claude-sonnet-5"),
        max_tokens=2000,
        system=cfg.get("niche", "system_prompt", default=""),
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    payload = _extract_json(text)

    tags = list(payload.get("tags", [])) + list(
        cfg.get("upload", "default_tags", default=[])
    )
    footer = cfg.get("upload", "description_footer", default="")
    description = payload.get("description", "").strip() + ("\n" + footer if footer else "")

    return VideoScript(
        topic=topic,
        title=payload["title"].strip(),
        narration=payload["narration"].strip(),
        description=description.strip(),
        tags=_dedupe(tags),
        scenes=payload.get("scenes", []),
        moral=payload.get("moral", "").strip(),
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
