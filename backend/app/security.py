import os, hashlib, secrets, hmac, jwt
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import Session, User
SECRET=os.getenv('JWT_SECRET','local-demo-only-change-this-secret-123456789')
if os.getenv('APP_ENV')=='production' and (len(SECRET)<32 or SECRET.startswith('local-demo')): raise RuntimeError('Set a strong JWT_SECRET')

def hash_password(password):
    salt=secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
def verify_password(password,stored):
    salt,digest=stored.split(':')
    return hmac.compare_digest(digest,hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex())
def token(user):
    return jwt.encode({'sub':str(user.id),'exp':datetime.now(timezone.utc)+timedelta(hours=8),'iss':'mediassist'},SECRET,algorithm='HS256')
def db():
    with Session() as s: yield s
bearer=HTTPBearer(auto_error=False)
def current(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),s=Depends(db)):
    try:
        claims=jwt.decode(credentials.credentials,SECRET,algorithms=['HS256'],issuer='mediassist',options={'require':['exp','sub','iss']})
        u=s.get(User,int(claims['sub']))
        if u: return u
    except (jwt.PyJWTError,AttributeError,ValueError): pass
    raise HTTPException(401,'Authentication required')
def require(u,*roles):
    if u.role not in roles or (u.role=='doctor' and not u.verified): raise HTTPException(403,'Access denied')
