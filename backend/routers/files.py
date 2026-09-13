import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])
LOCAL_ROOT = Path(__file__).resolve().parent.parent / "uploads"


@router.get("/files/serve/{path:path}")
def serve_local_file(path: str):
    """Serve files from local storage during development only."""
    if os.getenv("S3_BUCKET"):
        raise HTTPException(status_code=404, detail="Local file serving is disabled in S3 mode")

    file_path = (LOCAL_ROOT / path).resolve()
    root = LOCAL_ROOT.resolve()
    if not str(file_path).startswith(str(root) + os.sep) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(file_path))
