from fastapi import WebSocket
from typing import Dict, List
# MENTOR NOTU: SQLAlchemy, AsyncSession, User modeli ve uuid importlarının hepsini SİLDİK!
# Çünkü bu dosya artık veritabanı (PostgreSQL) ile hiç muhatap olmayacak. (Separation of Concerns)

from app.core.redis_client import set_user_online, set_user_offline


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.user_connections: Dict[str, int] = {}
        # Hangi kullanıcının (ID) hangi WebSocket tünelleri açık? (P2P sinyali için)
        self.user_sockets: Dict[str, List[WebSocket]] = {}
        # Global (Genel Bildirim) Soketlerini Tutacağımız Yer
        self.global_connections: Dict[str, List[WebSocket]] = {}

    async def connect_global(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.global_connections:
            self.global_connections[user_id] = []
        self.global_connections[user_id].append(websocket)
        print(f" [GLOBAL] Kullanıcı genel bildirime bağlandı: {user_id}")

    async def disconnect_global(self, websocket: WebSocket, user_id: str):
        if user_id in self.global_connections:
            if websocket in self.global_connections[user_id]:
                self.global_connections[user_id].remove(websocket)
            if not self.global_connections[user_id]:
                del self.global_connections[user_id]
        print(f"[GLOBAL] Kullanıcı genel bildirimden koptu: {user_id}")

    async def send_global_notification(self, user_id: str, message: dict):
        """Belirli bir kullanıcının genel soketine (uygulamada nerede olursa olsun) anlık bildirim atar"""
        if user_id in self.global_connections:
            for connection in self.global_connections[user_id]:
                await connection.send_json(message)

    async def connect(self, websocket: WebSocket, channel_id: str, user_id: str):
        await websocket.accept()

        if channel_id not in self.active_connections:
            self.active_connections[channel_id] = []
        self.active_connections[channel_id].append(websocket)

        # Kullanıcıyı kendi özel soket listesine ekle
        if user_id not in self.user_sockets:
            self.user_sockets[user_id] = []
        self.user_sockets[user_id].append(websocket)

        # --- ONLINE DURUMU KONTROLÜ ---
        if user_id not in self.user_connections:
            self.user_connections[user_id] = 0

        self.user_connections[user_id] += 1

        # Kullanıcı ilk sekmesini açtıysa (Sisteme girdiyse)
        if self.user_connections[user_id] == 1:
            print(f"[ONLINE] Kullanıcı bağlandı: {user_id}")

            # ARTIK POSTGRESQL YOK! Doğrudan Redis'e 60 saniyelik yaşam süresi (TTL) atıyoruz.
            await set_user_online(user_id, expire_seconds=60)

            # Odadaki diğer kişilere "Ahmet online oldu" diyerek yeşil ışık yaktırıyoruz
            await self.broadcast_to_channel({
                "type": "user_status",
                "user_id": user_id,
                "status": "online"
            }, channel_id)

    async def disconnect(self, websocket: WebSocket, channel_id: str, user_id: str):
        if channel_id in self.active_connections:
            if websocket in self.active_connections[channel_id]:
                self.active_connections[channel_id].remove(websocket)
            if not self.active_connections[channel_id]:
                del self.active_connections[channel_id]

        # Kullanıcıyı özel soket listesinden çıkar
        if user_id in self.user_sockets and websocket in self.user_sockets[user_id]:
            self.user_sockets[user_id].remove(websocket)
            if not self.user_sockets[user_id]:
                del self.user_sockets[user_id]

        # --- OFFLINE DURUMU KONTROLÜ ---
        if user_id in self.user_connections:
            self.user_connections[user_id] -= 1

            # Kullanıcı tüm sekmeleri kapattıysa
            if self.user_connections[user_id] <= 0:
                print(f"[OFFLINE] Kullanıcı koptu: {user_id}")
                del self.user_connections[user_id]

                # ARTIK POSTGRESQL YOK! Redis'ten adamın anahtarını anında siliyoruz.
                await set_user_offline(user_id)

                # Odadaki diğer kişilere "Ahmet çevrimdışı oldu" diyerek ışığı söndürtüyoruz
                await self.broadcast_to_channel({
                    "type": "user_status",
                    "user_id": user_id,
                    "status": "offline"
                }, channel_id)

    async def broadcast_to_channel(self, message: dict, channel_id: str):
        if channel_id in self.active_connections:
            for connection in self.active_connections[channel_id]:
                await connection.send_json(message)

    # Doğrudan sadece tek bir hedefe (P2P) WebRTC sinyali göndermek için
    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.user_sockets:
            for connection in self.user_sockets[user_id]:
                await connection.send_json(message)


manager = ConnectionManager()