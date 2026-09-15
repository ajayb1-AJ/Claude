"""Map a Gujarati beat of narration to an English stock-image query.

No LLM/API needed: a small dictionary of common story nouns/themes turns each
spoken beat into a relevant visual search, so the picture matches the words.
Falls back to the niche's visual theme when nothing specific is found.
"""
from __future__ import annotations

import re

# Gujarati keyword -> English image query fragment. Order roughly by specificity.
_MAP: dict[str, str] = {
    "ખેડૂત": "indian farmer field",
    # Values are CINEMATIC SCENE descriptions (no "India/Indian/flag" — those
    # trigger flags & touristy portraits). Favor atmospheric footage over
    # posed people so the video feels real, not like random stock selfies.
    "ખેતર": "green farm field crops cinematic",
    "માતા": "silhouette mother and child sunset warm",
    "મા ": "silhouette mother and child sunset warm",
    "બાળક": "child playing countryside slow motion",
    "છોકરો": "young boy walking rural path back view",
    "છોકરી": "young girl walking countryside back view",
    "રાજા": "ancient palace throne room cinematic",
    "શેઠ": "old marketplace lantern evening",
    "નોકર": "hands working hard labor close up",
    "વૃક્ષ": "large old tree golden hour",
    "ઝાડ": "tree silhouette sunset",
    "વાંસ": "bamboo forest wind",
    "ઘાસ": "grass field swaying wind",
    "નદી": "calm river flowing nature",
    "પાણી": "water pouring slow motion",
    "વરસાદ": "rain drops window cinematic",
    "વાવાઝોડું": "dramatic storm dark clouds",
    "પવન": "wind blowing trees field",
    "કૂતરો": "street dog resting village",
    "ગામ": "rural village huts morning mist",
    "મંદિર": "ancient temple architecture",
    "દુકાન": "small old shop lantern evening",
    "ફળ": "fresh fruit basket rustic",
    "ભોજન": "simple home cooked meal rustic",
    "પૈસા": "old coins on table close up",
    "ધન": "gold coins treasure close up",
    "રસ્તો": "empty village road misty morning",
    "આકાશ": "dramatic sky moving clouds timelapse",
    "સૂરજ": "golden sunrise over fields",
    "કુંભાર": "potter hands shaping clay close up",
    "વાસણ": "clay pots handmade rustic",
    "મહેનત": "hands working hard sweat close up",
    "ગરીબ": "humble mud house countryside",
    "આંસુ": "single tear drop macro slow motion",
    "હિંમત": "person standing on mountain top sunrise",
    "સફળ": "sunrise mountain summit victory",
    "ઝઘડો": "storm clouds tension dramatic",
    "માફી": "two hands reaching together warm",
    "સમય": "old clock ticking close up",
    "એકતા": "bundle of sticks rope together",
    "લાલચ": "gold coins greed dark moody",
    "જ્ઞાન": "old books candle light wisdom",
    "સંતોષ": "peaceful calm nature lake sunrise",
}


def beat_to_query(text: str, theme: str, index: int = 0) -> str:
    """Return an English image query relevant to this Gujarati beat."""
    hits: list[str] = []
    for guj, eng in _MAP.items():
        if guj.strip() in text:
            hits.append(eng)
        if len(hits) >= 2:
            break
    if hits:
        return hits[0]  # one specific scene reads cleaner than two mashed together
    # Fallback: cycle through varied cinematic scenery (no people, no flags).
    base = [t.strip() for t in theme.replace(";", ",").split(",") if t.strip()]
    scenery = ["misty green fields sunrise", "calm river nature", "ancient temple",
               "dramatic sky clouds timelapse", "golden wheat field wind",
               "old tree silhouette sunset", "mountain valley cinematic",
               "rain on leaves close up"]
    pool = base + scenery
    return pool[index % len(pool)]


def beats_to_queries(beats: list[dict], theme: str) -> list[str]:
    return [beat_to_query(b.get("text", ""), theme, i) for i, b in enumerate(beats)]
