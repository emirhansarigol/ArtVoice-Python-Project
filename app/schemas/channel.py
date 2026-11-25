from pydantic import BaseModel, EmailStr, ConfigDict
import uuid
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

# ENUM SINIFI: Artık roller sadece bu üçü olabilir! (Başka bir şey yazılamaz)
class RoleEnum(str, Enum):
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"

# ŞEMAYI GÜNCELLE: str yerine RoleEnum kullanıyoruz
class MemberRoleUpdate(BaseModel):
    role: RoleEnum
# 1. Yeni kanal oluştururken frontend'den beklediğimiz veriler
class ChannelCreate(BaseModel):
    name: str
    description: str | None = None

# 2. Kanala birini davet ederken beklediğimiz veri
class ChannelInvite(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None

# 3. Bizim frontend'e döndüreceğimiz kanal verisi
class ChannelResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    role:str | None= None
    unread_message_count: int = 0
    # SQLAlchemy modellerini doğrudan okuyabilmesi için bu ayar şart
    model_config = ConfigDict(from_attributes=True)

class ChannelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class ChannelMemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str

# channel.py dosyasının içine ekle:
class ChannelMemberUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None


class MemberRoleUpdate(BaseModel):
    role: str