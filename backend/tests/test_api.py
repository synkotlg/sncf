"""Tests d'intégration de l'API (base temporaire, référentiel synthétique)."""

import time

import pytest
from fastapi.testclient import TestClient

from railfine.demo import make_text_pdf
from railfine.main import create_app
from railfine.reference.importers import gtfs
from railfine.reference.store import ReferenceStore

from .conftest import gtfs_zip_bytes

H = {"X-RailFine-Request": "1"}

DOC_LINES = [
    "EXEMPLE FICTIF - DOCUMENT DE TEST",
    "N° de dossier : 5555 6666 7777",
    "Date de l'infraction : 14/03/2025 à 07h52",
    "Train TER n° 12345",
    "Trajet : de Alpha Ville à Beta Centre",
    "Motif : Absence de titre de transport",
    "Montant total à payer : 62,40 €",
]


@pytest.fixture
def client(ref_cfg):
    with TestClient(create_app(ref_cfg)) as c:
        yield c


def wait_processed(client, doc_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = client.get(f"/api/documents/{doc_id}").json()
        if d["status"] not in ("en_attente", "traitement"):
            return d
        time.sleep(0.2)
    raise AssertionError("traitement trop long")


def test_security_headers_and_csrf(client):
    assert client.post("/api/fines", json={}).status_code == 403  # en-tête anti-CSRF manquant
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400  # DNS rebinding
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_upload_rejects_wrong_types(client):
    r = client.post("/api/documents", headers=H, files=[("files", ("amende.pdf", b"MZ\x90\x00not a pdf", "application/pdf"))])
    res = r.json()["results"][0]
    assert not res["ok"] and "type" in res["error"]


def test_full_import_validation_flow(client, ref_cfg, tmp_path):
    # horaires synthétiques : le train 12345 relie Alpha -> Delta -> Beta le 14/03/2025
    z = tmp_path / "g.zip"
    z.write_bytes(gtfs_zip_bytes())
    gtfs.import_gtfs(ReferenceStore(ref_cfg.paths.reference_db), ref_cfg.paths.raw_dir, "sncf_gtfs", file=z)

    pdf = make_text_pdf(DOC_LINES)
    r = client.post("/api/documents", headers=H, files=[("files", ("../../../etc/amende.pdf", pdf, "application/pdf"))])
    res = r.json()["results"][0]
    assert res["ok"] and res["name"] == "amende.pdf"
    # même fichier : détecté comme déjà importé
    again = client.post("/api/documents", headers=H, files=[("files", ("copie.pdf", pdf, "application/pdf"))]).json()["results"][0]
    assert again["duplicate"] and again["id"] == res["id"]

    doc = wait_processed(client, res["id"])
    assert doc["status"] == "a_valider" and doc["method"] == "texte"
    draft = doc["drafts"][0]
    f = draft["fields"]
    assert f["amount_initial"]["value"] == 62.4 and f["origin_name"]["value"] == "Alpha Ville"

    payload = {k: v["value"] for k, v in f.items() if not k.startswith("_")}
    fine = client.post(f"/api/drafts/{draft['id']}/validate", headers=H, json=payload).json()
    assert fine["geo_status"] == "train_confirmed"
    assert fine["origin_resolved_id"] == "uic:8700001" and fine["dest_resolved_id"] == "uic:8700003"
    assert fine["has_case_number"] and fine["case_hint"] == "777"
    assert "case_number" not in fine
    kinds = {l["kind"] for l in fine["links"]}
    assert kinds == {"line", "route", "train"}

    # le texte extrait est purgé après validation (minimisation)
    assert client.get(f"/api/documents/{res['id']}?with_text=true").json()["text"] is None

    # doublon (même numéro de dossier) en saisie manuelle
    dup = client.post("/api/fines", headers=H, json={**payload, "case_number": "5555-6666-7777"})
    assert dup.status_code == 409 and dup.json()["duplicates"][0]["certainty"] == "certain"

    # statistiques et carte
    stats = client.get("/api/stats").json()
    assert stats["summary"]["count"] == 1 and stats["summary"]["total"] == 62.4
    assert stats["rankings"]["trains"]["by_count"][0]["key"] == "12345"
    layers = client.get("/api/map/fines").json()
    assert layers["segments"]["features"] and layers["unlocated"] == 0

    # exports
    csv_text = client.get("/api/export/fines.csv").text
    assert "Alpha Ville" in csv_text and "5555" not in csv_text  # le numéro de dossier n'est jamais exporté
    assert client.get("/api/export/stats.json").json()["summary"]["count"] == 1

    # document source
    r = client.get(f"/api/documents/{res['id']}/file")
    assert r.status_code == 200 and r.content == pdf and r.headers["content-type"] == "application/pdf"


def test_manual_entry_validation_and_geo(client):
    bad = client.post("/api/fines", headers=H, json={"amount_initial": "abc", "fine_date": "32/13/2025", "train_type": "XYZ"})
    assert bad.status_code == 422 and set(bad.json()["errors"]) == {"amount_initial", "fine_date", "train_type"}
    ok = client.post("/api/fines", headers=H, json={"amount_initial": "50,00", "fine_date": "06/01/2025", "fine_time": "8h10",
                                                    "origin_name": "Alpha Ville", "dest_name": "Gamma", "status": "a_payer"}).json()
    assert ok["amount_initial"] == 50.0 and ok["fine_date"] == "2025-01-06" and ok["fine_time"] == "08:10"
    assert ok["geo_status"] == "path_inferred"  # trajet présumé, signalé comme tel
    assert {l["ref_id"] for l in ok["links"] if l["kind"] == "line"} == {"rfn:000001", "rfn:000002"}
    # gares homonymes : non géolocalisée sans choix manuel
    amb = client.post("/api/fines", headers=H, json={"origin_name": "Saint-Test", "fine_date": "2025-01-07"}).json()
    assert amb["geo_status"] == "none" and amb["geo_detail"]["origin"]["ambiguous"]
    # choix manuel de la gare
    fixed = client.put(f"/api/fines/{amb['id']}", headers=H, json={"origin_station_id": "uic:8700005"}).json()
    assert fixed["geo_status"] == "station_only" and fixed["origin_resolved_id"] == "uic:8700005"
    # désactivation explicite
    off = client.put(f"/api/fines/{ok['id']}", headers=H, json={"geo_disabled": True}).json()
    assert off["geo_status"] == "none" and off["links"] == []
    assert client.delete(f"/api/fines/{ok['id']}", headers=H).json()["ok"]


def test_reference_endpoints(client):
    r = client.get("/api/reference/stations/search", params={"q": "alpha"}).json()["results"]
    assert r[0]["id"] == "uic:8700001"
    path = client.get("/api/reference/path", params={"from": "uic:8700001", "to": "uic:8700004"}).json()
    assert path["geometry"]["type"] == "LineString" and "disclaimer" in path["properties"]
    assert client.get("/api/reference/path", params={"from": "uic:8700001", "to": "uic:8800006"}).status_code == 404
    assert client.get("/api/tiles/lines/5/16/11.pbf").status_code == 200
    assert client.get("/api/tiles/nope/5/16/11.pbf").status_code == 400


def test_backup_restore_and_purge(client):
    client.post("/api/fines", headers=H, json={"amount_initial": 35, "fine_date": "2025-02-02", "case_number": "AB12345"})
    backup = client.get("/api/backup")
    assert backup.status_code == 200 and backup.content[:2] == b"PK"
    assert client.delete("/api/user-data?confirm=SUPPRIMER", headers=H).json()["ok"]
    assert client.get("/api/fines").json()["fines"] == []
    r = client.post("/api/restore", headers=H, files={"file": ("b.zip", backup.content, "application/zip")})
    assert r.status_code == 200
    fines = client.get("/api/fines").json()["fines"]
    assert len(fines) == 1
    # le hachage du numéro de dossier reste cohérent après restauration (sel restauré)
    dup = client.post("/api/fines", headers=H, json={"amount_initial": 35, "fine_date": "2025-02-02", "case_number": "AB12345"})
    assert dup.status_code == 409
    # archive non conforme refusée
    assert client.post("/api/restore", headers=H, files={"file": ("x.zip", b"not a zip", "application/zip")}).status_code == 422


def test_demo_data_is_flagged_and_removable(client):
    assert client.post("/api/demo", headers=H).json()["created"] > 10
    fines = client.get("/api/fines").json()["fines"]
    assert fines and all(f["is_demo"] for f in fines)
    assert client.get("/api/stats", params={"include_demo": "false"}).json()["summary"]["count"] == 0
    assert client.delete("/api/demo", headers=H).json()["fines"] == len(fines)
    assert client.get("/api/fines").json()["fines"] == []
