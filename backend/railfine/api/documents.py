"""Importation de documents (multi-fichiers), suivi du traitement, consultation et suppression."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..ingest.filetypes import RejectedFile
from . import rf

router = APIRouter(tags=["documents"])

MAX_FILES_PER_UPLOAD = 50


@router.post("/documents")
async def upload_documents(files: list[UploadFile] = File(...), state=Depends(rf)):
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(413, f"{MAX_FILES_PER_UPLOAD} fichiers maximum par envoi")
    limit = state.cfg.settings.max_upload_mb * 1024 * 1024
    results = []
    for f in files:
        data = await f.read(limit + 1)
        try:
            res = state.processor.ingest(data, f.filename)
            results.append({"file": f.filename, "ok": True, **res})
        except RejectedFile as exc:
            results.append({"file": f.filename, "ok": False, "error": str(exc)})
        finally:
            await f.close()
    return {"results": results}


@router.get("/documents")
def list_documents(state=Depends(rf)):
    return {"documents": state.fines.store.list_documents()}


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, with_text: bool = False, state=Depends(rf)):
    doc = state.fines.store.get_document(doc_id, with_text=with_text)
    if not doc:
        raise HTTPException(404, "document introuvable")
    doc.pop("stored_name", None)
    doc.pop("sha256", None)
    return doc


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, download: bool = False, state=Depends(rf)):
    doc = state.fines.store.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "document introuvable")
    path = state.processor.path_for(doc["stored_name"])
    if not path.exists():
        raise HTTPException(410, "fichier supprimé du disque")
    ext = doc["stored_name"].rsplit(".", 1)[-1]
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": f'{disposition}; filename="document-{doc_id}.{ext}"',
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; object-src 'self'; frame-ancestors 'self'",
    }
    return FileResponse(path, media_type=doc["mime"], headers=headers)


@router.post("/documents/{doc_id}/reprocess")
def reprocess(doc_id: int, state=Depends(rf)):
    if not state.fines.store.get_document(doc_id):
        raise HTTPException(404, "document introuvable")
    state.processor.reprocess(doc_id)
    return {"ok": True}


@router.post("/documents/{doc_id}/drafts")
def add_manual_draft(doc_id: int, state=Depends(rf)):
    """Ajoute un brouillon vide (amende supplémentaire présente dans le document)."""
    if not state.fines.store.get_document(doc_id):
        raise HTTPException(404, "document introuvable")
    draft_id = state.fines.store.add_draft(doc_id, {})
    return state.fines.store.get_draft(draft_id)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, delete_fines: bool = Query(False), state=Depends(rf)):
    res = state.fines.store.delete_document(doc_id, delete_fines)
    if res is None:
        raise HTTPException(404, "document introuvable")
    path = state.processor.path_for(res["stored_name"])
    path.unlink(missing_ok=True)
    return {"ok": True, "fines_deleted": res["fines_deleted"]}
