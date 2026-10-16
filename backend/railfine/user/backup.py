"""Sauvegarde et restauration des données personnelles (archive ZIP locale).

La restauration n'accepte que des entrées connues (pas de chemins arbitraires,
pas de liens) et vérifie la nature de chaque fichier avant de remplacer les données.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from ..config import Paths
from ..ingest.filetypes import sniff

DOC_NAME = re.compile(r"^documents/([0-9a-f]{64})\.(pdf|jpg|png)$")
MAX_RESTORE_BYTES = 4_000_000_000
MANIFEST = "railfine-backup.json"


def create_backup(paths: Paths) -> bytes:
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="railfine-bak-") as tmp:
        db_copy = Path(tmp) / "railfine.sqlite"
        if paths.user_db.exists():
            src = sqlite3.connect(str(paths.user_db))
            dst = sqlite3.connect(str(db_copy))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST, json.dumps({"app": "RailFine Analytics", "format": 1,
                                              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}))
            if db_copy.exists():
                zf.write(db_copy, "railfine.sqlite")
            if paths.settings_file.exists():
                zf.write(paths.settings_file, "settings.json")
            if paths.secret_file.exists():
                zf.write(paths.secret_file, ".secret")
            for f in sorted(paths.documents_dir.glob("*")):
                if f.is_file() and DOC_NAME.match(f"documents/{f.name}"):
                    zf.write(f, f"documents/{f.name}")
    return buf.getvalue()


class RestoreError(ValueError):
    pass


def restore_backup(paths: Paths, data: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise RestoreError("archive ZIP invalide") from exc
    names = zf.namelist()
    if MANIFEST not in names:
        raise RestoreError("ce fichier n'est pas une sauvegarde RailFine")
    total = sum(i.file_size for i in zf.infolist())
    if total > MAX_RESTORE_BYTES:
        raise RestoreError("archive trop volumineuse")
    allowed_fixed = {MANIFEST, "railfine.sqlite", "settings.json", ".secret"}
    for info in zf.infolist():
        if info.is_dir():
            continue
        if info.filename not in allowed_fixed and not DOC_NAME.match(info.filename):
            raise RestoreError(f"entrée inattendue dans l'archive : {info.filename[:80]}")
    with tempfile.TemporaryDirectory(prefix="railfine-restore-", dir=paths.user_dir) as tmp:
        stage = Path(tmp)
        (stage / "documents").mkdir()
        restored_docs = 0
        for info in zf.infolist():
            if info.is_dir() or info.filename == MANIFEST:
                continue
            content = zf.read(info)
            if info.filename == "railfine.sqlite":
                if not content.startswith(b"SQLite format 3\x00"):
                    raise RestoreError("base de données invalide dans l'archive")
                (stage / "railfine.sqlite").write_bytes(content)
            elif info.filename == "settings.json":
                json.loads(content.decode("utf-8"))
                (stage / "settings.json").write_bytes(content)
            elif info.filename == ".secret":
                if not re.fullmatch(rb"[0-9a-f]{32,128}\s*", content):
                    raise RestoreError("fichier .secret invalide")
                (stage / ".secret").write_bytes(content)
            else:
                m = DOC_NAME.match(info.filename)
                det = sniff(content)
                if det is None or det.ext != m.group(2):
                    raise RestoreError(f"document au contenu inattendu : {info.filename[:80]}")
                (stage / "documents" / f"{m.group(1)}.{m.group(2)}").write_bytes(content)
                restored_docs += 1
        if (stage / "railfine.sqlite").exists():
            conn = sqlite3.connect(str(stage / "railfine.sqlite"))
            try:
                ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
            if ok != "ok" or not {"fines", "documents"} <= tables:
                raise RestoreError("base de données de la sauvegarde endommagée ou incompatible")
        # remplacement
        for suffix in ("", "-wal", "-shm"):
            Path(str(paths.user_db) + suffix).unlink(missing_ok=True)
        if (stage / "railfine.sqlite").exists():
            shutil.move(str(stage / "railfine.sqlite"), paths.user_db)
        for name, target in (("settings.json", paths.settings_file), (".secret", paths.secret_file)):
            if (stage / name).exists():
                shutil.move(str(stage / name), target)
        for f in paths.documents_dir.glob("*"):
            if f.is_file():
                f.unlink()
        for f in (stage / "documents").glob("*"):
            shutil.move(str(f), paths.documents_dir / f.name)
    return {"documents": restored_docs}


def purge_all(paths: Paths) -> None:
    """Suppression définitive de toutes les données personnelles (amendes, documents, exports)."""
    for suffix in ("", "-wal", "-shm"):
        Path(str(paths.user_db) + suffix).unlink(missing_ok=True)
    for d in (paths.documents_dir, paths.exports_dir):
        for f in d.glob("*"):
            if f.is_file():
                f.unlink()
