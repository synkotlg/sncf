"""Chemins, limites et parametres de l'application.

Separation stricte :
- data/reference/ : donnees ferroviaires de reference (publiques, regenerables) ;
- data/user/      : donnees personnelles (amendes, documents, parametres) ;
- data/user/exports : resultats d'analyse exportes.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class Paths:
    def __init__(self, data_dir: Path | None = None):
        self.data = Path(data_dir or os.environ.get("RAILFINE_DATA_DIR") or REPO_ROOT / "data").resolve()

    @property
    def reference_dir(self) -> Path:
        return self.data / "reference"

    @property
    def raw_dir(self) -> Path:
        return self.reference_dir / "raw"

    @property
    def reference_db(self) -> Path:
        return self.reference_dir / "rail.sqlite"

    @property
    def graph_cache(self) -> Path:
        return self.reference_dir / "graph.pickle"

    @property
    def user_dir(self) -> Path:
        return self.data / "user"

    @property
    def user_db(self) -> Path:
        return self.user_dir / "railfine.sqlite"

    @property
    def documents_dir(self) -> Path:
        return self.user_dir / "documents"

    @property
    def exports_dir(self) -> Path:
        return self.user_dir / "exports"

    @property
    def settings_file(self) -> Path:
        return self.user_dir / "settings.json"

    @property
    def secret_file(self) -> Path:
        return self.user_dir / ".secret"

    def ensure(self) -> None:
        for p in (self.reference_dir, self.raw_dir, self.user_dir, self.documents_dir, self.exports_dir):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    """Parametres modifiables depuis l'interface (persistes dans data/user/settings.json)."""

    ocr_enabled: bool = True
    ocr_languages: str = "fra+nld+eng"
    keep_extracted_text: bool = False
    max_upload_mb: int = 20
    max_pdf_pages: int = 30
    online_basemap: bool = True
    basemap_url: str = "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
    basemap_attribution: str = "(c) OpenStreetMap contributors (c) CARTO"
    openrailwaymap_overlay: bool = False
    infer_paths: bool = True
    station_match_threshold: int = 82

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            return cls.from_dict(raw)
        return cls()

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        base = cls()
        allowed = {f.name: f.type for f in fields(cls)}
        for key, value in (raw or {}).items():
            if key not in allowed:
                continue
            current = getattr(base, key)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(current, str):
                value = str(value)[:500]
            setattr(base, key, value)
        base.max_upload_mb = max(1, min(base.max_upload_mb, 200))
        base.max_pdf_pages = max(1, min(base.max_pdf_pages, 200))
        base.station_match_threshold = max(60, min(base.station_match_threshold, 100))
        return base

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def to_dict(self) -> dict:
        return asdict(self)


class AppConfig:
    """Configuration courante (chemins + parametres), partagee par l'API et les taches de fond."""

    def __init__(self, data_dir: Path | None = None):
        self.paths = Paths(data_dir)
        self.paths.ensure()
        self._lock = threading.Lock()
        self._settings = Settings.load(self.paths.settings_file)
        self.tesseract_cmd = os.environ.get("TESSERACT_CMD", "tesseract")
        self.host = os.environ.get("RAILFINE_HOST", "127.0.0.1")
        self.port = int(os.environ.get("RAILFINE_PORT", "8000"))

    @property
    def settings(self) -> Settings:
        with self._lock:
            return Settings.from_dict(asdict(self._settings))

    def update_settings(self, patch: dict) -> Settings:
        with self._lock:
            merged = asdict(self._settings)
            merged.update(patch or {})
            self._settings = Settings.from_dict(merged)
            self._settings.save(self.paths.settings_file)
            return Settings.from_dict(asdict(self._settings))

    def reload_settings(self) -> None:
        with self._lock:
            self._settings = Settings.load(self.paths.settings_file)

    def secret(self) -> bytes:
        """Sel local servant a hacher les numeros de dossier (jamais stockes en clair)."""
        f = self.paths.secret_file
        if not f.exists():
            f.write_text(secrets.token_hex(32), encoding="utf-8")
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
        return f.read_text(encoding="utf-8").strip().encode()
