"""Traitement en arrière-plan des documents importés (extraction + analyse -> brouillons à valider)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import AppConfig
from ..reference import matching
from ..reference.store import ReferenceStore
from ..user.store import UserStore
from .filetypes import has_active_pdf_content, safe_display_name, validate_upload
from .parser import parse_document, summarize
from .textextract import extract

log = logging.getLogger("railfine.jobs")


class DocumentProcessor:
    def __init__(self, cfg: AppConfig, store: UserStore):
        self.cfg = cfg
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="railfine-ocr")
        self._lock = threading.Lock()

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

    def path_for(self, stored_name: str) -> Path:
        # stored_name = "<sha256>.<ext>" genere par l'application : jamais derive d'une saisie utilisateur
        p = (self.cfg.paths.documents_dir / stored_name).resolve()
        if p.parent != self.cfg.paths.documents_dir.resolve():
            raise ValueError("chemin de document invalide")
        return p

    def ingest(self, data: bytes, filename: str | None, is_demo: bool = False) -> dict:
        settings = self.cfg.settings
        detected = validate_upload(data, filename, settings.max_upload_mb * 1024 * 1024)
        sha = hashlib.sha256(data).hexdigest()
        existing = self.store.find_document_by_hash(sha)
        if existing:
            return {"id": existing["id"], "duplicate": True, "status": existing["status"], "name": existing["original_name"]}
        stored_name = f"{sha}.{detected.ext}"
        target = self.path_for(stored_name)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        active = detected.mime == "application/pdf" and has_active_pdf_content(data)
        doc_id = self.store.add_document(sha, safe_display_name(filename), detected.mime, len(data), stored_name, active, is_demo)
        self.pool.submit(self.process, doc_id)
        return {"id": doc_id, "duplicate": False, "status": "en_attente", "name": safe_display_name(filename),
                "active_content": active}

    def reprocess(self, doc_id: int) -> None:
        self.store.update_document(doc_id, status="en_attente", error=None)
        self.pool.submit(self.process, doc_id)

    def process(self, doc_id: int) -> None:
        doc = self.store.get_document(doc_id)
        if not doc:
            return
        settings = self.cfg.settings
        self.store.update_document(doc_id, status="traitement", error=None)
        try:
            path = self.path_for(doc["stored_name"])
            ext = extract(path, doc["mime"], max_pages=settings.max_pdf_pages, ocr=settings.ocr_enabled,
                          cmd=self.cfg.tesseract_cmd, languages=settings.ocr_languages)
            text = ext.text
            warnings = list(ext.warnings)
            if doc.get("active_content"):
                warnings.append("le PDF déclare du contenu actif (JavaScript, pièces jointes) : il n'a pas été exécuté")
            index = matching.get_index(ReferenceStore(self.cfg.paths.reference_db))
            drafts = parse_document(text, index.find_mentions) if text.strip() else []
            if not drafts:
                warnings.append("aucun texte exploitable : saisissez les informations manuellement")
            for d in drafts:
                info = summarize(d)
                d["_summary"] = info
            self.store.replace_drafts(doc_id, drafts)
            self.store.update_document(doc_id, status="a_valider" if drafts else "sans_texte", method=ext.method,
                                       ocr_confidence=ext.ocr_confidence, text=text, pages=len(ext.pages),
                                       warnings=json.dumps(warnings, ensure_ascii=False))
        except Exception as exc:  # erreur de lecture : signalée à l'utilisateur, jamais silencieuse
            log.exception("échec du traitement du document %s", doc_id)
            self.store.update_document(doc_id, status="erreur", error=f"{type(exc).__name__}: {exc}"[:500])
