import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.message import Message
from sqlalchemy.future import select
from fastapi import HTTPException
from app.services.minio_services import delete_file_from_minio

async def save_message(db: AsyncSession, channel_id: uuid.UUID, sender_id: uuid.UUID, content: str):
    # parent_id ve is_edited şu an varsayılan (null ve False) olarak kalacak.
    new_message = Message(
        channel_id=channel_id,
        sender_id=sender_id,
        content=content
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)
    return new_message


async def get_channel_messages(db: AsyncSession, channel_id: uuid.UUID, limit: int = 50, offset: int = 0):
    # 1. En YENİ mesajları çekebilmek için DESC (azalan) sıralama yapıyoruz
    stmt = select(Message).where(
        Message.channel_id == channel_id
    ).order_by(Message.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    messages = result.scalars().all()

    # 2. Frontend'de chat akışı aşağıya doğru (eskiden yeniye) aksın diye
    # gelen son 50 mesajı ters çevirip (kronolojik yapıp) yolluyoruz
    return list(reversed(messages)) # veya messages[::-1]




async def search_channel_messages(db: AsyncSession, channel_id: uuid.UUID, search_query: str):
    """Kanal (veya DM) içindeki mesajlarda kelime araması yapar"""
    stmt = select(Message).where(
        Message.channel_id == channel_id,
        Message.content.ilike(f"%{search_query}%")  # İçinde bu kelime geçenler
    ).order_by(Message.created_at.desc()).limit(50)

    result = await db.execute(stmt)
    messages = result.scalars().all()

    return list(reversed(messages))


async def edit_message(db: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID, new_content: str):
    """Kullanıcının kendi mesajını düzenlemesini sağlar"""
    stmt = select(Message).where(Message.id == message_id)
    res = await db.execute(stmt)
    message = res.scalar_one_or_none()

    if not message:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı.")

    if message.sender_id != user_id:
        raise HTTPException(status_code=403, detail="Sadece kendi mesajınızı düzenleyebilirsiniz.")

    message.content = new_content
    message.is_edited = True

    await db.commit()
    await db.refresh(message)
    return message



async def delete_message(db: AsyncSession, message_id: uuid.UUID, user_id: uuid.UUID):

    """Kullanıcının kendi mesajını silmesini sağlar"""

    # Mesajı bul (eski kodun)
    stmt = select(Message).where(Message.id == message_id, Message.sender_id == user_id)
    res = await db.execute(stmt)
    message = res.scalar_one_or_none()

    if not message:
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı veya silme yetkiniz yok.")

    # SİHİRLİ DOKUNUŞ: Eğer mesajın içinde bir dosya varsa, MinIO'dan da sil!
    if message.file_url:
        await delete_file_from_minio(message.file_url)

    # Veritabanından sil (eski kodun)
    await db.delete(message)
    await db.commit()