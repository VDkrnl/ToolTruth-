from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import UploadLog,Version
from schemas import PublishRequest
from auth import current_admin
router=APIRouter(tags=["publish"])
@router.post("/publish")
def publish(body:PublishRequest,db:Session=Depends(get_db),_=Depends(current_admin)):
    upload=db.get(UploadLog,body.upload_id)
    if not upload: raise HTTPException(404,"Upload not found")
    existing=db.query(Version).filter(Version.upload_id==body.upload_id).first()
    if existing: raise HTTPException(409,"This upload has already been published")
    db.query(Version).filter(Version.slug==body.slug).update({"is_latest":False})
    row=Version(upload_id=body.upload_id,slug=body.slug,title=body.title,version=body.version,date=body.date,authors=body.authors,summary=body.summary,is_latest=True)
    upload.status="published";db.add(row);db.commit();db.refresh(row)
    return {
        "id": row.id,
        "title": row.title,
        "version": row.version,
        "date": row.date,
        "slug": row.slug,
        "summary": row.summary,
        "authors": row.authors,
        "filename": upload.filename,
        "preview_ready": bool(upload.preview_key),
    }
