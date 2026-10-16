"""Normalisation des noms de gares (FR/NL/DE) pour la recherche et l'appariement.

Deux formes sont produites :
- ``normalize_name`` : minuscules, sans accents ni ponctuation, abreviations developpees ;
- ``match_key``      : forme ``normalize_name`` debarrassee des mots vides
  ("gare", "de", "la"...), utilisee pour comparer des libelles heterogenes
  ("Gare de Lyon-Part-Dieu" ~ "LYON PART DIEU").
"""

from __future__ import annotations

import re
import unicodedata

_APOSTROPHES = re.compile(r"[’'`´‘]")
_SEPARATORS = re.compile(r"[\-‐-―_/.,;:()\[\]\"«»+*]")
_SPACES = re.compile(r"\s+")

ABBREVIATIONS = {
    "st": "saint",
    "ste": "sainte",
    "sts": "saints",
    "stes": "saintes",
    "gd": "grand",
    "gde": "grande",
    "pte": "porte",
    "bxl": "bruxelles",
    "brux": "bruxelles",
    "cdg": "charles de gaulle",
    "aerop": "aeroport",
    "aero": "aeroport",
    "chu": "chu",
    "ctre": "centre",
}

# Mots ignores pour la cle d'appariement. "ville", "centre", "nord"... sont
# conserves car ils distinguent des gares d'une meme commune.
STOPWORDS = {
    "gare", "gares", "station", "halte", "arret", "sncf", "sncb", "nmbs",
    "de", "du", "des", "la", "le", "les", "l", "d", "en", "sur", "sous",
    "et", "a", "au", "aux", "van", "het", "de", "der", "den", "te",
}

# Equivalences bilingues usuelles en Belgique (ajoutees comme alias de recherche).
BILINGUAL_HINTS = {
    "brussel": "bruxelles",
    "brussels": "bruxelles",
    "zuid": "midi",
    "noord": "nord",
    "centraal": "central",
    "centrale": "central",
    "luik": "liege",
    "bergen": "mons",
    "namen": "namur",
    "doornik": "tournai",
    "antwerpen": "anvers",
    "gent": "gand",
    "kortrijk": "courtrai",
    "leuven": "louvain",
    "mechelen": "malines",
    "brugge": "bruges",
    "aken": "aachen",
    "rijsel": "lille",
}


def strip_accents(text: str) -> str:
    text = text.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = strip_accents(str(name)).lower()
    s = _APOSTROPHES.sub(" ", s)
    s = _SEPARATORS.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [ABBREVIATIONS.get(t, t) for t in _SPACES.sub(" ", s).strip().split(" ") if t]
    return " ".join(tokens)


def match_key(name: str | None) -> str:
    norm = normalize_name(name)
    tokens = [t for t in norm.split(" ") if t and t not in STOPWORDS]
    return " ".join(tokens) if tokens else norm


def bilingual_variant(name: str | None) -> str | None:
    """Variante francisee d'un nom neerlandais (ou l'inverse) si des equivalences existent."""
    norm = normalize_name(name)
    tokens = norm.split(" ")
    changed = [BILINGUAL_HINTS.get(t, t) for t in tokens]
    if changed != tokens:
        return " ".join(changed)
    return None


def clean_display_name(name: str | None) -> str:
    """Nettoyage leger pour l'affichage (espaces, casse des libelles tout en majuscules)."""
    if not name:
        return ""
    s = _SPACES.sub(" ", str(name)).strip(" -:\t")
    if s.isupper() and len(s) > 3:
        s = " ".join(w.capitalize() if len(w) > 2 or i == 0 else w.lower() for i, w in enumerate(s.lower().split(" ")))
        s = re.sub(r"(?<=[\-'])([a-z])", lambda m: m.group(1).upper(), s)
    return s
