"""Application FastAPI : API locale + interface web compilée (frontend/dist)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import FRONTEND_DIST, AppConfig
from .ingest.jobs import DocumentProcessor
from .reference.store import ReferenceStore
from .reference.tiles import TileRenderer
from .user.service import FineService

log = logging.getLogger("railfine")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-railfine-request"


class AppState:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.reference = ReferenceStore(cfg.paths.reference_db)
        self.tiles = TileRenderer(cfg.paths.reference_db)
        self.fines = FineService(cfg)
        self.processor = DocumentProcessor(cfg, self.fines.store)
        self.update_job: dict = {"running": False, "log": [], "report": None}


def _origin(url: str) -> str | None:
    try:
        p = urlparse(url.replace("{s}", "a").replace("{z}", "0").replace("{x}", "0").replace("{y}", "0"))
    except ValueError:
        return None
    if p.scheme in ("https", "http") and p.netloc:
        host = p.netloc
        # sous-domaines a/b/c/d des serveurs de tuiles
        parts = host.split(".")
        if len(parts) > 2 and len(parts[0]) == 1:
            host = "*." + ".".join(parts[1:])
        return f"{p.scheme}://{host}"
    return None


def content_security_policy(cfg: AppConfig) -> str:
    s = cfg.settings
    tiles = []
    if s.online_basemap:
        o = _origin(s.basemap_url)
        if o:
            tiles.append(o)
            if o.startswith("https://") and not o.startswith("https://*."):
                tiles.append("https://*." + o[len("https://"):])
    if s.openrailwaymap_overlay:
        tiles.append("https://*.tiles.openrailwaymap.org")
    t = " ".join(tiles)
    return (
        "default-src 'self'; "
        f"img-src 'self' data: blob: {t}; "
        f"connect-src 'self' {t}; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "worker-src 'self' blob:; "
        "child-src 'self' blob:; "
        "font-src 'self' data:; "
        "frame-src 'self'; "
        "object-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'none'; form-action 'self'"
    )


class SecurityMiddleware(BaseHTTPMiddleware):
    """- refuse les noms d'hôte inattendus (protection contre le DNS rebinding) ;
    - exige un en-tête personnalisé sur les requêtes modifiantes (protection CSRF : un site tiers
      ne peut pas l'ajouter sans pré-vérification CORS, que l'application n'autorise pas) ;
    - ajoute des en-têtes de sécurité."""

    def __init__(self, app, cfg: AppConfig, allowed_hosts: set[str]):
        super().__init__(app)
        self.cfg = cfg
        self.allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            return JSONResponse({"detail": "hôte non autorisé"}, status_code=400)
        if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "en-tête de requête manquant"}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", content_security_policy(self.cfg))
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response


def create_app(cfg: AppConfig | None = None) -> FastAPI:
    cfg = cfg or AppConfig()
    state = AppState(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        state.processor.shutdown()

    app = FastAPI(title="RailFine Analytics", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.rf = state
    extra = {h.strip().lower() for h in os.environ.get("RAILFINE_ALLOWED_HOSTS", "").split(",") if h.strip()}
    allowed = {"127.0.0.1", "localhost", "::1", "testserver"} | extra
    if os.environ.get("RAILFINE_ALLOW_ANY_HOST") == "1":
        allowed = set()
    app.add_middleware(SecurityMiddleware, cfg=cfg, allowed_hosts=allowed)

    from .api import admin, documents, fines, reference, stats

    for module in (reference, documents, fines, stats, admin):
        app.include_router(module.router, prefix="/api")

    dist = FRONTEND_DIST

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "introuvable"}, status_code=404)
        if dist.exists():
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{full_path}" else {}
                return FileResponse(candidate, headers=headers)
            if full_path.startswith(("fonts/", "assets/")) or full_path.endswith((".pbf", ".js", ".css", ".png", ".svg")):
                return JSONResponse({"detail": "introuvable"}, status_code=404)
            index = dist / "index.html"
            if index.exists():
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Interface non compilée : lancez `npm run build` dans frontend/ (voir README)."},
                            status_code=503)

    return app


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = AppConfig()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")
