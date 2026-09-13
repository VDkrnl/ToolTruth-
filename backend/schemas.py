from pydantic import BaseModel, Field
class LoginRequest(BaseModel):
    username:str
    password:str
class PublishRequest(BaseModel):
    upload_id:int
    slug:str="planning"
    title:str
    version:str
    date:str
    authors:str
    summary:str
class TokenResponse(BaseModel):
    access_token:str
    token_type:str="bearer"
