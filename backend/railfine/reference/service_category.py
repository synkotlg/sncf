"""Classification des itineraires commerciaux / circulations en categories de service.

Uniquement a partir de libelles explicites (reseau, exploitant, nom de marque,
type de service). Si rien n'est explicite, la categorie reste "AUTRE".
"""

from __future__ import annotations

import re

from .normalize import strip_accents

TER_BRANDS = (
    "ter", "fluo", "mobigo", "aleop", "breizhgo", "remi", "lio", "zou", "nomad", "trains regionaux",
    "sud provence", "auvergne rhone alpes", "hauts de france", "grand est", "occitanie", "nouvelle aquitaine",
    "normandie", "bretagne", "pays de la loire", "centre val de loire", "bourgogne franche comte", "leman express",
)


def _t(*parts) -> str:
    return " ".join(strip_accents(str(p)).lower() for p in parts if p)


def categorize(network=None, operator=None, name=None, ref=None, service=None, extra_text=None) -> str:
    text = _t(network, operator, name, ref, service, extra_text)
    words = set(re.findall(r"[a-z0-9]+", text))
    if re.search(r"\brer\b", text):
        return "RER"
    if "transilien" in text:
        return "TRANSILIEN"
    if any(w in words for w in ("tgv", "inoui", "ouigo", "lyria")) or "high_speed" in text or "grande vitesse" in text:
        return "TGV"
    if "eurostar" in words or "thalys" in words:
        return "EUROSTAR"
    if "intercites" in text or "intercite" in text:
        return "INTERCITES"
    if any(w in words for w in ("sncb", "nmbs")) or "belgian rail" in text:
        return "SNCB"
    if any(re.search(rf"\b{re.escape(b)}\b", text) for b in TER_BRANDS) or "regional" in words:
        return "TER"
    return "AUTRE"


# Categories de trains belges (route_short_name SNCB) : toutes rattachees a "SNCB".
SNCB_SHORT_NAMES = {"IC", "L", "P", "S", "ICE", "EXTRA", "EXT", "TRN", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S10", "S19", "S20", "S32", "S33", "S34", "S41", "S42", "S43", "S44", "S51", "S52", "S53", "S61", "S62", "S63", "S64", "S81"}
