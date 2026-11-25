from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt

from app.db.database import get_db
from app.core import security
from app.core.config import settings
from app.models.user import User

# Eski OAuth2PasswordBearer yerine doğrudan HTTPBearer kullanıyoruz
security_scheme = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
                           db: AsyncSession = Depends(get_db)):
    """
    Gelen token'ı çözer, geçerliyse veritabanından kullanıcıyı bulup döndürür.
    Geçersizse 401 hatası verip kapıdan kovar.
    """
    # Token'ı artık credentials.credentials içinden alıyoruz
    token = credentials.credentials

    try:
        payload = security.verify_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Geçersiz token tipi.")
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token.")

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı veya pasif.")

    return user