from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
import uuid
from app.models.user import User
from app.models.invitation import Invitation
from app.core import security
from app.core.rabbitmq import publish_message
from jose import JWTError

async def request_magic_link(email: str, db: AsyncSession) -> dict:
    # 1. Benzersiz bir token üret
    raw_token = security.generate_magic_token()

    # 2. Token'ın geçerlilik süresini belirle (15 dakika)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)

    # 3. Veritabanına kaydedilecek davetiye objesini oluştur
    new_invitation = Invitation(
        email=email,
        token=raw_token,
        status="pending",
        expires_at=expires
    )

    db.add(new_invitation)
    await db.commit()


    mail_icerigi = {
        "to_email": email,
        "subject": "ArtVoice Giriş Linki",
        "body": f"Sisteme giriş yapmak için bu linke tıklayın:\nhttp://localhost:5173/verify?token={raw_token}\n\nBu link 15 dakika geçerlidir."
    }

    # Mesajı kuyruğa fırlat
    await publish_message(queue_name="email_queue", message_body=mail_icerigi)

    return {"message": f"{email} adresine giriş linki kuyruğa eklendi."}

async def verify_magic_link(token: str, db: AsyncSession) -> dict:
    # 1. Token'ı veritabanında bul ve durumunun "pending" (bekliyor) olduğundan emin ol
    stmt = select(Invitation).where(Invitation.token == token, Invitation.status == "pending")
    result = await db.execute(stmt)
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz veya kullanılmış link.")

    # 2. Token'ın süresi dolmuş mu kontrol et
    if invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = "expired"
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bu linkin süresi dolmuş.")

    # 3. Token geçerli Durumunu kullanıldı yap
    invitation.status = "used"

    # 4. Kullanıcı daha önce kayıt olmuş mu kontrol et
    stmt_user = select(User).where(User.email == invitation.email)
    result_user = await db.execute(stmt_user)
    user = result_user.scalar_one_or_none()

    # 5. Kullanıcı yoksa yeni kullanıcı oluştur
    if not user:
        user = User(email=invitation.email, is_active=True)
        db.add(user)
    else:
        # Varsa ve pasifse aktif hale getir
        user.is_active = True

    await db.commit()
    await db.refresh(user)  # Yeni oluşan kullanıcının UUID'sini almak için yeniliyoruz

    # 6. JWT anahtarlarını üret ve teslim et
    access_token = security.create_access_token(subject=user.id)
    refresh_token = security.create_refresh_token(subject=user.id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": str(user.id)
    }


async def refresh_session(refresh_token: str, db: AsyncSession) -> dict:
    try:
        # 1. Gelen Refresh Token geçerli mi kontrol et
        payload = security.verify_token(refresh_token)

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Geçersiz token tipi.")

        # 2. String olarak gelen ID'yi UUID objesine çevir (KRİTİK DÜZELTME)
        user_id_str = payload.get("sub")
        user_id = uuid.UUID(user_id_str)

        # 3. Kullanıcı veritabanında hala duruyor mu kontrol et
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı veya pasif.")

        # 4. Yeni bir Access Token üret
        new_access_token = security.create_access_token(subject=str(user.id))

        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }

    except HTTPException:
        raise
    except JWTError:
        # Sadece token şifresi/süresi bozuksa bu hatayı ver
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum süresi doldu, tekrar giriş yapın.")