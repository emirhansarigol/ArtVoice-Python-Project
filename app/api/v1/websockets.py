import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from jose import JWTError

from app.db.database import get_db
from app.core.websocket_manager import manager
from app.core.security import verify_token
from app.models.channel import ChannelMember
from app.services import message_services
from app.models.user import User
from app.core.redis_client import add_user_to_call, remove_user_from_call, get_active_call_participants, set_user_online

router = APIRouter()

# ---------------------------------------------------------
# GLOBAL (GENEL BİLDİRİM VE ARAMA) SOKETİ
# ---------------------------------------------------------
@router.websocket("/ws/global")
async def global_websocket_endpoint(
        websocket: WebSocket,
        token: str = Query(...)
):
    # 1. TOKEN KONTROLÜ
    try:
        payload = verify_token(token)
        user_id_str = payload.get("sub")

        if not user_id_str or payload.get("type") != "access":
            await websocket.close(code=1008)
            return
        user_id = str(uuid.UUID(user_id_str))
    except JWTError:
        await websocket.close(code=1008)
        return

    # 2. GLOBAL TÜNELE BAĞLA
    await manager.connect_global(websocket, user_id)

    try:
        while True:
            # MENTOR DOKUNUŞU: Sonsuz döngü kilitlenmelerini önleyen zırh
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise  # Kopmayı yutma, dışarıdaki temizlik bloğuna fırlat!
            except RuntimeError:
                raise WebSocketDisconnect(code=1000)
            except Exception as e:
                print(f"[GLOBAL] JSON ÇÖZME HATASI: {e}")
                continue

            action_type = data.get("type")

            # --- WEBRTC ARAMA SİNYALLERİ (Çaldırma, Açma, Kapatma) ---
            if action_type in ["call_request", "call_accepted", "call_rejected", "call_ended"]:
                target_user_id = data.get("target_user_id")

                signal_payload = {
                    "type": action_type,
                    "sender_id": user_id,
                    "channel_id": data.get("channel_id"),  # Hangi odadan arıyor
                    "data": data.get("data")  # Varsa ekstra bilgi (Offer SDP vs)
                }

                # Sinyali doğrudan hedef kullanıcının ekranına fırlat
                await manager.send_global_notification(target_user_id, signal_payload)

    except WebSocketDisconnect:
        await manager.disconnect_global(websocket, user_id)


# ---------------------------------------------------------
# KANAL (CHAT VE WEBRTC MEDYA) SOKETİ
# ---------------------------------------------------------
@router.websocket("/ws/{channel_id}")
async def websocket_endpoint(
        websocket: WebSocket,
        channel_id: uuid.UUID,
        token: str = Query(...),
        db: AsyncSession = Depends(get_db)
):
    # 1. TOKEN KONTROLÜ
    try:
        payload = verify_token(token)
        user_id_str = payload.get("sub")
        token_type = payload.get("type")

        if not user_id_str or token_type != "access":
            await websocket.close(code=1008)
            return
        user_id = uuid.UUID(user_id_str)
    except JWTError:
        await websocket.close(code=1008)
        return

    # 2. YETKİ KONTROLÜ
    stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == user_id
    )
    res = await db.execute(stmt)
    is_member = res.scalar_one_or_none()

    if not is_member:
        await websocket.close(code=1008)
        return

    # 3. BAĞLANTIYI KABUL ET
    await manager.connect(websocket, str(channel_id), str(user_id))

    # 4. MESAJ DİNLEME DÖNGÜSÜ
    try:
        while True:
            # MENTOR DOKUNUŞU: Olası tüm patlamalara karşı 3 katmanlı güvenlik!
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise  # Sekme kapandıysa doğrudan çıkışa git
            except RuntimeError:
                raise WebSocketDisconnect(code=1000)  # Kapanmış soketten okuma hatasını çevir
            except Exception as e:
                print(f"[CHAT] Bozuk format veya JSON hatası: {e}")
                continue  # Sadece hatalı formatı atla, dinlemeye devam et!

            action_type = data.get("type")

            # --- HEARTBEAT (KALP ATIŞI) ---
            if action_type == "ping":
                # Front-end'den her ping geldiğinde adamın Redis süresini 60 sn uzat!
                await set_user_online(str(user_id), expire_seconds=60)
                await websocket.send_json({"type": "pong"})
                continue

            # --- NORMAL MESAJLAŞMA ---
            if action_type == "chat_message":
                try:
                    content = data.get("content")

                    # Mesajı PostgreSQL'e kaydet
                    saved_message = await message_services.save_message(
                        db=db,
                        channel_id=channel_id,
                        sender_id=user_id,
                        content=content
                    )

                    message_payload = {
                        "id": str(saved_message.id),
                        "sender_id": str(user_id),
                        "content": content,
                        "channel_id": str(channel_id),
                        "room_id": str(channel_id),
                        "is_edited": saved_message.is_edited,
                        "created_at": saved_message.created_at.isoformat(),
                        "type": "new_message"
                    }

                    # Odadaki herkese (kendisi dahil) mesajı gönder
                    await manager.broadcast_to_channel(message=message_payload, channel_id=str(channel_id))

                    # GLOBAL BİLDİRİM FIRLATMA KISMI (Diğer odalardaki üyeler için rozet)
                    stmt_sender = select(User).where(User.id == user_id)
                    res_sender = await db.execute(stmt_sender)
                    sender = res_sender.scalar_one_or_none()
                    sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() if sender else "Biri"

                    stmt_members = select(ChannelMember.user_id).where(
                        ChannelMember.channel_id == channel_id,
                        ChannelMember.user_id != user_id
                    )
                    res_members = await db.execute(stmt_members)
                    other_members = res_members.scalars().all()

                    for member_id in other_members:
                        notification_payload = {
                            "type": "new_message",  # <--- FRONTEND İLE AYNI DİLİ KONUŞSUN!
                            "channel_id": str(channel_id),
                            "room_id": str(channel_id),  # <--- DM GLOBAL BİLDİRİMLERİ İÇİN ŞART
                            "sender_id": str(user_id),
                            "sender_name": sender_name,
                            "content": content
                        }
                        await manager.send_global_notification(str(member_id), notification_payload)

                except Exception as inner_error:
                    print(f" KRİTİK VERİTABANI HATASI: {inner_error}")
                    import traceback
                    traceback.print_exc()

            # --- WEBRTC MEDYA SİNYALLERİ ---
            elif action_type in ["webrtc_offer", "webrtc_answer", "webrtc_ice_candidate"]:
                target_user_id = data.get("target_user_id")
                signal_payload = {
                    "type": action_type,
                    "sender_id": str(user_id),
                    "data": data.get("data")
                }
                await manager.send_personal_message(message=signal_payload, user_id=target_user_id)

            # --- YAZIYOR SİNYALLERİ ---
            elif action_type in ["typing_start", "typing_stop"]:
                typing_payload = {
                    "type": action_type,
                    "user_id": str(user_id),
                    "channel_id": str(channel_id)
                }
                await manager.broadcast_to_channel(typing_payload, str(channel_id))

            # --- REDİS ÇAĞRI DURUMU KONTROLLERİ ---
            elif action_type == "join_call":
                await add_user_to_call(str(channel_id), str(user_id))
                current_participants = await get_active_call_participants(str(channel_id))
                await manager.broadcast_to_channel({
                    "type": "call_participants_updated",
                    "channel_id": str(channel_id),
                    "participants": current_participants
                }, str(channel_id))

            elif action_type == "leave_call":
                await remove_user_from_call(str(channel_id), str(user_id))
                current_participants = await get_active_call_participants(str(channel_id))
                await manager.broadcast_to_channel({
                    "type": "call_participants_updated",
                    "channel_id": str(channel_id),
                    "participants": current_participants
                }, str(channel_id))

    except WebSocketDisconnect:
        # Kişi koptuğunda temizlik operasyonu başlar
        try:
            # Önce sesli çağrıdaysa oradan çıkar (Redis)
            await remove_user_from_call(str(channel_id), str(user_id))
            current_participants = await get_active_call_participants(str(channel_id))
            await manager.broadcast_to_channel({
                "type": "call_participants_updated",
                "channel_id": str(channel_id),
                "participants": current_participants
            }, str(channel_id))
        except Exception:
            pass  # Redis anlık ulaşılamazsa temizlik yarıda kalmasın diye

        # Sonra ana ConnectionManager'dan sil ve Offline yap
        await manager.disconnect(websocket, str(channel_id), str(user_id))

