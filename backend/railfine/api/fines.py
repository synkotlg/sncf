"""Amendes : saisie manuelle, validation des brouillons, correction, correspondances, suppression."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..user.service import DuplicateError, ValidationError
from . import rf

router = APIRouter(tags=["amendes"])


def _dup_response(exc: DuplicateError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "doublon potentiel", "duplicates": exc.duplicates})


def _invalid(exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "données invalides", "errors": exc.errors})


@router.get("/fines")
def list_fines(include_demo: bool = True, state=Depends(rf)):
    return {"fines": state.fines.store.list_fines(include_demo=include_demo)}


@router.get("/fines/{fine_id}")
def get_fine(fine_id: int, state=Depends(rf)):
    f = state.fines.store.get_fine(fine_id)
    if not f:
        raise HTTPException(404, "amende introuvable")
    return f


@router.post("/fines")
def create_fine(body: dict, force: bool = Query(False), state=Depends(rf)):
    try:
        return state.fines.create(body, force=force)
    except ValidationError as exc:
        return _invalid(exc)
    except DuplicateError as exc:
        return _dup_response(exc)


@router.put("/fines/{fine_id}")
def update_fine(fine_id: int, body: dict, force: bool = Query(False), state=Depends(rf)):
    try:
        return state.fines.update(fine_id, body, force=force)
    except KeyError:
        raise HTTPException(404, "amende introuvable")
    except ValidationError as exc:
        return _invalid(exc)
    except DuplicateError as exc:
        return _dup_response(exc)


@router.delete("/fines/{fine_id}")
def delete_fine(fine_id: int, state=Depends(rf)):
    if not state.fines.store.delete_fine(fine_id):
        raise HTTPException(404, "amende introuvable")
    return {"ok": True}


@router.post("/fines/{fine_id}/relocate")
def relocate(fine_id: int, state=Depends(rf)):
    f = state.fines.relocate(fine_id)
    if not f:
        raise HTTPException(404, "amende introuvable")
    return f


@router.post("/fines-relocate-all")
def relocate_all(state=Depends(rf)):
    return {"updated": state.fines.relocate_all()}


@router.post("/fines-check-duplicates")
def check_duplicates(body: dict, exclude_id: int | None = None, state=Depends(rf)):
    from ..user.service import clean_fine_payload

    try:
        values, case, _ = clean_fine_payload(body)
    except ValidationError as exc:
        return _invalid(exc)
    return {"duplicates": state.fines.store.find_duplicates(values, case, exclude_id=exclude_id)}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, state=Depends(rf)):
    d = state.fines.store.get_draft(draft_id)
    if not d:
        raise HTTPException(404, "brouillon introuvable")
    return d


@router.post("/drafts/{draft_id}/validate")
def validate_draft(draft_id: int, body: dict, force: bool = Query(False), state=Depends(rf)):
    try:
        return state.fines.validate_draft(draft_id, body, force=force)
    except KeyError:
        raise HTTPException(404, "brouillon introuvable")
    except ValidationError as exc:
        return _invalid(exc)
    except DuplicateError as exc:
        return _dup_response(exc)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, state=Depends(rf)):
    try:
        state.fines.discard_draft(draft_id)
    except KeyError:
        raise HTTPException(404, "brouillon introuvable")
    return {"ok": True}
