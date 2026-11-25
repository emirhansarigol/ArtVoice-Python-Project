import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from app.models.user import User
from app.models.channel import Channel, ChannelMember
from app.core.redis_client import redis_db
from datetime import datetime, timedelta, timezone


async def get_user_dms(current_user_id: uuid.UUID, db: AsyncSession):
    """SADECE DM (is_direct=True) ODALARINI GETİRİR VE İSİMLERİ GÜZELLEŞTİRİR"""
    stmt = select(Channel, ChannelMember.role).join(ChannelMember).where(
        ChannelMember.user_id == current_user_id,
        Channel.is_direct == True
    )
    result = await db.execute(stmt)
    dms_list = []

    for channel, user_role in result.all():
        display_name = channel.name

        # SİHİRLİ DOKUNUŞ: Kanaldaki "diğer" kişiyi bul (ID'si benim ID'm olmayan kişi)
        stmt_other = select(User).join(ChannelMember).where(
            ChannelMember.channel_id == channel.id,
            ChannelMember.user_id != current_user_id
        )
        res_other = await db.execute(stmt_other)
        other_user = res_other.scalar_one_or_none()

        if other_user:
            # Karşıdaki adamın adı varsa onu, yoksa emailini göster
            isim = f"{other_user.first_name or ''} {other_user.last_name or ''}".strip()
            display_name = isim if isim else other_user.email
        else:
            # Karşıda kimse yoksa (Yani kendisine mesaj atıyorsa)
            display_name = "Kendime Notlar"

        # Çağrı durumu DM'ler için de geçerli olabilir
        active_call_count = await redis_db.scard(f"call:{channel.id}")

        dms_list.append({
            "id": channel.id,
            "name": display_name,
            "description": channel.description,
            "is_direct": channel.is_direct,
            "created_at": channel.created_at,
            "role": user_role,
            "has_active_call": active_call_count > 0,
            "active_call_participants_count": active_call_count
        })

    return dms_list


async def get_or_create_dm(db: AsyncSession, current_user_id: uuid.UUID, target_user_id: uuid.UUID):
    is_self = (current_user_id == target_user_id)
    # user_ids sıraya dizilir ki A kişisi B'ye atarken de B kişisi A'ya atarken de aynı DM odası bulunsun
    user_ids = sorted([str(current_user_id), str(target_user_id)])
    dm_channel_name = f"dm_{user_ids[0]}_{user_ids[1]}"

    stmt = select(Channel).where(Channel.name == dm_channel_name, Channel.is_direct == True)
    result = await db.execute(stmt)
    dm_channel = result.scalar_one_or_none()

    if not dm_channel:
        # Daha önce konuşmamışlar, yeni DM kanalı oluştur
        dm_channel = Channel(
            name=dm_channel_name,
            description="Kendime Notlar" if is_self else "Direct Message",
            is_direct=True,
            owner_id=current_user_id
        )
        db.add(dm_channel)
        await db.flush()

        member1 = ChannelMember(channel_id=dm_channel.id, user_id=current_user_id, role="member",last_read_at=datetime.now(timezone.utc))
        db.add(member1)

        if not is_self:
            member2 = ChannelMember(channel_id=dm_channel.id, user_id=target_user_id, role="member",last_read_at=datetime.now(timezone.utc))
            db.add(member2)

        await db.commit()
        await db.refresh(dm_channel)

    # FRONTEND'E GİDECEK İSMİ GÜZELLEŞTİR
    display_name = "Kendime Notlar"
    if not is_self:
        stmt_target = select(User).where(User.id == target_user_id)
        res_target = await db.execute(stmt_target)
        target_user = res_target.scalar_one_or_none()
        if target_user:
            isim = f"{target_user.first_name or ''} {target_user.last_name or ''}".strip()
            display_name = isim if isim else target_user.email

    return {
        "id": dm_channel.id,
        "name": display_name,
        "description": dm_channel.description,
        "is_direct": dm_channel.is_direct,
        "created_at": dm_channel.created_at
    }


async def delete_dm_channel(channel_id: uuid.UUID, current_user_id: uuid.UUID, db: AsyncSession):
    """Sadece DM odalarını tamamen silmek için kullanılır."""
    # 1. Kanalı ve kullanıcının o DM'nin içinde olup olmadığını teyit et
    stmt = select(Channel).join(ChannelMember).where(
        Channel.id == channel_id,
        ChannelMember.user_id == current_user_id,
        Channel.is_direct == True
    )
    res = await db.execute(stmt)
    channel = res.scalar_one_or_none()

    if not channel:
        raise HTTPException(
            status_code=404,
            detail="DM odası bulunamadı, bu odaya ait değilsiniz veya bu bir DM değil."
        )

    # 2. Kanalı sil. (Veritabanındaki CASCADE kuralı sayesinde içindeki tüm mesajlar da otomatik uçar)
    await db.delete(channel)
    await db.commit()
    return {"message": "DM sohbeti ve içindeki tüm mesajlar kalıcı olarak silindi."}