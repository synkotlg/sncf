"""Verification du type REEL des fichiers importes (signature binaire), sans se fier a l'extension."""

from __future__ import annotations

import re
from dataclasses import dataclass

ALLOWED = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


@dataclass
class DetectedType:
    mime: str
    ext: str


class RejectedFile(ValueError):
    pass


def sniff(data: bytes) -> DetectedType | None:
    head = data[:16]
    if head.startswith(b"%PDF-") or (b"%PDF-" in data[:1024] and data[:1024].lstrip().startswith(b"%PDF-")):
        return DetectedType("application/pdf", "pdf")
    if head.startswith(b"\xff\xd8\xff"):
        return DetectedType("image/jpeg", "jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedType("image/png", "png")
    return None


def validate_upload(data: bytes, filename: str | None, max_bytes: int) -> DetectedType:
    if not data:
        raise RejectedFile("fichier vide")
    if len(data) > max_bytes:
        raise RejectedFile(f"fichier trop volumineux ({len(data) // 1024} Ko > {max_bytes // 1024} Ko)")
    detected = sniff(data)
    if detected is None:
        raise RejectedFile("type de fichier non pris en charge (PDF, JPG, JPEG ou PNG uniquement, verifie sur le contenu)")
    name = (filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    expected = {"pdf": "pdf", "jpg": "jpg", "jpeg": "jpg", "png": "png"}
    if ext and ext in expected and expected[ext] != detected.ext:
        raise RejectedFile(f"l'extension .{ext} ne correspond pas au contenu reel ({detected.mime})")
    if ext and ext not in expected:
        raise RejectedFile(f"extension .{ext} non autorisee")
    return detected


def has_active_pdf_content(data: bytes) -> bool:
    """Signale du contenu actif PDF. Il n'est JAMAIS execute (pdfium sans environnement de
    formulaires ni JavaScript) ; l'information est seulement affichee a l'utilisateur."""
    return bool(re.search(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia)\b", data[:5_000_000]))


_SAFE = re.compile(r"[^A-Za-z0-9._ \-()À-ſ]")


def safe_display_name(filename: str | None) -> str:
    """Nom d'origine nettoye, uniquement pour l'affichage (jamais utilise comme chemin)."""
    name = (filename or "document").replace("\\", "/").rsplit("/", 1)[-1]
    name = _SAFE.sub("_", name).strip(" .")
    return (name or "document")[:120]
