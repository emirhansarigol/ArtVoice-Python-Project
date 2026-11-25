from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional

# Yeni mesaj atılırken frontend'den gelecek veri
class MessageCreate(BaseModel):
    content: str
    parent_id: Optional[UUID] = None # Eğer bu bir thread (yanıt) ise ana mesajın ID'si

# Mesaj geçmişini frontend'e çekerken kullanılacak format
class MessageResponse(BaseModel):
    id: UUID
    channel_id: UUID
    sender_id: UUID
    parent_id: Optional[UUID]
    content: str
    is_edited: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MessageEditRequest(BaseModel):
    content: str