import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import UploadLog
from auth import current_admin
from storage import upload_fileobj, make_key, delete_file

router = APIRouter(prefix="/uploads", tags=["uploads"])
MAX = int(os.getenv("MAX_FILE_SIZE_MB", "25")) * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",
    "image/png",
    "image/jpeg",
    "image/webp",
}
ALLOWED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".zip", ".png", ".jpg", ".jpeg", ".webp"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx"}


def _is_allowed(filename: str, content_type: str | None) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS and content_type in ALLOWED_CONTENT_TYPES


def _is_presentation(filename: str) -> bool:
    return Path(filename).suffix.lower() in PRESENTATION_EXTENSIONS


def _convert_presentation_to_pdf(data: bytes, filename: str) -> bytes:
    """Convert a PowerPoint file to PDF using LibreOffice/soffice."""
    soffice = os.getenv("LIBREOFFICE_BIN", "libreoffice")
    if shutil.which(soffice) is None:
        raise RuntimeError(
            "LibreOffice is required to publish PowerPoint files. "
            "Install LibreOffice or set LIBREOFFICE_BIN to the soffice executable."
        )

    with tempfile.TemporaryDirectory(prefix="tooltruth-ppt-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / Path(filename).name
        source.write_bytes(data)

        profile = tmp_path / "profile"
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        cmd = [
            soffice,
            "--headless",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(source),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown conversion error").strip()
            raise RuntimeError(f"PowerPoint conversion failed: {detail}")

        pdf_path = out_dir / f"{source.stem}.pdf"
        if not pdf_path.is_file():
            raise RuntimeError("LibreOffice completed without producing a PDF preview")
        return pdf_path.read_bytes()


@router.post("")
async def upload(file: UploadFile = File(...), _=Depends(current_admin), db: Session = Depends(get_db)):
    filename = Path(file.filename or "upload").name
    content_type = file.content_type or "application/octet-stream"

    if not _is_allowed(filename, content_type):
        raise HTTPException(400, "Unsupported file type")

    data = await file.read()
    if len(data) > MAX:
        raise HTTPException(413, f"File too large. Maximum size is {MAX // (1024 * 1024)} MB")

    key = make_key(filename)
    preview_key = None
    preview_content_type = None

    try:
        # Always keep the original upload.
        upload_fileobj(io.BytesIO(data), key, content_type)

        # PowerPoint files are converted to PDF so they can be displayed inside
        # the public website without requiring PowerPoint or a third-party viewer.
        if _is_presentation(filename):
            try:
                preview_data = _convert_presentation_to_pdf(data, filename)
            except RuntimeError as exc:
                # Conversion failed after the original file was already stored;
                # clean it up so it doesn't become an orphaned, unreferenced file.
                delete_file(key)
                raise HTTPException(503, str(exc)) from exc

            preview_key = f"{Path(key).with_suffix('')}-preview.pdf"
            upload_fileobj(io.BytesIO(preview_data), preview_key, "application/pdf")
            preview_content_type = "application/pdf"
        elif Path(filename).suffix.lower() == ".pdf" or content_type == "application/pdf":
            preview_key = key
            preview_content_type = "application/pdf"

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"File storage failed: {exc}") from exc

    row = UploadLog(
        filename=filename,
        s3_key=key,
        preview_key=preview_key,
        preview_content_type=preview_content_type,
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "filename": row.filename,
        "status": row.status,
        "presentation": _is_presentation(filename),
        "preview_ready": bool(preview_key),
    }
