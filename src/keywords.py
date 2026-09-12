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
    "ખેતર": "farm field crops",
    "માતા": "indian mother love",
    "મા ": "indian mother child",
    "બાળક": "indian child",
    "છોકરો": "indian boy village",
    "છોકરી": "indian girl village",
    "રાજા": "king palace throne",
    "શેઠ": "indian merchant shopkeeper",
    "નોકર": "servant worker humble",
    "વૃક્ષ": "large tree nature",
    "ઝાડ": "tree nature",
    "વાંસ": "bamboo forest",
    "ઘાસ": "grass field wind",
    "નદી": "river flowing water",
    "પાણી": "water pouring",
    "વરસાદ": "heavy rain",
    "વાવાઝોડું": "storm wind dramatic",
    "પવન": "wind blowing trees",
    "કૂતરો": "loyal dog street",
    "ગામ": "indian village",
    "મંદિર": "hindu temple",
    "દુકાન": "small shop market india",
    "ફળ": "fresh fruit basket",
    "ભોજન": "indian food meal",
    "પૈસા": "coins money rupees",
    "ધન": "gold coins wealth",
    "રસ્તો": "village road path",
    "આકાશ": "sky clouds",
    "સૂરજ": "sunrise golden",
    "કુંભાર": "potter clay pottery",
    "વાસણ": "clay pot pottery",
    "મહેનત": "hard work labour",
    "ગરીબ": "poor humble india",
    "આંસુ": "tears emotional face",
    "હિંમત": "courage determination",
    "સફળ": "success achievement",
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
        return " ".join(hits[:2])
    # Fallback: cycle through the niche visual theme fragments.
    base = [t.strip() for t in theme.replace(";", ",").split(",") if t.strip()]
    if not base:
        base = ["cinematic indian village", "nature", "temple"]
    return base[index % len(base)]


def beats_to_queries(beats: list[dict], theme: str) -> list[str]:
    return [beat_to_query(b.get("text", ""), theme, i) for i, b in enumerate(beats)]
