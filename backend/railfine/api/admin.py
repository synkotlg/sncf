"""Paramètres, état du système, sauvegarde/restauration, données d'exemple, purge."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from ..demo import load_demo_fines, write_sample_documents
from ..ingest.textextract import tesseract_status
from ..user.backup import RestoreError, create_backup, purge_all, restore_backup
from ..user.service import FineService
from . import rf

router = APIRouter(tags=["administration"])


@router.get("/health")
def health(state=Depends(rf)):
    return {"ok": True, "reference_version": state.reference.version()}


@router.get("/system")
def system(state=Depends(rf)):
    cfg = state.cfg
    return {
        "tesseract": tesseract_status(cfg.tesseract_cmd),
        "data_dir": str(cfg.paths.data),
        "reference": state.reference.counts(),
        "user": state.fines.store.counts(),
        "host": cfg.host,
    }


@router.get("/settings")
def get_settings(state=Depends(rf)):
    return state.cfg.settings.to_dict()


@router.put("/settings")
def put_settings(body: dict, state=Depends(rf)):
    s = state.cfg.update_settings(body)
    return s.to_dict()


@router.get("/backup")
def backup(state=Depends(rf)):
    data = create_backup(state.cfg.paths)
    name = f"railfine-sauvegarde-{time.strftime('%Y%m%d-%H%M')}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/restore")
async def restore(file: UploadFile = File(...), state=Depends(rf)):
    data = await file.read(4_000_000_001)
    try:
        res = restore_backup(state.cfg.paths, data)
    except RestoreError as exc:
        raise HTTPException(422, str(exc))
    # rechargement des services sur les données restaurées
    state.cfg.reload_settings()
    state.fines = FineService(state.cfg)
    state.processor.store = state.fines.store
    state.fines.relocate_all()
    return {"ok": True, **res}


@router.post("/demo")
def demo_load(state=Depends(rf)):
    if state.fines.store.counts()["demo_fines"]:
        raise HTTPException(409, "les données d'exemple sont déjà chargées")
    n = load_demo_fines(state.fines)
    return {"created": n}


@router.delete("/demo")
def demo_delete(state=Depends(rf)):
    res = state.fines.store.delete_demo()
    for name in res.pop("stored_names"):
        state.processor.path_for(name).unlink(missing_ok=True)
    return res


@router.post("/demo/documents")
def demo_documents(state=Depends(rf)):
    """Génère des documents fictifs et les importe comme des documents ordinaires (marqués exemple)."""
    folder = state.cfg.paths.exports_dir / "exemples-fictifs"
    out = []
    for p in write_sample_documents(folder):
        res = state.processor.ingest(p.read_bytes(), p.name, is_demo=True)
        out.append({"file": p.name, **res})
    return {"results": out}


@router.delete("/user-data")
def purge(confirm: str = "", state=Depends(rf)):
    if confirm != "SUPPRIMER":
        raise HTTPException(400, "confirmation requise : confirm=SUPPRIMER")
    purge_all(state.cfg.paths)
    state.fines = FineService(state.cfg)
    state.processor.store = state.fines.store
    return {"ok": True}
