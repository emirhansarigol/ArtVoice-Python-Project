from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from app.db.database import get_db
from app.api.dependencies import get_current_user
from app.schemas.channel import ChannelCreate, ChannelResponse, ChannelInvite, ChannelMemberResponse, ChannelMemberUpdate, ChannelUpdate
from app.services import channel_services
from app.models.user import User
from pydantic import BaseModel
from app.schemas.channel import MemberRoleUpdate
from app.core.websocket_manager import manager
from datetime import datetime, timezone
router = APIRouter(prefix="/channels", tags=["Channels"])

@router.post("/", response_model=ChannelResponse)
async def create_channel(
    request: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Yeni bir kanal oluşturur. Oluşturan kişiyi otomatik admin yapar."""
    return await channel_services.create_channel(
        name=request.name,
        description=request.description,
        current_user_id=current_user.id,
        db=db
    )

@router.get("/", response_model=list[ChannelResponse])
async def get_my_channels(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Kullanıcının üye olduğu NORMAL (Grup) kanalları listeler."""
    return await channel_services.get_user_channels(
        current_user_id=current_user.id,
        db=db
    )

@router.post("/{channel_id}/invite")
async def invite_to_channel(
    channel_id: uuid.UUID,
    request: ChannelInvite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Belirtilen maile kanala katılım için Magic Link gönderir (Sadece adminler kullanabilir)."""
    return await channel_services.invite_user_to_channel(
        email=request.email,
        first_name=request.first_name,
        last_name=request.last_name,
        channel_id=channel_id,
        inviter_id=current_user.id,
        db=db
    )

class AcceptInviteRequest(BaseModel):
    token: str

@router.post("/accept-invite")
async def accept_invite(
    request: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Kullanıcının mailine gelen davet token'ını okur.
    Kullanıcıyı kanala ekler ve doğrudan sisteme giriş yapması için Access Token döner.
    DİKKAT: Burada get_current_user YOK. Herkese açık bir kapı.
    """
    return await channel_services.accept_channel_invite(
        token=request.token,
        db=db
    )

@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    request: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Kanalın ismini veya açıklamasını günceller. (Sadece Admin)"""
    return await channel_services.update_channel_details(
        channel_id=channel_id,
        name=request.name,
        description=request.description,
        current_user_id=current_user.id,
        db=db
    )

@router.delete("/{channel_id}/members/{target_user_id}")
async def remove_member(
    channel_id: uuid.UUID,
    target_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Kanaldan bir kullanıcıyı çıkarır (Admin) veya kullanıcının kendisi kanaldan ayrılır (Leave)."""
    return await channel_services.remove_user_from_channel(
        channel_id=channel_id,
        target_user_id=target_user_id,
        current_user_id=current_user.id,
        db=db
    )

@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Kanalı tamamen siler. (Sadece Admin)"""
    return await channel_services.delete_channel_completely(
        channel_id=channel_id,
        current_user_id=current_user.id,
        db=db
    )

@router.get("/{channel_id}/members", response_model=list[ChannelMemberResponse])
async def get_members(
    channel_id: uuid.UUID,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Belirli bir kanalın içindeki tüm üyeleri ve rollerini getirir.
    'search' query parametresi verilirse isme/soyisme göre filtreler.
    """
    return await channel_services.get_channel_members(
        channel_id=channel_id,
        current_user_id=current_user.id,
        db=db,
        search_query=search
    )

@router.put("/{channel_id}/members/{target_user_id}")
async def update_channel_member(
    channel_id: uuid.UUID,
    target_user_id: uuid.UUID,
    request: ChannelMemberUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Kanal içindeki bir kullanıcının ad/soyad bilgisini günceller.
    Kural: Kullanıcı kendisini güncelleyebilir, Admin ise HERKESİ güncelleyebilir.
    """
    updated_user = await channel_services.update_member_profile(
        channel_id=channel_id,
        target_user_id=target_user_id,
        current_user_id=current_user.id,
        first_name=request.first_name,
        last_name=request.last_name,
        db=db
    )
    # Frontend için temiz bir sözlük dönüyoruz
    return {
        "id": updated_user.id,
        "email": updated_user.email,
        "first_name": updated_user.first_name,
        "last_name": updated_user.last_name
    }


from datetime import datetime, timezone


@router.post("/{channel_id}/read")
async def mark_channel_as_read(
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Kullanıcının odaya girdiğini ve tüm mesajları okuduğunu kaydeder."""
    return await channel_services.mark_channel_as_read(
        channel_id=channel_id,
        current_user_id=current_user.id,
        db=db
    )


# Şemayı ve WebSocket Manager'ı import etmeyi unutma!


@router.patch("/{channel_id}/members/{target_user_id}/role")
async def change_member_role(
        channel_id: uuid.UUID,
        target_user_id: uuid.UUID,
        payload: MemberRoleUpdate,  # FastAPI burada enum dışı bir şeyi anında reddedecek!
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # payload.role.value diyerek "project_manager" stringini alıyoruz
    updated_member = await channel_services.update_member_role(
        channel_id, target_user_id, payload.role.value, current_user.id, db
    )

    ws_payload = {
        "type": "member_role_updated",
        "user_id": str(target_user_id),
        "new_role": payload.role.value
    }
    await manager.broadcast_to_channel(ws_payload, str(channel_id))

    return {"message": f"Kullanıcının rolü başarıyla '{payload.role.value}' olarak güncellendi."}