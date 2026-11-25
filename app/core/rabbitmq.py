import json
import aio_pika
from app.core.config import settings


async def publish_message(queue_name: str, message_body: dict):
    # RabbitMQ'ya bağlan
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()

        # Kuyruk yoksa oluştur (durable=True ile sunucu çökse bile mesajlar kaybolmaz)
        queue = await channel.declare_queue(queue_name, durable=True)

        # Mesajı JSON formatına çevir ve kuyruğa fırlat
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message_body).encode("utf-8"),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT  # Kalıcı mesaj
            ),
            routing_key=queue_name
        )
        print(f" RabbitMQ'ya mesaj eklendi: {queue_name} -> {message_body}")