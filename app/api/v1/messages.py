from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from sqlalchemy.future import select
from app.db.database import get_db
from app.api.dependencies import get_current_user
from app.services import message_services
from app.services.minio_services import upload_file_to_minio
from app.models.message import Message
from app.models.channel import ChannelMember
from app.models.user import User
from app.schemas.message import MessageEditRequest
from app.core.websocket_manager import manager

# Front-end url'leri bozulmasın diye prefix aynı kalıyor (/channels/{channel_id}/messages)
router = APIRouter(prefix="/channels", tags=["Messages"])


@router.get("/{channel_id}/messages")
async def get_messages(
        channel_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Kanalın (veya DM odasının) geçmiş mesajlarını sayfalayarak getirir.
    Önce kullanıcının bu kanalda yetkisi olup olmadığı kontrol edilir.
    """
    # 1. Güvenlik Kontrolü: Bu adam bu kanala cidden üye mi? (Gizli DM'leri okumasın)
    stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    )
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Bu kanalın mesajlarını okuma yetkiniz yok.")

    return await message_services.get_channel_messages(
        db=db,
        channel_id=channel_id,
        limit=limit,
        offset=offset
    )


@router.post("/{channel_id}/messages/with-file")
async def send_message_with_file(
        channel_id: uuid.UUID,
        file: UploadFile = File(...),  # Yüklenen fiziksel dosya
        content: str | None = Form(None),  # Dosyanın yanındaki opsiyonel açıklama metni
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    Kanala dosya (resim/pdf vs) ve opsiyonel metin gönderir.
    Dosyayı MinIO'ya yükleyip, URL'sini PostgreSQL'e kaydeder.
    """
    # 1. Güvenlik Kontrolü: Bu adam bu kanala üye mi? (Yabancılar dosya atamasın)
    stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user.id
    )
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Bu kanala mesaj gönderme yetkiniz yok.")

    # 2. Dosyayı MinIO'ya Yükle ve URL'sini Al
    file_url = await upload_file_to_minio(file)

    # 3. Yeni Mesajı Veritabanına (PostgreSQL) Kaydet
    new_message = Message(
        channel_id=channel_id,
        sender_id=current_user.id,
        content=content if content is not None else "",  # Null hatasını engelleyen dokunuş
        file_url=file_url
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    # 4. SİHİRLİ DOKUNUŞ: Odadaki herkese anında bildir!
    message_payload = {
        "id": str(new_message.id),
        "sender_id": str(current_user.id),
        "content": new_message.content,
        "channel_id": str(channel_id),  # <--- OĞUZHAN'IN ROZET İÇİN BEKLEDİĞİ KRİTİK VERİ
        "room_id": str(channel_id),
        "file_url": new_message.file_url,
        "is_edited": new_message.is_edited,
        "created_at": new_message.created_at.isoformat(),
        "type": "new_message"
    }
    await manager.broadcast_to_channel(
        message=message_payload,
        channel_id=str(channel_id)
    )
    return new_message


@router.get("/{channel_id}/messages/search")
async def search_messages_in_channel(
        channel_id: uuid.UUID,
        q: str,  # Arama kelimesi
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Kanalın veya DM odasının içinde metin araması yapar."""
    return await message_services.search_channel_messages(
        db=db,
        channel_id=channel_id,
        search_query=q
    )


@router.put("/{channel_id}/messages/{message_id}")
async def edit_channel_message(
        channel_id: uuid.UUID,
        message_id: uuid.UUID,
        request: MessageEditRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Kullanıcının daha önceden attığı mesajın metnini düzenlemesini sağlar."""
    updated_message = await message_services.edit_message(
        db=db,
        message_id=message_id,
        user_id=current_user.id,
        new_content=request.content
    )

    # Odadaki herkese "mesaj güncellendi" sinyali fırlat
    await manager.broadcast_to_channel(
        channel_id=str(channel_id),
        message={
            "type": "message_edited",
            "message_id": str(message_id),
            "new_content": request.content
        }
    )
    return updated_message


@router.delete("/{channel_id}/messages/{message_id}")
async def delete_channel_message(
        channel_id: uuid.UUID,
        message_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Kullanıcının kendi mesajını odadan tamamen silmesini sağlar."""
    await message_services.delete_message(
        db=db,
        message_id=message_id,
        user_id=current_user.id
    )

    # Odadaki herkese "mesaj silindi" sinyali fırlat
    await manager.broadcast_to_channel(
        channel_id=str(channel_id),
        message={
            "type": "message_deleted",
            "message_id": str(message_id)
        }
    )
    return {"message": "Mesaj silindi"}