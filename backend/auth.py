import os
from datetime import datetime,timedelta,timezone
from jose import jwt,JWTError
from passlib.context import CryptContext
from fastapi import Depends,HTTPException,status
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import Admin
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")
security=HTTPBearer()
SECRET=os.getenv("JWT_SECRET")
if not SECRET or SECRET=="CHANGE_ME_BEFORE_PRODUCTION":
    raise RuntimeError("JWT_SECRET environment variable must be set to a real secret before starting the server.")
ALGO="HS256"
def hash_password(value): return pwd.hash(value)
def verify_password(value,hashed): return pwd.verify(value,hashed)
def create_token(subject):
    exp=datetime.now(timezone.utc)+timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES","30")))
    return jwt.encode({"sub":subject,"exp":exp},SECRET,algorithm=ALGO)
def current_admin(creds:HTTPAuthorizationCredentials=Depends(security),db:Session=Depends(get_db)):
    try: payload=jwt.decode(creds.credentials,SECRET,algorithms=[ALGO]); username=payload.get("sub")
    except JWTError: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Invalid or expired token")
    admin=db.query(Admin).filter(Admin.username==username).first()
    if not admin: raise HTTPException(status_code=401,detail="Admin not found")
    return admin
