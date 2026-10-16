"""Règles métier : validation des saisies, création/mise à jour des amendes, doublons, géolocalisation."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..categories import COUNTRIES, FINE_STATUSES, REASONS, TRAIN_TYPES
from ..config import AppConfig
from ..ingest.parser import parse_date_value, parse_time_value
from .geomatch import GeoContext, geolocate
from .store import UserStore

log = logging.getLogger("railfine.fines")


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class DuplicateError(ValueError):
    def __init__(self, duplicates: list[dict]):
        super().__init__("doublon potentiel")
        self.duplicates = duplicates


def _amount(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = re.sub(r"[^\d,.\-]", "", str(v)).replace(",", ".")
        if s.count(".") > 1:
            head, _, tail = s.rpartition(".")
            s = head.replace(".", "") + "." + tail
        try:
            f = float(s)
        except ValueError:
            raise ValueError("montant invalide")
    if f < 0 or f > 100000:
        raise ValueError("montant hors limites")
    return round(f, 2)


def _text(v: Any, max_len: int = 200) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:max_len] or None


def clean_fine_payload(payload: dict) -> tuple[dict, str | None, bool]:
    """Normalise une saisie (formulaire ou brouillon). Retourne (valeurs, numéro de dossier, effacer_numero)."""
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    for key in ("amount_initial", "amount_paid"):
        if key in payload:
            try:
                out[key] = _amount(payload[key])
            except ValueError as exc:
                errors[key] = str(exc)
    if "currency" in payload:
        cur = (_text(payload["currency"], 3) or "EUR").upper()
        if not re.fullmatch(r"[A-Z]{3}", cur):
            errors["currency"] = "code devise ISO 4217 attendu (ex. EUR)"
        out["currency"] = cur
    if "fine_date" in payload:
        if payload["fine_date"]:
            d = parse_date_value(str(payload["fine_date"]))
            if not d:
                errors["fine_date"] = "date invalide (AAAA-MM-JJ ou JJ/MM/AAAA)"
            out["fine_date"] = d
        else:
            out["fine_date"] = None
    if "fine_time" in payload:
        if payload["fine_time"]:
            t = parse_time_value(str(payload["fine_time"]))
            if not t:
                errors["fine_time"] = "heure invalide (HH:MM)"
            out["fine_time"] = t
        else:
            out["fine_time"] = None
    for key, n in (("origin_name", 120), ("dest_name", 120), ("control_station_name", 120), ("line_label", 40),
                   ("carrier", 80), ("reason_text", 200), ("notes", 1000), ("origin_station_id", 80),
                   ("dest_station_id", 80), ("control_station_id", 80)):
        if key in payload:
            out[key] = _text(payload[key], n)
    if "train_number" in payload:
        tn = _text(payload["train_number"], 10)
        if tn and not re.fullmatch(r"\d{1,6}", tn):
            errors["train_number"] = "numéro de train : chiffres uniquement"
        out["train_number"] = tn.lstrip("0") if tn else None
    for key, allowed in (("train_type", TRAIN_TYPES), ("reason", REASONS), ("status", FINE_STATUSES), ("country", COUNTRIES)):
        if key in payload:
            v = payload[key] or None
            if v is not None and v not in allowed:
                errors[key] = f"valeur non reconnue : {v}"
            out[key] = v
    if out.get("status") is None and "status" in payload:
        out["status"] = "inconnue"
    if "via_station_ids" in payload:
        via = payload["via_station_ids"] or []
        if not isinstance(via, list) or len(via) > 10:
            errors["via_station_ids"] = "liste de gares invalide"
        out["via_station_ids"] = [str(v)[:80] for v in via][:10] if isinstance(via, list) else []
    for key in ("geo_disabled", "geo_validated"):
        if key in payload:
            out[key] = bool(payload[key])
    if "uncertain_fields" in payload:
        uf = payload["uncertain_fields"] or []
        out["uncertain_fields"] = [str(x)[:40] for x in uf][:30] if isinstance(uf, list) else []
    if out.get("amount_paid") is not None and out.get("amount_initial") is not None and out["amount_paid"] > out["amount_initial"] * 10:
        errors["amount_paid"] = "montant payé incohérent avec le montant initial"
    if errors:
        raise ValidationError(errors)
    case = payload.get("case_number")
    case = _text(case, 40) if case else None
    clear_case = "case_number" in payload and not case
    return out, case, clear_case


class FineService:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.store = UserStore(cfg.paths.user_db, cfg.secret())

    def geo_context(self) -> GeoContext:
        return GeoContext.load(self.cfg)

    def relocate(self, fine_id: int, ctx: GeoContext | None = None) -> dict | None:
        fine = self.store.get_fine(fine_id)
        if not fine:
            return None
        ctx = ctx or self.geo_context()
        geo, links, path = geolocate(fine, ctx)
        self.store.set_geo(fine_id, geo, links, path)
        if not fine.get("train_type") and geo.get("detail", {}).get("train"):
            self.store.update_fine(fine_id, {"train_type": geo["detail"]["train"]["category"]})
        return self.store.get_fine(fine_id)

    def relocate_all(self) -> int:
        ctx = self.geo_context()
        n = 0
        for f in self.store.list_fines():
            self.relocate(f["id"], ctx)
            n += 1
        return n

    def create(self, payload: dict, document_id: int | None = None, draft_id: int | None = None, force: bool = False,
               is_demo: bool = False) -> dict:
        values, case, _ = clean_fine_payload(payload)
        values.setdefault("status", "inconnue")
        values.setdefault("currency", "EUR")
        if not force:
            dups = self.store.find_duplicates(values, case)
            if dups:
                raise DuplicateError(dups)
        fine_id = self.store.insert_fine(values, document_id=document_id, draft_id=draft_id, case_number=case, is_demo=is_demo)
        return self.relocate(fine_id)

    def update(self, fine_id: int, payload: dict, force: bool = False) -> dict:
        if not self.store.get_fine(fine_id):
            raise KeyError(fine_id)
        values, case, clear_case = clean_fine_payload(payload)
        if case and not force:
            dups = [d for d in self.store.find_duplicates({}, case, exclude_id=fine_id) if d["certainty"] == "certain"]
            if dups:
                raise DuplicateError(dups)
        # toute modification des éléments de localisation invalide la validation manuelle précédente
        geo_keys = {"origin_name", "dest_name", "origin_station_id", "dest_station_id", "train_number", "fine_date", "via_station_ids"}
        if geo_keys & set(values) and "geo_validated" not in values:
            current = self.store.get_fine(fine_id)
            if any(values.get(k) != current.get(k) for k in geo_keys & set(values)):
                values["geo_validated"] = False
        self.store.update_fine(fine_id, values, case_number=case, clear_case=clear_case)
        return self.relocate(fine_id)

    def validate_draft(self, draft_id: int, payload: dict, force: bool = False) -> dict:
        draft = self.store.get_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        if draft["status"] != "a_valider":
            raise ValueError("brouillon déjà traité")
        if "uncertain_fields" not in payload:
            payload = {**payload, "uncertain_fields": [k for k, v in draft["fields"].items() if isinstance(v, dict) and v.get("uncertain")]}
        fine = self.create(payload, document_id=draft["document_id"], draft_id=draft_id, force=force)
        keep = self.cfg.settings.keep_extracted_text
        self.store.set_draft_status(draft_id, "validee", fine["id"], strip_evidence=not keep)
        if not keep:
            self.store.maybe_purge_document_text(draft["document_id"])
        return fine

    def discard_draft(self, draft_id: int) -> None:
        draft = self.store.get_draft(draft_id)
        if not draft:
            raise KeyError(draft_id)
        self.store.set_draft_status(draft_id, "ecartee", strip_evidence=not self.cfg.settings.keep_extracted_text)
        if not self.cfg.settings.keep_extracted_text:
            self.store.maybe_purge_document_text(draft["document_id"])
