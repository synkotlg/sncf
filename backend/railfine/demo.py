"""Données d'EXEMPLE FICTIVES, clairement identifiées, pour tester l'application.

- ``load_demo_fines`` : insère des amendes fictives (drapeau ``is_demo``), supprimables en un clic ;
- ``write_sample_documents`` : génère des documents fictifs (PDF texte, PDF scanné, image PNG)
  pour essayer l'importation et l'OCR sans utiliser de vrais documents.

Les gares citées sont réelles (pour tester la cartographie), les amendes ne le sont pas.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .user.service import FineService

DEMO_TAG = "EXEMPLE FICTIF - donnée de démonstration"

# (départ, arrivée, type, transporteur, pays, numéro de train ou None, libellé de ligne)
DEMO_TRIPS = [
    ("Lille Flandres", "Arras", "TER", "SNCF Voyageurs - TER Hauts-de-France", "FR", "847123", None),
    ("Lille Flandres", "Arras", "TER", "SNCF Voyageurs - TER Hauts-de-France", "FR", None, None),
    ("Paris Gare de Lyon", "Dijon Ville", "TER", "SNCF Voyageurs", "FR", "891502", None),
    ("Paris Gare de Lyon", "Marseille St-Charles", "TGV", "SNCF Voyageurs", "FR", "6111", None),
    ("Lyon Part-Dieu", "Grenoble", "TER", "SNCF Voyageurs - TER Auvergne-Rhone-Alpes", "FR", None, None),
    ("Paris Nord", "Lille Flandres", "TGV", "SNCF Voyageurs", "FR", "7015", None),
    ("Bordeaux St-Jean", "Toulouse Matabiau", "INTERCITES", "SNCF Voyageurs", "FR", "4655", None),
    ("Strasbourg", "Metz", "TER", "SNCF Voyageurs - TER Grand Est", "FR", None, None),
    ("Nancy", "Metz", "TER", "SNCF Voyageurs - TER Grand Est", "FR", "88712", None),
    ("Bruxelles-Midi", "Liège-Guillemins", "SNCB", "SNCB", "BE", "2117", None),
    ("Bruxelles-Midi", "Namur", "SNCB", "SNCB", "BE", None, None),
    ("Antwerpen-Centraal", "Gent-Sint-Pieters", "SNCB", "SNCB", "BE", "1817", None),
    ("Lille Flandres", "Bruxelles-Midi", "SNCB", "SNCB", "BE", None, None),
    ("Rennes", "Nantes", "TER", "SNCF Voyageurs - TER Bretagne", "FR", None, None),
    (None, None, "TER", "SNCF Voyageurs", "FR", None, None),  # amende sans gare : non géolocalisée
]
REASONS = ["absence_titre", "absence_titre", "non_validation", "titre_non_valide", "surclassement", "reduction", "comportement"]


def load_demo_fines(service: FineService, n: int = 36, seed: int = 42) -> int:
    rng = random.Random(seed)
    start = date(2024, 1, 8)
    created = 0
    for i in range(n):
        o, d, ttype, carrier, country, train, line = DEMO_TRIPS[i % len(DEMO_TRIPS)] if i < len(DEMO_TRIPS) else rng.choice(DEMO_TRIPS[:9] + DEMO_TRIPS[9:12])
        day = start + timedelta(days=rng.randint(0, 600))
        hour = rng.choice([6, 7, 7, 8, 8, 8, 9, 12, 13, 17, 17, 18, 18, 19, 21, 22])
        base = rng.choice([35.0, 50.0, 50.0, 75.0, 90.0, 135.0]) if country == "FR" else rng.choice([75.0, 75.0, 100.0, 225.0])
        status = rng.choice(["payee", "payee", "a_payer", "contestee", "inconnue"])
        payload = {
            "amount_initial": base,
            "amount_paid": base if status == "payee" else None,
            "currency": "EUR",
            "fine_date": day.isoformat(),
            "fine_time": f"{hour:02d}:{rng.randint(0, 59):02d}",
            "origin_name": o,
            "dest_name": d,
            "train_number": train,
            "line_label": line,
            "train_type": ttype,
            "carrier": carrier,
            "country": country,
            "reason": rng.choice(REASONS),
            "status": status,
            "notes": DEMO_TAG,
            "case_number": f"DEMO{i:04d}{rng.randint(1000, 9999)}",
        }
        service.create(payload, force=True, is_demo=True)
        created += 1
    return created


# ------------------------------------------------------------------ documents d'essai
SAMPLE_LINES = [
    "SNCF VOYAGEURS - TER Hauts-de-France",
    "EXEMPLE FICTIF - DOCUMENT DE TEST SANS VALEUR",
    "PROCES-VERBAL DE CONSTATATION D'INFRACTION",
    "N° de dossier : 9999 0000 1234",
    "Date de l'infraction : 14/03/2025 à 07h52",
    "Train TER n° 847123",
    "Trajet : de Lille Flandres à Arras",
    "Motif : Absence de titre de transport",
    "Prix du billet : 12,40 €",
    "Indemnité forfaitaire : 50,00 €",
    "Montant total à payer : 62,40 €",
    "A payer avant le 13/05/2025.",
]

SAMPLE_LINES_SNCB = [
    "SNCB - Constat d'irrégularité",
    "EXEMPLE FICTIF - DOCUMENT DE TEST SANS VALEUR",
    "N° de dossier : 9999 0000 5678",
    "Date du contrôle : 03/02/2025   Heure : 08:12",
    "Train IC 2117",
    "Trajet : Bruxelles-Midi - Liège-Guillemins",
    "Motif : Titre de transport non validé",
    "Montant à payer : 75,00 EUR",
]


def _pdf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_text_pdf(lines: list[str]) -> bytes:
    """PDF minimal avec une vraie couche texte (police Helvetica, encodage WinAnsi)."""
    content = ["BT", "/F1 12 Tf", "14 TL", "60 780 Td"]
    for line in lines:
        content.append(f"({_pdf_escape(line)}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("cp1252", errors="replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _font(size: int):
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_scan_image(lines: list[str], rotate: float = 0.6) -> Image.Image:
    img = Image.new("L", (1700, 1400), 248)
    draw = ImageDraw.Draw(img)
    font = _font(34)
    y = 90
    for line in lines:
        draw.text((90, y), line, fill=25, font=font)
        y += 62
    img = img.rotate(rotate, expand=False, fillcolor=248)
    return img.convert("RGB")


def write_sample_documents(target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    out = []
    p = target / "exemple_fictif_pv_ter.pdf"
    p.write_bytes(make_text_pdf(SAMPLE_LINES))
    out.append(p)
    img = make_scan_image(SAMPLE_LINES_SNCB)
    p = target / "exemple_fictif_constat_sncb.png"
    img.save(p, format="PNG")
    out.append(p)
    p = target / "exemple_fictif_scan.pdf"
    make_scan_image(SAMPLE_LINES).save(p, format="PDF", resolution=150)
    out.append(p)
    return out
