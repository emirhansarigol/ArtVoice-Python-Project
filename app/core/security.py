from datetime import datetime, timedelta, timezone
from typing import Any, Union
from jose import jwt
import secrets
from app.core.config import settings

def create_access_token(subject: Union[str, Any]) -> str:
    """
    Kullanıcının API'ye (mesaj atma, okuma vb.) erişirken kullanacağı kısa ömürlü token.
    'subject' genellikle kullanıcının UUID'sidir.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "access"
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: Union[str, Any]) -> str:
    """
    Kullanıcı her bilgisayarı açtığında yeniden giriş yapmasın diye
    arka planda yeni bir access_token almak için kullanılan uzun ömürlü token.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh"
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def generate_magic_token() -> str:
    """
    E-postaya gönderilecek linkin içine yerleştirilecek,
    veritabanındaki Invitations tablosuna yazılacak kırılmaz rastgele metin.
    Örnek çıktı: 'a-bC1dE2fG3hI4jK5lM6nO7pQ8rS9tU0vW_xY-zA'
    """
    return secrets.token_urlsafe(32)


def verify_token(token: str) -> dict:
    """
    Gelen JWT token'ın geçerli olup olmadığını (süresi bitmiş mi, şifre doğru mu) kontrol eder.
    """
    # jwt.decode işlemi eğer token bozuksa veya süresi geçmişse otomatik hata fırlatır
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    return payload