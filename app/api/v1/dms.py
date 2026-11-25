from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from app.db.database import get_db
from app.api.dependencies import get_current_user
from app.schemas.channel import ChannelResponse
from app.services import dm_services
from app.models.user import User
from app.core.websocket_manager import manager
from pydantic import BaseModel


class DMCreateRequest(BaseModel):
    target_user_id: uuid.UUID


# Front-end url'leri bozulmasın diye prefix aynı kalıyor (/channels/dms)
router = APIRouter(prefix="/channels", tags=["Direct Messages"])


@router.get("/dms", response_model=list[ChannelResponse])
async def get_my_dms(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """Kullanıcının daha önce konuştuğu DM (Özel Mesaj) odalarını listeler."""
    return await dm_services.get_user_dms(
        current_user_id=current_user.id,
        db=db
    )


@router.post("/dm")
async def start_direct_message(
        request: DMCreateRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Hedef kullanıcıyla yeni bir DM kanalı oluşturur veya var olanı getirir."""
    return await dm_services.get_or_create_dm(
        db=db,
        current_user_id=current_user.id,
        target_user_id=request.target_user_id
    )


@router.delete("/dms/{channel_id}")
async def delete_dm_conversation(
        channel_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Bir DM sohbetini tüm geçmişiyle birlikte kalıcı olarak siler."""
    await dm_services.delete_dm_channel(
        channel_id=channel_id,
        current_user_id=current_user.id,
        db=db
    )

    # SİHİRLİ DOKUNUŞ: Karşı tarafın ekranında da sohbet anında kaybolsun diye sinyal fırlat
    await manager.broadcast_to_channel(
        channel_id=str(channel_id),
        message={
            "type": "channel_deleted",
            "channel_id": str(channel_id)
        }
    )
    return {"message": "DM sohbeti başarıyla silindi"}