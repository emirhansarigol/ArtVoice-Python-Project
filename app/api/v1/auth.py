from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.invitation import MagicLinkRequest, VerifyTokenRequest, RefreshTokenRequest
from app.services import auth_services


router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/request-magic-link")
async def request_magic_link(request: MagicLinkRequest, db: AsyncSession = Depends(get_db)):
    """
    Kullanıcının e-posta adresine tek kullanımlık giriş/kayıt linki gönderir.
    """
    return await auth_services.request_magic_link(email=request.email, db=db)


@router.post("/verify-magic-link")
async def verify_magic_link(request: VerifyTokenRequest, db: AsyncSession = Depends(get_db)):
    """
    E-postadaki linkten gelen token'ı doğrular ve kullanıcıya oturum anahtarlarını (JWT) verir.
    """
    return await auth_services.verify_magic_link(token=request.token, db=db)


@router.post("/refresh")
async def refresh_session(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """
    Süresi dolmuş Access Token'ı, geçerli bir Refresh Token ile yeniler.
    """
    return await auth_services.refresh_session(refresh_token=request.refresh_token, db=db)