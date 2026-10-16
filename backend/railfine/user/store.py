"""Base utilisateur : documents importes, brouillons extraits, amendes validees, correspondances.

Donnees minimisees :
- le numero de dossier n'est conserve que sous forme d'empreinte salee (detection
  des doublons) et de ses 3 derniers caracteres pour l'affichage ;
- les nom, adresse et autres donnees d'identite presentes sur les documents ne
  sont jamais extraits ;
- le texte extrait est purge apres validation, sauf choix contraire de l'utilisateur.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY,
  sha256 TEXT UNIQUE NOT NULL,
  original_name TEXT,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  pages INTEGER,
  stored_name TEXT NOT NULL,
  uploaded_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'en_attente',
  method TEXT,
  ocr_confidence REAL,
  text TEXT,
  warnings TEXT,
  error TEXT,
  active_content INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL DEFAULT 0,
  fields TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'a_valider',
  fine_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fines(
  id INTEGER PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  draft_id INTEGER,
  amount_initial REAL,
  amount_paid REAL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  fine_date TEXT,
  fine_time TEXT,
  origin_name TEXT,
  origin_station_id TEXT,
  dest_name TEXT,
  dest_station_id TEXT,
  control_station_name TEXT,
  control_station_id TEXT,
  origin_resolved_id TEXT,
  dest_resolved_id TEXT,
  control_resolved_id TEXT,
  via_station_ids TEXT,
  train_number TEXT,
  line_label TEXT,
  train_type TEXT,
  carrier TEXT,
  country TEXT,
  reason TEXT,
  reason_text TEXT,
  case_hash TEXT,
  case_hint TEXT,
  status TEXT NOT NULL DEFAULT 'inconnue',
  notes TEXT,
  geo_status TEXT NOT NULL DEFAULT 'none',
  geo_confidence REAL,
  geo_detail TEXT,
  geo_validated INTEGER NOT NULL DEFAULT 0,
  geo_disabled INTEGER NOT NULL DEFAULT 0,
  route_id TEXT,
  uncertain_fields TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fines_date ON fines(fine_date);
CREATE INDEX IF NOT EXISTS idx_fines_case ON fines(case_hash);
CREATE TABLE IF NOT EXISTS fine_links(
  fine_id INTEGER NOT NULL REFERENCES fines(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  label TEXT,
  km REAL,
  confidence REAL,
  method TEXT
);
CREATE INDEX IF NOT EXISTS idx_fine_links ON fine_links(fine_id);
CREATE INDEX IF NOT EXISTS idx_fine_links_ref ON fine_links(kind, ref_id);
CREATE TABLE IF NOT EXISTS fine_paths(
  fine_id INTEGER PRIMARY KEY REFERENCES fines(id) ON DELETE CASCADE,
  graph_version TEXT NOT NULL,
  edges TEXT NOT NULL,
  length_km REAL,
  method TEXT
);
"""

FINE_FIELDS = [
    "amount_initial", "amount_paid", "currency", "fine_date", "fine_time", "origin_name", "origin_station_id",
    "dest_name", "dest_station_id", "control_station_name", "control_station_id", "via_station_ids", "train_number",
    "line_label", "train_type", "carrier", "country", "reason", "reason_text", "status", "notes", "geo_disabled",
    "geo_validated", "uncertain_fields",
]


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class UserStore:
    def __init__(self, path: Path, secret: bytes):
        self.path = path
        self.secret = secret
        conn = self.connect()
        conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = connect(self.path)
        conn.executescript(SCHEMA)
        return conn

    # -- numero de dossier ------------------------------------------------
    def case_hash(self, case_number: str | None) -> tuple[str | None, str | None]:
        if not case_number:
            return None, None
        norm = "".join(ch for ch in str(case_number).upper() if ch.isalnum())
        if len(norm) < 4:
            return None, None
        digest = hmac.new(self.secret, norm.encode(), hashlib.sha256).hexdigest()
        return digest, norm[-3:]

    # -- documents --------------------------------------------------------
    def find_document_by_hash(self, sha: str) -> dict | None:
        conn = self.connect()
        try:
            r = conn.execute("SELECT * FROM documents WHERE sha256=?", (sha,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def add_document(self, sha: str, original_name: str, mime: str, size: int, stored_name: str, active: bool,
                     is_demo: bool = False) -> int:
        conn = self.connect()
        try:
            cur = conn.execute(
                """INSERT INTO documents(sha256, original_name, mime, size, stored_name, uploaded_at, status, active_content, is_demo)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (sha, original_name, mime, size, stored_name, now(), "en_attente", int(active), int(is_demo)),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def update_document(self, doc_id: int, **values: Any) -> None:
        allowed = {"status", "method", "ocr_confidence", "text", "warnings", "error", "pages"}
        sets = {k: v for k, v in values.items() if k in allowed}
        if not sets:
            return
        conn = self.connect()
        try:
            conn.execute(f"UPDATE documents SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), doc_id))
            conn.commit()
        finally:
            conn.close()

    def get_document(self, doc_id: int, with_text: bool = False) -> dict | None:
        conn = self.connect()
        try:
            r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not r:
                return None
            d = dict(r)
            if not with_text:
                d["has_text"] = bool(d.pop("text"))
            d["warnings"] = json.loads(d["warnings"]) if d.get("warnings") else []
            d["drafts"] = [self._draft_row(x) for x in conn.execute("SELECT * FROM drafts WHERE document_id=? ORDER BY idx", (doc_id,))]
            d["fine_ids"] = [x[0] for x in conn.execute("SELECT id FROM fines WHERE document_id=?", (doc_id,))]
            return d
        finally:
            conn.close()

    def list_documents(self) -> list[dict]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """SELECT d.id, d.original_name, d.mime, d.size, d.pages, d.uploaded_at, d.status, d.method, d.ocr_confidence,
                          d.error, d.is_demo, d.active_content,
                          (SELECT COUNT(*) FROM drafts x WHERE x.document_id=d.id AND x.status='a_valider') AS pending_drafts,
                          (SELECT COUNT(*) FROM fines f WHERE f.document_id=d.id) AS fines
                   FROM documents d ORDER BY d.id DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_document(self, doc_id: int, delete_fines: bool) -> dict | None:
        conn = self.connect()
        try:
            r = conn.execute("SELECT stored_name FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not r:
                return None
            fines = [x[0] for x in conn.execute("SELECT id FROM fines WHERE document_id=?", (doc_id,))]
            if delete_fines and fines:
                conn.execute(f"DELETE FROM fines WHERE id IN ({','.join('?' * len(fines))})", fines)
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.commit()
            return {"stored_name": r[0], "fines_deleted": len(fines) if delete_fines else 0}
        finally:
            conn.close()

    # -- brouillons -------------------------------------------------------
    @staticmethod
    def _draft_row(r) -> dict:
        d = dict(r)
        d["fields"] = json.loads(d["fields"])
        return d

    def replace_drafts(self, doc_id: int, drafts: list[dict]) -> list[int]:
        conn = self.connect()
        try:
            conn.execute("DELETE FROM drafts WHERE document_id=? AND status='a_valider'", (doc_id,))
            ids = []
            for i, fields in enumerate(drafts):
                cur = conn.execute("INSERT INTO drafts(document_id, idx, fields, created_at) VALUES(?,?,?,?)",
                                   (doc_id, i, json.dumps(fields, ensure_ascii=False), now()))
                ids.append(int(cur.lastrowid))
            conn.commit()
            return ids
        finally:
            conn.close()

    def add_draft(self, doc_id: int, fields: dict) -> int:
        conn = self.connect()
        try:
            idx = conn.execute("SELECT COALESCE(MAX(idx), -1) + 1 FROM drafts WHERE document_id=?", (doc_id,)).fetchone()[0]
            cur = conn.execute("INSERT INTO drafts(document_id, idx, fields, created_at) VALUES(?,?,?,?)",
                               (doc_id, idx, json.dumps(fields, ensure_ascii=False), now()))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def get_draft(self, draft_id: int) -> dict | None:
        conn = self.connect()
        try:
            r = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
            return self._draft_row(r) if r else None
        finally:
            conn.close()

    def set_draft_status(self, draft_id: int, status: str, fine_id: int | None = None, strip_evidence: bool = False) -> None:
        conn = self.connect()
        try:
            if strip_evidence:
                r = conn.execute("SELECT fields FROM drafts WHERE id=?", (draft_id,)).fetchone()
                if r:
                    fields = json.loads(r[0])
                    for v in fields.values():
                        if isinstance(v, dict):
                            v["evidence"] = None
                    if isinstance(fields.get("case_number"), dict):
                        fields["case_number"]["value"] = None
                        fields["case_number"]["alternatives"] = []
                    conn.execute("UPDATE drafts SET fields=? WHERE id=?", (json.dumps(fields, ensure_ascii=False), draft_id))
            conn.execute("UPDATE drafts SET status=?, fine_id=? WHERE id=?", (status, fine_id, draft_id))
            conn.commit()
        finally:
            conn.close()

    def maybe_purge_document_text(self, doc_id: int) -> None:
        """Supprime le texte extrait quand plus aucun brouillon n'est en attente."""
        conn = self.connect()
        try:
            pending = conn.execute("SELECT COUNT(*) FROM drafts WHERE document_id=? AND status='a_valider'", (doc_id,)).fetchone()[0]
            if pending == 0:
                conn.execute("UPDATE documents SET text=NULL WHERE id=?", (doc_id,))
                conn.commit()
        finally:
            conn.close()

    # -- amendes ----------------------------------------------------------
    def insert_fine(self, values: dict, document_id: int | None = None, draft_id: int | None = None,
                    case_number: str | None = None, is_demo: bool = False) -> int:
        h, hint = self.case_hash(case_number)
        cols = [c for c in FINE_FIELDS if c in values]
        conn = self.connect()
        try:
            cur = conn.execute(
                f"""INSERT INTO fines({', '.join(cols)}, document_id, draft_id, case_hash, case_hint, is_demo, created_at, updated_at)
                    VALUES({', '.join('?' * len(cols))}, ?, ?, ?, ?, ?, ?, ?)""",
                (*[_serialize(values[c]) for c in cols], document_id, draft_id, h, hint, int(is_demo), now(), now()),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def update_fine(self, fine_id: int, values: dict, case_number: str | None = None, clear_case: bool = False) -> None:
        cols = [c for c in FINE_FIELDS if c in values]
        sets = [f"{c}=?" for c in cols]
        params = [_serialize(values[c]) for c in cols]
        if case_number:
            h, hint = self.case_hash(case_number)
            sets += ["case_hash=?", "case_hint=?"]
            params += [h, hint]
        elif clear_case:
            sets += ["case_hash=NULL", "case_hint=NULL"]
        sets.append("updated_at=?")
        params.append(now())
        conn = self.connect()
        try:
            conn.execute(f"UPDATE fines SET {', '.join(sets)} WHERE id=?", (*params, fine_id))
            conn.commit()
        finally:
            conn.close()

    def set_geo(self, fine_id: int, geo: dict, links: list[dict], path: dict | None) -> None:
        conn = self.connect()
        try:
            conn.execute(
                """UPDATE fines SET geo_status=?, geo_confidence=?, geo_detail=?, route_id=?, country=COALESCE(country, ?),
                   origin_resolved_id=?, dest_resolved_id=?, control_resolved_id=? WHERE id=?""",
                (geo["status"], geo.get("confidence"), json.dumps(geo.get("detail") or {}, ensure_ascii=False), geo.get("route_id"),
                 geo.get("country"), geo.get("origin_resolved_id"), geo.get("dest_resolved_id"), geo.get("control_resolved_id"), fine_id),
            )
            conn.execute("DELETE FROM fine_links WHERE fine_id=?", (fine_id,))
            for l in links:
                conn.execute("INSERT INTO fine_links(fine_id, kind, ref_id, label, km, confidence, method) VALUES(?,?,?,?,?,?,?)",
                             (fine_id, l["kind"], l["ref_id"], l.get("label"), l.get("km"), l.get("confidence"), l.get("method")))
            conn.execute("DELETE FROM fine_paths WHERE fine_id=?", (fine_id,))
            if path:
                conn.execute("INSERT INTO fine_paths(fine_id, graph_version, edges, length_km, method) VALUES(?,?,?,?,?)",
                             (fine_id, path["graph_version"], json.dumps(path["edges"]), path.get("length_km"), path.get("method")))
            conn.commit()
        finally:
            conn.close()

    def get_fine(self, fine_id: int) -> dict | None:
        conn = self.connect()
        try:
            r = conn.execute("SELECT * FROM fines WHERE id=?", (fine_id,)).fetchone()
            if not r:
                return None
            d = _fine_row(r)
            d["links"] = [dict(x) for x in conn.execute("SELECT kind, ref_id, label, km, confidence, method FROM fine_links WHERE fine_id=?", (fine_id,))]
            p = conn.execute("SELECT graph_version, length_km, method FROM fine_paths WHERE fine_id=?", (fine_id,)).fetchone()
            d["path"] = dict(p) if p else None
            return d
        finally:
            conn.close()

    def list_fines(self, include_demo: bool = True) -> list[dict]:
        conn = self.connect()
        try:
            q = "SELECT * FROM fines" + ("" if include_demo else " WHERE is_demo=0") + " ORDER BY fine_date DESC, fine_time DESC, id DESC"
            fines = [_fine_row(r) for r in conn.execute(q)]
            links: dict[int, list] = {}
            for r in conn.execute("SELECT fine_id, kind, ref_id, label, km, confidence, method FROM fine_links"):
                links.setdefault(r["fine_id"], []).append(dict(r))
            for f in fines:
                f["links"] = links.get(f["id"], [])
            return fines
        finally:
            conn.close()

    def delete_fine(self, fine_id: int) -> bool:
        conn = self.connect()
        try:
            cur = conn.execute("DELETE FROM fines WHERE id=?", (fine_id,))
            conn.execute("UPDATE drafts SET status='supprimee' WHERE fine_id=?", (fine_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def paths(self) -> dict[int, dict]:
        conn = self.connect()
        try:
            return {r["fine_id"]: {"graph_version": r["graph_version"], "edges": json.loads(r["edges"]), "length_km": r["length_km"],
                                   "method": r["method"]} for r in conn.execute("SELECT * FROM fine_paths")}
        finally:
            conn.close()

    # -- doublons ---------------------------------------------------------
    def find_duplicates(self, values: dict, case_number: str | None, exclude_id: int | None = None) -> list[dict]:
        """Doublon certain : meme numero de dossier. Doublon probable : meme date + heure/montant + gares."""
        conn = self.connect()
        out = []
        try:
            h, _ = self.case_hash(case_number)
            if h:
                for r in conn.execute("SELECT * FROM fines WHERE case_hash=?", (h,)):
                    if r["id"] != exclude_id:
                        out.append({"fine": _fine_row(r), "reason": "même numéro de dossier", "certainty": "certain"})
            date = values.get("fine_date")
            if date:
                for r in conn.execute("SELECT * FROM fines WHERE fine_date=?", (date,)):
                    if r["id"] == exclude_id or any(o["fine"]["id"] == r["id"] for o in out):
                        continue
                    score = 0
                    if values.get("fine_time") and r["fine_time"] == values.get("fine_time"):
                        score += 2
                    if values.get("amount_initial") is not None and r["amount_initial"] is not None and abs(float(r["amount_initial"]) - float(values["amount_initial"])) < 0.01:
                        score += 1
                    if values.get("train_number") and r["train_number"] == str(values.get("train_number")):
                        score += 1
                    for a, b in (("origin_name", "origin_name"), ("dest_name", "dest_name")):
                        if values.get(a) and r[b] and str(values[a]).strip().lower() == str(r[b]).strip().lower():
                            score += 1
                    if score >= 3:
                        out.append({"fine": _fine_row(r), "reason": "même date et informations très proches", "certainty": "probable"})
            return out
        finally:
            conn.close()

    # -- purge / demo -----------------------------------------------------
    def demo_document_names(self) -> list[str]:
        conn = self.connect()
        try:
            return [r[0] for r in conn.execute("SELECT stored_name FROM documents WHERE is_demo=1")]
        finally:
            conn.close()

    def delete_demo(self) -> dict:
        conn = self.connect()
        try:
            n_f = conn.execute("DELETE FROM fines WHERE is_demo=1").rowcount
            names = [r[0] for r in conn.execute("SELECT stored_name FROM documents WHERE is_demo=1")]
            n_d = conn.execute("DELETE FROM documents WHERE is_demo=1").rowcount
            conn.commit()
            return {"fines": n_f, "documents": n_d, "stored_names": names}
        finally:
            conn.close()

    def counts(self) -> dict:
        conn = self.connect()
        try:
            return {
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "fines": conn.execute("SELECT COUNT(*) FROM fines").fetchone()[0],
                "demo_fines": conn.execute("SELECT COUNT(*) FROM fines WHERE is_demo=1").fetchone()[0],
                "pending_drafts": conn.execute("SELECT COUNT(*) FROM drafts WHERE status='a_valider'").fetchone()[0],
            }
        finally:
            conn.close()


def _serialize(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def _fine_row(r) -> dict:
    d = dict(r)
    d.pop("case_hash", None)
    for k in ("via_station_ids", "uncertain_fields", "geo_detail"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    d["has_case_number"] = bool(r["case_hash"]) if "case_hash" in r.keys() else False
    return d
