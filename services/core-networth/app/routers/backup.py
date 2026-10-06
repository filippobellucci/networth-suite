from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from .. import backup
from ..config import MAX_BACKUP_UPLOAD_SIZE_BYTES

router = APIRouter()


# ---------------------------------------------------------------- Backup / Restore
@router.get("/backup/export")
def backup_export():
    try:
        data = backup.export_db_bytes()
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="networth.db"'},
    )


@router.get("/backup/stats")
def backup_stats():
    return backup.get_stats()


async def _read_bounded(file: UploadFile) -> bytes:
    """Reads the upload in chunks and gives up as soon as it exceeds the
    limit, so an oversized file is never held in memory whole."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_BACKUP_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                413, f"File too large -- max is {MAX_BACKUP_UPLOAD_SIZE_BYTES} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/backup/preview")
async def backup_preview(file: UploadFile = File(...)):
    try:
        return backup.preview_uploaded_db(await _read_bounded(file))
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))


@router.post("/backup/restore")
async def backup_restore(file: UploadFile = File(...)):
    try:
        return backup.restore_db(await _read_bounded(file))
    except backup.InvalidBackupError as e:
        raise HTTPException(400, str(e))
