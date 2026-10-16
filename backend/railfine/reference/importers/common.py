"""Outils communs : telechargement prudent, API Opendatasoft, lecture tolerante des attributs."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import httpx

log = logging.getLogger("railfine.import")

USER_AGENT = "RailFineAnalytics/0.1 (application locale personnelle; +https://github.com/)"
MAX_DOWNLOAD_BYTES = 1_500_000_000


class SourceUnavailable(RuntimeError):
    """La source n'a pas pu etre telechargee (reseau, URL obsolete, quota...)."""


def http_client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=20.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        trust_env=True,
    )


def download(url: str, dest: Path, timeout: float = 300.0, retries: int = 2, data: dict | None = None) -> Path:
    """Telecharge ``url`` vers ``dest`` (ecriture atomique). Leve SourceUnavailable en cas d'echec."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with http_client(timeout) as client:
                method = "POST" if data is not None else "GET"
                with client.stream(method, url, data=data) as resp:
                    if resp.status_code == 429:
                        raise SourceUnavailable(f"{url} : quota depasse (HTTP 429), reessayer plus tard")
                    if resp.status_code >= 400:
                        raise SourceUnavailable(f"{url} : HTTP {resp.status_code}")
                    size = 0
                    with tmp.open("wb") as fh:
                        for chunk in resp.iter_bytes(1 << 16):
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise SourceUnavailable(f"{url} : fichier trop volumineux")
                            fh.write(chunk)
            tmp.replace(dest)
            log.info("telecharge %s -> %s (%d octets)", url, dest, dest.stat().st_size)
            return dest
        except SourceUnavailable as exc:
            last_error = exc
            if "HTTP 4" in str(exc) and "429" not in str(exc):
                break
        except httpx.ProxyError as exc:  # refus du proxy / politique reseau : inutile d'insister
            last_error = exc
            break
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    if tmp.exists():
        tmp.unlink(missing_ok=True)
    raise SourceUnavailable(f"Echec du telechargement de {url} : {last_error}")


def first_available(urls: Iterable[str], dest: Path, **kw) -> tuple[Path, str]:
    errors = []
    for url in urls:
        try:
            return download(url, dest, **kw), url
        except SourceUnavailable as exc:
            errors.append(str(exc))
    raise SourceUnavailable(" | ".join(errors) or "aucune URL candidate")


def ods_export(bases: Iterable[str], dataset_ids: Iterable[str], dest_dir: Path, fmt: str = "geojson",
               search_terms: Iterable[str] = ()) -> tuple[Path, str]:
    """Telecharge l'export complet d'un jeu Opendatasoft (API Explore v2.1).

    Essaie chaque identifiant sur chaque portail, puis une recherche plein texte
    dans le catalogue si aucun identifiant connu ne repond.
    """
    errors: list[str] = []
    bases = list(bases)
    ids = list(dataset_ids)
    for base in bases:
        for ds in ids:
            url = f"{base}/catalog/datasets/{ds}/exports/{fmt}?lang=fr&timezone=Europe%2FParis"
            dest = dest_dir / f"{ds}.{fmt}"
            try:
                return download(url, dest), url
            except SourceUnavailable as exc:
                errors.append(str(exc))
    for base in bases:
        for term in search_terms:
            try:
                with http_client(60) as client:
                    q = f'{base}/catalog/datasets?where={quote(json.dumps(term))}&limit=20&select=dataset_id'
                    resp = client.get(q)
                    if resp.status_code != 200:
                        continue
                    for item in resp.json().get("results", []):
                        ds = item.get("dataset_id")
                        if not ds or ds in ids:
                            continue
                        url = f"{base}/catalog/datasets/{ds}/exports/{fmt}?lang=fr&timezone=Europe%2FParis"
                        try:
                            return download(url, dest_dir / f"{ds}.{fmt}"), url
                        except SourceUnavailable as exc:
                            errors.append(str(exc))
            except httpx.HTTPError as exc:
                errors.append(f"{base} recherche '{term}' : {exc}")
    raise SourceUnavailable(" | ".join(errors[-6:]) or "jeu introuvable")


def pick(props: dict[str, Any], *candidates: str, default: Any = None) -> Any:
    """Valeur du premier attribut present (comparaison insensible a la casse et aux accents usuels)."""
    if not props:
        return default
    lowered = {str(k).lower(): v for k, v in props.items()}
    for cand in candidates:
        v = lowered.get(cand.lower())
        if v not in (None, "", [], {}):
            return v
    return default


def pick_contains(props: dict[str, Any], *fragments: str, default: Any = None) -> Any:
    for k, v in (props or {}).items():
        lk = str(k).lower()
        if any(f in lk for f in fragments) and v not in (None, "", [], {}):
            return v
    return default


def load_geojson(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return data.get("features", [])
    if isinstance(data, list):  # export JSON Opendatasoft (liste d'enregistrements)
        return [{"type": "Feature", "properties": r, "geometry": r.get("geo_shape") or r.get("geometry")} for r in data]
    raise ValueError(f"{path} n'est pas un GeoJSON exploitable")
