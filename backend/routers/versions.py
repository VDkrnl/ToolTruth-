from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Version, UploadLog
from storage import presigned_url, delete_file
from auth import current_admin

router = APIRouter(tags=["versions"])


def out(v, u=None):
    return {
        "id": v.id,
        "slug": v.slug,
        "title": v.title,
        "version": v.version,
        "date": v.date,
        "authors": v.authors,
        "summary": v.summary,
        "is_latest": v.is_latest,
        "filename": u.filename if u else None,
        "content_type": u.content_type if u else None,
        "preview_ready": bool(u and u.preview_key),
    }


@router.get("/versions")
def versions(db: Session = Depends(get_db)):
    rows = db.query(Version).order_by(Version.published_at.desc()).all()
    return [out(v, db.get(UploadLog, v.upload_id)) for v in rows]


@router.get("/versions/{slug}")
def versions_slug(slug: str, db: Session = Depends(get_db)):
    rows = db.query(Version).filter(Version.slug == slug).order_by(Version.published_at.desc()).all()
    return [out(v, db.get(UploadLog, v.upload_id)) for v in rows]


@router.get("/files/{version_id}")
def file_url(version_id: int, db: Session = Depends(get_db)):
    v = db.get(Version, version_id)
    if not v:
        raise HTTPException(404, "Version not found")

    u = db.get(UploadLog, v.upload_id)
    if not u:
        raise HTTPException(404, "Uploaded file not found")
    if not u.preview_key:
        raise HTTPException(415, "This deliverable does not have an in-browser preview")

    return {
        "url": presigned_url(u.preview_key),
        "filename": u.filename,
        "content_type": u.preview_content_type or u.content_type,
        "version_id": v.id,
    }


@router.delete("/versions/{version_id}")
def delete_version(version_id: int, db: Session = Depends(get_db), _=Depends(current_admin)):
    v = db.get(Version, version_id)

    if not v:
        raise HTTPException(404, "Version not found")

    u = db.get(UploadLog, v.upload_id)

    other_versions = db.query(Version).filter(
        Version.upload_id == v.upload_id, Version.id != v.id
    ).count()
    upload_still_referenced = other_versions > 0

    if v.is_latest:
        sibling = (
            db.query(Version)
            .filter(Version.slug == v.slug, Version.id != v.id)
            .order_by(Version.published_at.desc())
            .first()
        )
        if sibling:
            sibling.is_latest = True

    if u and not upload_still_referenced:
        # Delete original PPT/PPTX
        if u.s3_key:
            delete_file(u.s3_key)

        # Delete generated PDF preview
        if u.preview_key:
            delete_file(u.preview_key)

        # Delete database record
        db.delete(u)

    db.delete(v)
    db.commit()

    return {
        "message": "Version deleted successfully",
        "version_id": version_id,
    }
