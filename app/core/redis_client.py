import redis.asyncio as redis
from app.core.config import settings
from app.core.config import settings  # Eğer redis url config'de yoksa direkt "redis://artvoice_redis:6379" yazabilirsin

# Docker ağındaki redis container'ının adresi (Eğer .env'den okuyorsan orayı kullan)

# Tüm uygulamanın kullanacağı global Redis havuzu
redis_db = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

async def get_active_call_participants(channel_id: str):
    """Bir kanaldaki aktif sesli sohbette kimlerin olduğunu getirir"""
    # Redis'te Set (Küme) veri tipini kullanıyoruz. Key: call:channel_id
    participants = await redis_db.smembers(f"call:{channel_id}")
    return list(participants)


async def add_user_to_call(channel_id: str, user_id: str):
    """Kullanıcıyı sesli sohbete ekler"""
    await redis_db.sadd(f"call:{channel_id}", user_id)
    # Çağrı odası 24 saat işlem görmezse otomatik silinsin (RAM şişmesin)
    await redis_db.expire(f"call:{channel_id}", 86400)


async def remove_user_from_call(channel_id: str, user_id: str):
    """Kullanıcıyı sesli sohbetten çıkarır"""
    await redis_db.srem(f"call:{channel_id}", user_id)

    # Odada kimse kalmadıysa Redis'ten odayı tamamen temizle
    count = await redis_db.scard(f"call:{channel_id}")
    if count == 0:
        await redis_db.delete(f"call:{channel_id}")

# KULLANICI ONLINE/OFFLINE İŞLEMLERİ

async def set_user_online(user_id: str, expire_seconds: int = 60):
    """
    Kullanıcının 'kalp atışını' Redis'e kaydeder.
    expire_seconds: Eğer bu süre boyunca yeni bir kalp atışı gelmezse,
                    Redis bu anahtarı otomatik siler ve adam 'Offline' olur.
    """
    # setex (Set with Expiration): Bir veriyi oluştur ve ona ömür biç
    await redis_db.setex(f"online:{user_id}", expire_seconds, "true")

async def set_user_offline(user_id: str):
    """Kullanıcı kendi isteğiyle sekmeyi kapattığında veya çıkış yaptığında hemen offline yap."""
    await redis_db.delete(f"online:{user_id}")

async def is_user_online(user_id: str) -> bool:
    """Kullanıcının online durumunu Redis'ten sor."""
    # exist: "Bu anahtar Redis'te yaşıyor mu?" sorusunun cevabıdır (1 veya 0 döner)
    result = await redis_db.exists(f"online:{user_id}")
    return result > 0