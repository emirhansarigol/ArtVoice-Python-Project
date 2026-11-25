from pydantic import BaseModel, EmailStr, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional
import uuid
# Frontend'den giriş veya kayıt istenirken gelecek veri (Sadece mail yeterli)
class UserCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

# Frontend'e kullanıcı bilgisini döndürürken kullanacağımız format (Token'lar asla burada olmaz)
class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    avatar_url: Optional[str]
    is_active: bool
    settings: dict
    created_at: datetime

    # Bu ayar Pydantic'e şunu söyler: "Gelen veri bir sözlük (dict) değil de, SQLAlchemy veritabanı objesiyse, içinden verileri süzerek al."
    model_config = ConfigDict(from_attributes=True)


