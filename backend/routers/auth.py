import os
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Admin
from schemas import LoginRequest,TokenResponse
from auth import verify_password,create_token
router=APIRouter(prefix="/auth",tags=["auth"])
@router.post("/login",response_model=TokenResponse)
def login(body:LoginRequest,db:Session=Depends(get_db)):
    admin=db.query(Admin).filter(Admin.username==body.username).first()
    if not admin or not verify_password(body.password,admin.password_hash):
        raise HTTPException(status_code=401,detail="Invalid credentials")
    return TokenResponse(access_token=create_token(admin.username))
