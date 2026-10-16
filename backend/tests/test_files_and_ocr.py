import shutil

import pytest

from railfine.demo import SAMPLE_LINES, make_scan_image, make_text_pdf
from railfine.ingest.filetypes import RejectedFile, has_active_pdf_content, safe_display_name, validate_upload
from railfine.ingest.parser import parse_fine
from railfine.ingest.textextract import extract

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.4\n" + b"\x00" * 32


def test_real_type_is_checked():
    assert validate_upload(PDF, "a.pdf", 10_000).mime == "application/pdf"
    assert validate_upload(PNG, "photo.png", 10_000).ext == "png"
    assert validate_upload(JPG, "photo.jpeg", 10_000).ext == "jpg"
    with pytest.raises(RejectedFile):
        validate_upload(b"MZ\x90\x00 executable", "amende.pdf", 10_000)
    with pytest.raises(RejectedFile):
        validate_upload(PNG, "amende.pdf", 10_000)  # extension mensongère
    with pytest.raises(RejectedFile):
        validate_upload(PDF, "amende.exe", 10_000)
    with pytest.raises(RejectedFile):
        validate_upload(PDF * 1000, "gros.pdf", 1000)
    with pytest.raises(RejectedFile):
        validate_upload(b"", "vide.pdf", 1000)


def test_safe_display_name_blocks_traversal():
    assert safe_display_name("../../etc/passwd") == "passwd"
    assert safe_display_name("C:\\Users\\x\\amende.pdf") == "amende.pdf"
    assert "/" not in safe_display_name("a/b/c<script>.pdf")


def test_active_pdf_content_detected():
    assert has_active_pdf_content(b"%PDF-1.4 /OpenAction << /S /JavaScript /JS (app.alert(1)) >>")
    assert not has_active_pdf_content(make_text_pdf(["bonjour"]))


def test_native_pdf_text_extraction(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(make_text_pdf(SAMPLE_LINES))
    ext = extract(p, "application/pdf", ocr=False)
    assert ext.method == "texte"
    v = parse_fine(ext.text)
    assert v["amount_initial"].value == 62.4
    assert v["origin_name"].value == "Lille Flandres"
    assert v["fine_date"].value == "2025-03-14"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract non installé")
def test_ocr_on_scanned_image(tmp_path):
    p = tmp_path / "scan.png"
    make_scan_image(SAMPLE_LINES).save(p)
    ext = extract(p, "image/png", ocr=True, languages="fra+eng")
    assert ext.method == "ocr" and (ext.ocr_confidence or 0) > 60
    v = parse_fine(ext.text)
    assert v["amount_initial"].value == 62.4
    assert v["train_number"].value == "847123"
    assert v["fine_time"].value == "07:52"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract non installé")
def test_ocr_on_scanned_pdf(tmp_path):
    p = tmp_path / "scan.pdf"
    make_scan_image(SAMPLE_LINES).save(p, format="PDF", resolution=150)
    ext = extract(p, "application/pdf", ocr=True, languages="fra+eng")
    assert ext.method == "ocr"
    assert parse_fine(ext.text)["dest_name"].value == "Arras"


def test_corrupted_image_rejected(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(PNG)
    with pytest.raises(Exception):
        extract(p, "image/png", ocr=False)
