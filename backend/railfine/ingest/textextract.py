"""Extraction du texte : couche texte des PDF natifs, OCR Tesseract local pour les scans et images.

Aucun document n'est envoye a un service externe. Tesseract est appele en
sous-processus avec une liste d'arguments (pas de shell) et un delai maximal.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger("railfine.ocr")

Image.MAX_IMAGE_PIXELS = 80_000_000  # protection contre les "bombes de decompression"
MIN_TEXT_CHARS = 60
OCR_DPI = 300
OCR_TIMEOUT = 180


@dataclass
class PageText:
    page: int
    text: str
    method: str  # "texte" | "ocr" | "vide"
    confidence: float | None = None


@dataclass
class Extraction:
    pages: list[PageText] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\f\n".join(p.text for p in self.pages)

    @property
    def method(self) -> str:
        methods = {p.method for p in self.pages if p.method != "vide"}
        if not methods:
            return "aucun"
        return "mixte" if len(methods) > 1 else methods.pop()

    @property
    def ocr_confidence(self) -> float | None:
        confs = [p.confidence for p in self.pages if p.confidence is not None]
        return round(sum(confs) / len(confs), 1) if confs else None


class OcrUnavailable(RuntimeError):
    pass


def _meaningful(text: str) -> int:
    return sum(1 for c in text if c.isalnum())


@lru_cache(maxsize=4)
def available_languages(cmd: str) -> tuple[str, ...]:
    exe = shutil.which(cmd) or (cmd if Path(cmd).exists() else None)
    if not exe:
        return ()
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    langs = [line.strip() for line in (out.stdout + out.stderr).splitlines()[1:] if line.strip() and " " not in line.strip()]
    return tuple(langs)


def tesseract_status(cmd: str) -> dict:
    langs = available_languages(cmd)
    return {"available": bool(langs), "command": cmd, "languages": list(langs)}


def _ocr_image(img: Image.Image, cmd: str, languages: str) -> tuple[str, float | None]:
    langs = available_languages(cmd)
    if not langs:
        raise OcrUnavailable("Tesseract introuvable : installez-le (voir README) ou définissez TESSERACT_CMD")
    wanted = [l for l in languages.split("+") if l in langs] or [l for l in ("fra", "eng") if l in langs] or [langs[0]]
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    if gray.width < 1600:
        factor = min(3.0, 1600 / max(1, gray.width))
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.LANCZOS)
    with tempfile.TemporaryDirectory(prefix="railfine-ocr-") as tmp:
        src = Path(tmp) / "page.png"
        gray.save(src, format="PNG")
        exe = shutil.which(cmd) or cmd
        proc = subprocess.run(
            [exe, str(src), "stdout", "-l", "+".join(wanted), "--psm", "3", "tsv"],
            capture_output=True, text=True, timeout=OCR_TIMEOUT, check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"Echec OCR : {proc.stderr.strip()[:300]}")
    return _tsv_to_text(proc.stdout)


def _tsv_to_text(tsv: str) -> tuple[str, float | None]:
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1
        if conf >= 0:
            confs.append(conf)
        key = (int(row["page_num"]), int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(word)
    out = []
    last_block = None
    for key in sorted(lines):
        if last_block is not None and key[:3] != last_block:
            out.append("")
        out.append(" ".join(lines[key]))
        last_block = key[:3]
    return "\n".join(out), (round(sum(confs) / len(confs), 1) if confs else None)


def extract_pdf(path: Path, max_pages: int, ocr: bool, cmd: str, languages: str) -> Extraction:
    import pypdfium2 as pdfium

    result = Extraction()
    try:
        pdf = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        raise ValueError(f"PDF illisible ou protege par mot de passe : {exc}") from exc
    try:
        n = len(pdf)
        if n > max_pages:
            result.warnings.append(f"{n} pages : seules les {max_pages} premières sont analysées")
        for i in range(min(n, max_pages)):
            page = pdf[i]
            textpage = page.get_textpage()
            text = textpage.get_text_bounded() or ""
            textpage.close()
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if _meaningful(text) >= MIN_TEXT_CHARS:
                result.pages.append(PageText(i + 1, text, "texte"))
            elif ocr:
                bitmap = page.render(scale=OCR_DPI / 72)
                img = bitmap.to_pil()
                bitmap.close()
                try:
                    otext, conf = _ocr_image(img, cmd, languages)
                    result.pages.append(PageText(i + 1, otext, "ocr", conf))
                except OcrUnavailable as exc:
                    result.warnings.append(str(exc))
                    result.pages.append(PageText(i + 1, text, "vide" if not text.strip() else "texte"))
            else:
                result.warnings.append(f"page {i + 1} sans couche texte et OCR désactivé")
                result.pages.append(PageText(i + 1, text, "vide" if not text.strip() else "texte"))
            page.close()
    finally:
        pdf.close()
    return result


def extract_image(path: Path, ocr: bool, cmd: str, languages: str) -> Extraction:
    result = Extraction()
    with Image.open(path) as img:
        img.verify()  # detecte les fichiers corrompus / tronques
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img.load()
        if not ocr:
            result.warnings.append("OCR désactivé : aucune donnée extraite de l'image")
            result.pages.append(PageText(1, "", "vide"))
            return result
        text, conf = _ocr_image(img, cmd, languages)
    result.pages.append(PageText(1, text, "ocr", conf))
    if conf is not None and conf < 60:
        result.warnings.append(f"qualité OCR faible (confiance moyenne {conf}/100) : vérifiez chaque champ")
    return result


def extract(path: Path, mime: str, *, max_pages: int = 30, ocr: bool = True, cmd: str = "tesseract",
            languages: str = "fra+nld+eng") -> Extraction:
    if mime == "application/pdf":
        return extract_pdf(path, max_pages, ocr, cmd, languages)
    if mime in ("image/jpeg", "image/png"):
        return extract_image(path, ocr, cmd, languages)
    raise ValueError(f"type non pris en charge : {mime}")
