from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from backend import models
from backend import schemas
from backend.dependencies import get_db, get_current_user
from backend.services.csv_parser import parse_csv, detect_format
from backend.services.import_service import build_preview, run_import

router = APIRouter(prefix="/import", tags=["import"])


def _detect_and_parse(content: bytes, filename: str) -> tuple[list, models.ImportFormat]:
    """Parse file content and return (parsed_rows, format). Detects OFX/QFX by extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("ofx", "qfx"):
        from backend.services.ofx_parser import parse_ofx
        return parse_ofx(content), models.ImportFormat.ofx
    import csv, io
    text = content.decode("utf-8-sig", errors="replace")
    headers = list(csv.DictReader(io.StringIO(text)).fieldnames or [])
    return parse_csv(content), detect_format(headers)


@router.post("/preview", response_model=schemas.ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    account_id: Optional[int] = Form(None),
    card_id: Optional[int] = Form(None),
    skip_categorization: bool = Form(False),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not account_id and not card_id:
        raise HTTPException(status_code=400, detail="Provide either account_id or card_id")

    content = await file.read()
    try:
        parsed_rows, fmt = _detect_and_parse(content, file.filename or "")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {e}")

    if not parsed_rows:
        raise HTTPException(status_code=422, detail="No valid rows found in file")

    preview_rows = build_preview(db, user, parsed_rows, skip_categorization=skip_categorization)
    categorized = sum(1 for r in preview_rows if not r.needs_review)

    return schemas.ImportPreviewResponse(
        format=fmt,
        rows=preview_rows,
        stats=schemas.ImportPreviewStats(
            total=len(preview_rows),
            categorized=categorized,
            needs_review=len(preview_rows) - categorized,
        ),
    )


@router.post("/confirm", response_model=schemas.ImportConfirmResponse)
def confirm_import(
    body: schemas.ImportConfirmRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not body.account_id and not body.card_id:
        raise HTTPException(status_code=400, detail="Provide either account_id or card_id")

    return run_import(db, user, body.rows, body.account_id, body.card_id)
