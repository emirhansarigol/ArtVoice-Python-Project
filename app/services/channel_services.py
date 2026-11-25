import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from fastapi import HTTPException
from app.models.user import User
from app.models.invitation import Invitation
from app.core import security
from app.core.rabbitmq import publish_message
from app.core.redis_client import redis_db, is_user_online
from app.models.channel import Channel, ChannelMember
from app.models.message import Message

def normalize_search_text(text: str) -> str:
    """Kullanıcıdan gelen arama metnindeki Türkçe karakterleri İngilizce tabana çeker."""
    if not text: return ""
    text = text.replace("İ", "i").replace("I", "ı").lower()
    tr_map = str.maketrans("ıüşöçğ", "iusocg")
    return text.translate(tr_map)

def sql_normalize(column):
    """PostgreSQL'deki sütunu anlık olarak İngilizce tabana çekerek kıyaslamaya hazırlar."""
    return func.translate(func.lower(column), 'ıüşöçğ', 'iusocg')

async def create_channel(name: str, description: str, current_user_id: uuid.UUID, db: AsyncSession):
    # 1. Yeni kanalı oluştur ve KURUCUYU (Owner) kaydet
    new_channel = Channel(
        name=name,
        description=description,
        owner_id=current_user_id  # <--- İŞTE KRİTİK ZIRH BURASI
    )
    db.add(new_channel)

    # Kanal veritabanına yazılmadan (ID'si oluşmadan) o ID'yi alamayız.
    await db.flush()

    # 2. Kanalı kuran kişiyi o kanala "admin" olarak ekle
    channel_member = ChannelMember(
        user_id=current_user_id,
        channel_id=new_channel.id,
        role="admin",
        last_read_at=datetime.now(timezone.utc)
    )
    db.add(channel_member)

    # Her şeyi güvenlice kaydet
    await db.commit()
    await db.refresh(new_channel)

    return new_channel


async def get_user_channels(current_user_id: uuid.UUID, db: AsyncSession):
    """SADECE GRUP (is_direct=False) KANALLARINI GETİRİR"""

    # 1. SENİOR DOKUNUŞU: last_read_at değerini en baştaki ana sorguya ekledik!
    stmt = select(Channel, ChannelMember.role, ChannelMember.last_read_at).join(ChannelMember).where(
        ChannelMember.user_id == current_user_id,
        Channel.is_direct == False
    )
    result = await db.execute(stmt)
    channels_with_roles = []

    # Artık 3 değer birden geliyor: channel, user_role, last_read_time
    for channel, user_role, last_read_time in result.all():

        # Redis'te bu kanal için bir çağrı odası var mı?
        active_call_count = await redis_db.scard(f"call:{channel.id}")

        # 2. Döngü içindeki o gereksiz "stmt_member" sorgusunu SİLDİK! (DB rahatladı)

        # 3. Mesajlar tablosuna sor: "Bu kanalda, bu tarihten SONRA atılmış kaç mesaj var?"
        unread_count = 0
        if last_read_time:
            stmt_unread = select(func.count(Message.id)).where(
                Message.channel_id == channel.id,
                Message.created_at > last_read_time
            )
        else:
            # EĞER HİÇ OKUMADIYSA (NULL İSE), O KANALDAKİ TÜM MESAJLARI SAY
            stmt_unread = select(func.count(Message.id)).where(
                Message.channel_id == channel.id
            )

        res_unread = await db.execute(stmt_unread)
        unread_count = res_unread.scalar_one()

        channel_dict = {
            "id": channel.id,
            "name": channel.name,
            "description": channel.description,
            "is_direct": channel.is_direct,
            "created_at": channel.created_at,
            "role": user_role,
            "has_active_call": active_call_count > 0,
            "active_call_participants_count": active_call_count,
            "unread_message_count": unread_count
        }
        channels_with_roles.append(channel_dict)

    return channels_with_roles

async def mark_channel_as_read(channel_id: uuid.UUID, current_user_id: uuid.UUID, db: AsyncSession):
    stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id
    )
    res = await db.execute(stmt)
    member = res.scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=403, detail="Bu kanalda değilsiniz.")

    member.last_read_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Kanal okundu olarak işaretlendi."}


async def invite_user_to_channel(email: str, first_name: str | None, last_name: str | None, channel_id: uuid.UUID,
                                 inviter_id: uuid.UUID, db: AsyncSession):
    # 1. Güvenlik Kontrolü: Daveti atan kişi bu kanalda "admin" mi?
    stmt_admin = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == inviter_id,
        ChannelMember.role == "admin"
    )
    res_admin = await db.execute(stmt_admin)
    if not res_admin.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Bu kanala davet etme yetkiniz yok.")

    # 2. Kontrol: Bu mail adresi zaten bu kanalda var mı?
    stmt_user = select(User).where(User.email == email)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()

    if user:
        stmt_member = select(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == user.id
        )
        res_member = await db.execute(stmt_member)
        if res_member.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Bu kullanıcı zaten bu kanala üye.")

    # 3. Yeni Davetiye Üret
    raw_token = security.generate_magic_token()
    expires = datetime.now(timezone.utc) + timedelta(days=3)

    new_invitation = Invitation(
        email=email,
        first_name=first_name,
        last_name=last_name,
        channel_id=channel_id,
        token=raw_token,
        status="pending",
        expires_at=expires
    )
    db.add(new_invitation)
    await db.commit()

    # RabbitMQ ile davet maili atılacak
    mail_icerigi = {
        "to_email": email,
        "subject": f"ArtVoice Kanal Daveti: {channel_id}",
        "body": f"Sisteme ve kanala katılmak için bu linke tıklayın:\nhttp://localhost:3000/invite?token={raw_token}\n\nBu link 3 gün geçerlidir."
    }
    await publish_message(queue_name="email_queue", message_body=mail_icerigi)
    return {"message": f"{email} adresine kanal daveti başarıyla gönderildi."}


async def accept_channel_invite(token: str, db: AsyncSession):
    # 1. Veritabanında bu token'a sahip "pending" (bekleyen) bir davetiye var mı?
    stmt_invite = select(Invitation).where(
        Invitation.token == token,
        Invitation.status == "pending"
    )
    res_invite = await db.execute(stmt_invite)
    invitation = res_invite.scalar_one_or_none()

    if not invitation:
        raise HTTPException(status_code=400, detail="Geçersiz veya daha önce kullanılmış davet linki.")

    # 2. Davetiyenin süresi dolmuş mu?
    if invitation.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Davet linkinin süresi dolmuş.")

    # 3. Kullanıcıyı bul, sistemde hiç yoksa yeni kayıt oluştur!
    stmt_user = select(User).where(User.email == invitation.email)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()

    if not user:
        # Adam sisteme ilk defa giriyor, e-postasını VE İSMİNİ davetiyeden çekip yaratıyoruz
        user = User(
            email=invitation.email,
            first_name=invitation.first_name,
            last_name=invitation.last_name,
            is_active=True
        )
        db.add(user)
        await db.flush()

    # 4. Kullanıcıyı kanala ekle
    stmt_member = select(ChannelMember).where(
        ChannelMember.channel_id == invitation.channel_id,
        ChannelMember.user_id == user.id
    )
    res_member = await db.execute(stmt_member)

    if not res_member.scalar_one_or_none():
        new_member = ChannelMember(
            channel_id=invitation.channel_id,
            user_id=user.id,
            role="member",  # Davetle gelen düz üyedir
            last_read_at=datetime.now(timezone.utc)
        )
        db.add(new_member)

    # 5. Davetiyeyi "kabul edildi" (accepted) olarak işaretle
    invitation.status = "accepted"
    await db.commit()

    # 6. Kullanıcıyı içeri almak için token'larını üret
    from app.core import security
    access_token = security.create_access_token(subject=str(user.id))
    refresh_token = security.create_refresh_token(subject=str(user.id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "channel_id": str(invitation.channel_id),
        "message": "Davet kabul edildi, kanala başarıyla katıldınız."
    }


async def remove_user_from_channel(channel_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID,
                                   db: AsyncSession):
    # 1. Güvenlik: Kişi KENDİSİ ayrılmıyorsa (başkasını atıyorsa), admin olmak ZORUNDA.
    if target_user_id != current_user_id:
        stmt_admin = select(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.user_id == current_user_id,
            ChannelMember.role == "admin"
        )
        res_admin = await db.execute(stmt_admin)
        if not res_admin.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Başkalarını kanaldan çıkarma yetkiniz yok.")

    # 2. Silinecek üyeyi bul
    stmt_member = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == target_user_id
    )
    res_member = await db.execute(stmt_member)
    member = res_member.scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=404, detail="Kullanıcı bu kanalda bulunamadı.")

    # 3. Üyeyi sil
    await db.delete(member)
    await db.commit()
    return {"message": "Kullanıcı kanaldan başarıyla çıkarıldı."}


async def delete_channel_completely(channel_id: uuid.UUID, current_user_id: uuid.UUID, db: AsyncSession):
    # 1. Güvenlik: Sadece adminler kanalı silebilir.
    stmt_admin = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id,
        ChannelMember.role == "admin"
    )
    res_admin = await db.execute(stmt_admin)
    if not res_admin.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Bu kanalı silme yetkiniz yok.")

    # 2. Kanalı bul
    stmt_channel = select(Channel).where(Channel.id == channel_id)
    res_channel = await db.execute(stmt_channel)
    channel = res_channel.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")

    # PostgreSQL'deki Cascade yapısı sayesinde mesajlar ve üyeler otomatik silinecek
    await db.delete(channel)
    await db.commit()
    return {"message": "Kanal ve içindeki tüm veriler kalıcı olarak silindi."}


# GÜNCELLENMİŞ FONKSİYON (Eskisini sil, bunu yapıştır)
async def get_channel_members(channel_id: uuid.UUID, current_user_id: uuid.UUID, db: AsyncSession,
                              search_query: str | None = None):
    # 1. Güvenlik: İstek atan adam cidden bu kanalda mı?
    stmt_check = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id
    )
    res_check = await db.execute(stmt_check)
    if not res_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Bu kanalın üyelerini görme yetkiniz yok.")

    # 2. Temel Sorgu
    stmt = select(User, ChannelMember.role).join(
        ChannelMember, User.id == ChannelMember.user_id
    ).where(ChannelMember.channel_id == channel_id)

    # 3. YENİ ARAMA MANTIĞI: (Türkçe karakter sorununu kökten çözen yapı)
    if search_query:
        normalized_query = normalize_search_text(search_query)
        stmt = stmt.where(or_(
            sql_normalize(User.first_name).ilike(f"%{normalized_query}%"),
            sql_normalize(User.last_name).ilike(f"%{normalized_query}%"),
            sql_normalize(func.concat(User.first_name, ' ', User.last_name)).ilike(f"%{normalized_query}%")
        ))

    result = await db.execute(stmt)
    members_list = []

    # 4. Frontend için veriyi paketle
    for user, role in result.all():
        # Redis'e soruyoruz
        online_mi = await is_user_online(str(user.id))

        members_list.append({
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": role,
            "is_online": online_mi
        })
    return members_list

async def update_member_profile(channel_id: uuid.UUID, target_user_id: uuid.UUID, current_user_id: uuid.UUID,
                                first_name: str | None, last_name: str | None, db: AsyncSession):
    # 1. İsteği atan kişinin (current_user) bu kanaldaki rolünü bul
    stmt_caller = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id
    )
    res_caller = await db.execute(stmt_caller)
    caller_member = res_caller.scalar_one_or_none()

    if not caller_member:
        raise HTTPException(status_code=403, detail="Bu kanalda değilsiniz.")

    # 2. BÜYÜK YETKİ KONTROLÜ: Kişi kendisi değilse VE admin değilse -> YASAK
    if current_user_id != target_user_id and caller_member.role != "admin":
        raise HTTPException(status_code=403, detail="Başkalarının bilgilerini sadece adminler güncelleyebilir.")

    # 3. Güncellenecek (hedef) kişinin de bu kanalda olup olmadığını teyit et
    stmt_target = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == target_user_id
    )
    res_target = await db.execute(stmt_target)
    if not res_target.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Güncellenecek kullanıcı bu kanalda bulunamadı.")

    # 4. Her şey güvenli. Kullanıcıyı User tablosundan bul ve GÜNCELLE
    stmt_user = select(User).where(User.id == target_user_id)
    res_user = await db.execute(stmt_user)
    user_to_update = res_user.scalar_one_or_none()

    if first_name is not None:
        user_to_update.first_name = first_name
    if last_name is not None:
        user_to_update.last_name = last_name

    await db.commit()
    await db.refresh(user_to_update)
    return user_to_update


async def update_channel_details(channel_id: uuid.UUID, name: str | None, description: str | None,
                                 current_user_id: uuid.UUID, db: AsyncSession):
    # 1. Güvenlik Kontrolü: İsteği atan kişi bu kanalda "admin" mi?
    stmt_admin = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id,
        ChannelMember.role == "admin"
    )
    res_admin = await db.execute(stmt_admin)
    if not res_admin.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Kanal bilgilerini sadece adminler güncelleyebilir.")

    # 2. Güncellenecek kanalı bul
    stmt_channel = select(Channel).where(Channel.id == channel_id)
    res_channel = await db.execute(stmt_channel)
    channel = res_channel.scalar_one_or_none()

    if not channel:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")

    # 3. DM (Özel Mesaj) odalarının isminin değiştirilmesini engelle
    if channel.is_direct:
        raise HTTPException(status_code=400, detail="Özel mesaj (DM) odalarının ismi güncellenemez.")

    # 4. Yeni bilgileri uygula
    if name is not None:
        channel.name = name
    if description is not None:
        channel.description = description

    await db.commit()
    await db.refresh(channel)
    return channel


async def update_member_role(
        channel_id: uuid.UUID,
        target_user_id: uuid.UUID,
        new_role: str,
        current_user_id: uuid.UUID,
        db: AsyncSession
):
    # 1. İsteği atan kişi (current_user) ADMIN mi?
    stmt_caller = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == current_user_id,
        ChannelMember.role == "admin"
    )
    res_caller = await db.execute(stmt_caller)
    if not res_caller.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Rol atamasını sadece kanal adminleri yapabilir.")

    # 2. KRİTİK ZIRH: Eğer Admin KENDİ YETKİSİNİ 'member' yapmaya çalışıyorsa!
    if target_user_id == current_user_id and new_role == "member":
        # Kanalda benden başka admin var mı diye sayıyoruz
        stmt_admin_count = select(func.count()).select_from(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.role == "admin"
        )
        admin_count = await db.scalar(stmt_admin_count)

        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Kanalda tek admin sizsiniz! Kendi yetkinizi almadan önce başka birini admin yapmalısınız."
            )

    # 3. Rolü değişecek hedef kullanıcıyı bul
    stmt_target = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == target_user_id
    )
    res_target = await db.execute(stmt_target)
    target_member = res_target.scalar_one_or_none()

    if not target_member:
        raise HTTPException(status_code=404, detail="Kullanıcı bu kanalda bulunamadı.")

    # 4. İşlemi onayla ve kaydet
    target_member.role = new_role
    await db.commit()

    return target_member