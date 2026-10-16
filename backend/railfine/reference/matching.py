"""Appariement de libelles de gares (issus d'OCR ou saisis) avec le referentiel.

- score de similarite sur la cle normalisee (``match_key``) et sur les alias ;
- detection des HOMONYMES : plusieurs gares eloignees avec un score equivalent ;
- desambiguisation prudente par le contexte (pays, autre gare du trajet) ;
- un appariement sous le seuil ou ambigu n'est jamais retenu automatiquement :
  il est renvoye comme "incertain" avec ses candidats pour validation manuelle.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from ..db import connect
from .normalize import match_key, normalize_name
from .store import ReferenceStore, haversine_km

HOMONYM_KM = 8.0  # deux candidats plus eloignes que cela sont des gares distinctes
AMBIGUITY_MARGIN = 4.0


@dataclass
class StationCandidate:
    id: str
    name: str
    score: float
    country: str | None
    lat: float
    lon: float
    uic: str | None
    importance: int
    matched_alias: str | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "score": round(self.score, 1), "country": self.country, "lat": self.lat,
                "lon": self.lon, "uic": self.uic, "importance": self.importance, "matched_alias": self.matched_alias}


@dataclass
class StationMatch:
    query: str
    station_id: str | None
    name: str | None
    confidence: float
    ambiguous: bool
    reason: str
    candidates: list[StationCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"query": self.query, "station_id": self.station_id, "name": self.name, "confidence": round(self.confidence, 2),
                "ambiguous": self.ambiguous, "reason": self.reason, "candidates": [c.to_dict() for c in self.candidates[:6]]}


class StationIndex:
    def __init__(self, store: ReferenceStore):
        self.version = store.version()
        self.path = str(store.path)
        self.stations: dict[str, dict] = {}
        self.keys: list[str] = []
        self.key_station: list[tuple[str, str]] = []  # (station_id, alias affiche)
        self.token_index: dict[str, set[str]] = {}
        if not store.exists():
            return
        conn = connect(store.path, readonly=True)
        try:
            for r in conn.execute("SELECT id, name, uic, country, lat, lon, importance, kind FROM stations"):
                self.stations[r["id"]] = dict(r)
            for r in conn.execute("SELECT station_id, name, key FROM station_names"):
                st = self.stations.get(r["station_id"])
                if st is None:
                    continue
                self.keys.append(r["key"])
                self.key_station.append((r["station_id"], r["name"]))
                if st["kind"] == "station":
                    for tok in r["key"].split(" "):
                        self.token_index.setdefault(tok, set()).add(r["station_id"])
        finally:
            conn.close()

    def _candidates(self, query: str, limit: int, scorer, kinds=("station",)) -> list[StationCandidate]:
        key = match_key(query)
        if not key or not self.keys:
            return []
        hits = process.extract(key, self.keys, scorer=scorer, limit=limit * 4, score_cutoff=50)
        best: dict[str, StationCandidate] = {}
        for _, score, idx in hits:
            sid, alias = self.key_station[idx]
            st = self.stations[sid]
            if st["kind"] not in kinds:
                continue
            k = self.keys[idx]
            if k == key:
                score = 100.0
            if sid not in best or score > best[sid].score:
                best[sid] = StationCandidate(sid, st["name"], float(score), st["country"], st["lat"], st["lon"], st["uic"],
                                             st["importance"], alias if alias != st["name"] else None)
        return sorted(best.values(), key=lambda c: (-c.score, c.importance, c.name))[:limit]

    def find_mentions(self, text: str, max_tokens: int = 5) -> list[tuple[str, int]]:
        """Gares citées telles quelles dans un texte (clé normalisée exacte), avec leur position.

        Les noms d'un seul mot de moins de 5 lettres sont ignorés (trop de faux positifs).
        """
        if not self.keys:
            return []
        if not hasattr(self, "_exact"):
            exact: dict[str, str] = {}
            for k, (sid, _alias) in zip(self.keys, self.key_station):
                if self.stations[sid]["kind"] == "station":
                    exact.setdefault(k, self.stations[sid]["name"])
            self._exact = exact
        found: list[tuple[str, int]] = []
        offset = 0
        for line in text.split("\n"):
            tokens = [(m.group(0), m.start()) for m in re.finditer(r"[^\s,;:()]+", line)]
            i = 0
            while i < len(tokens):
                hit = None
                for n in range(min(max_tokens, len(tokens) - i), 0, -1):
                    chunk = " ".join(t for t, _ in tokens[i : i + n])
                    k = match_key(chunk)
                    if k in self._exact and (" " in k or len(k) >= 5):
                        hit = (self._exact[k], offset + tokens[i][1], n)
                        break
                if hit:
                    found.append((hit[0], hit[1]))
                    i += hit[2]
                else:
                    i += 1
            offset += len(line) + 1
        return found

    def search(self, query: str, limit: int = 10, include_points: bool = False) -> list[dict]:
        """Recherche tolerante pour l'autocompletion (prefixes, mots partiels)."""
        kinds = ("station", "operational_point") if include_points else ("station",)
        by_id = {c.id: c for c in self._candidates(query, limit * 2, fuzz.WRatio, kinds)}
        qk = match_key(query)
        if qk:
            # priorite aux noms (ou alias FR/NL) dont un mot commence par la saisie
            for i, k in enumerate(self.keys):
                if k.startswith(qk) or (" " + qk) in (" " + k):
                    sid, alias = self.key_station[i]
                    st = self.stations[sid]
                    if st["kind"] not in kinds:
                        continue
                    score = 100.0 - min(8.0, (len(k) - len(qk)) / 4) - (0 if k.startswith(qk) else 1)
                    if sid not in by_id or by_id[sid].score < score:
                        by_id[sid] = StationCandidate(sid, st["name"], score, st["country"], st["lat"], st["lon"], st["uic"],
                                                      st["importance"], alias if alias != st["name"] else None)
        cands = sorted(by_id.values(), key=lambda c: (-round(c.score), c.importance, c.name))
        return [c.to_dict() for c in cands[:limit]]

    def match(self, query: str | None, threshold: float = 82.0, country_hint: str | None = None,
              near: tuple[float, float] | None = None) -> StationMatch:
        if not query or not query.strip():
            return StationMatch(query or "", None, None, 0.0, False, "libellé vide")

        def scorer(a, b, **kw):
            return max(fuzz.ratio(a, b, **kw), fuzz.token_sort_ratio(a, b, **kw))

        cands = self._candidates(query, 8, scorer)
        key = match_key(query)
        # les libelles courts tolerent moins d'ecart ("Lille" ne doit pas devenir "Laille")
        threshold = threshold + max(0, 10 - len(key)) * 2.5
        has_exact = bool(cands) and cands[0].score >= 100
        if not has_exact:
            tokens = key.split(" ")
            ids = set.intersection(*(self.token_index.get(t, set()) for t in tokens)) if tokens and tokens[0] else set()
            if ids:
                subset = sorted((self.stations[i] for i in ids), key=lambda s: (s["importance"], s["name"]))[:8]
                sc = [StationCandidate(s["id"], s["name"], 90.0, s["country"], s["lat"], s["lon"], s["uic"], s["importance"])
                      for s in subset]
                if len(ids) == 1:
                    c = sc[0]
                    return StationMatch(query, c.id, c.name, 0.75, False, "libellé partiel : une seule gare correspondante (à vérifier)", sc)
                return StationMatch(query, None, None, 0.4, True,
                                    f"libellé partiel commun à {len(ids)} gares : choix manuel requis", sc)
        if not cands or cands[0].score < threshold:
            return StationMatch(query, None, None, (cands[0].score / 100 * 0.5) if cands else 0.0, False,
                                "aucune gare suffisamment proche", cands)
        top = cands[0].score
        exact = [c for c in cands if c.score >= 100]
        close = exact if exact else [c for c in cands if top - c.score <= AMBIGUITY_MARGIN]
        if len(close) > 1 and not exact:
            # plusieurs gares differentes aussi plausibles (ex. "Paris" -> Paris Nord / Paris Est) : pas de choix automatique
            names = {match_key(c.name) for c in close}
            if len(names) > 1:
                return StationMatch(query, None, None, top / 100 * 0.5, True,
                                    f"{len(close)} gares aussi plausibles : choix manuel requis", cands)
        distinct = [close[0]]
        for c in close[1:]:
            if all(haversine_km(c.lon, c.lat, d.lon, d.lat) > HOMONYM_KM for d in distinct):
                distinct.append(c)
        if len(distinct) == 1:
            c = distinct[0]
            return StationMatch(query, c.id, c.name, c.score / 100, False, "correspondance unique", cands)
        # homonymes : contexte du pays puis proximite de l'autre gare du trajet
        pool = distinct
        if country_hint:
            same = [c for c in pool if c.country == country_hint]
            if len(same) == 1:
                c = same[0]
                return StationMatch(query, c.id, c.name, c.score / 100 * 0.8, True, f"homonymes départagés par le pays ({country_hint})", cands)
            pool = same or pool
        if near is not None:
            ranked = sorted(pool, key=lambda c: haversine_km(c.lon, c.lat, near[1], near[0]))
            d0 = haversine_km(ranked[0].lon, ranked[0].lat, near[1], near[0])
            d1 = haversine_km(ranked[1].lon, ranked[1].lat, near[1], near[0])
            if d0 < 250 and d1 > 2.5 * d0:
                c = ranked[0]
                return StationMatch(query, c.id, c.name, c.score / 100 * 0.7, True,
                                    "homonymes départagés par la proximité de l'autre gare (à vérifier)", cands)
        return StationMatch(query, None, None, top / 100 * 0.5, True, f"{len(distinct)} gares homonymes : choix manuel requis", cands)


_lock = threading.Lock()
_index: StationIndex | None = None


def get_index(store: ReferenceStore) -> StationIndex:
    global _index
    version = store.version()
    with _lock:
        if _index is None or _index.version != version or _index.path != str(store.path):
            _index = StationIndex(store)
        return _index


def reset_index() -> None:
    global _index
    with _lock:
        _index = None
