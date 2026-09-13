import os
from dotenv import load_dotenv
load_dotenv()
from database import init_db,SessionLocal
from models import Admin
from auth import hash_password
init_db()
db=SessionLocal()
username=os.getenv("ADMIN_USERNAME","admin")
password=os.getenv("ADMIN_PASSWORD")
if not password:
    raise RuntimeError("ADMIN_PASSWORD environment variable must be set before seeding the admin account.")
if not db.query(Admin).filter(Admin.username==username).first():
    db.add(Admin(username=username,password_hash=hash_password(password)));db.commit()
    print(f"Created admin: {username}")
else: print("Admin already exists.")
db.close()
