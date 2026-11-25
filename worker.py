import asyncio
import json
import aio_pika
from app.core.config import settings
from app.utils.email import send_email


async def process_message(message: aio_pika.IncomingMessage):
    async with message.process():
        # Kuyruktan gelen byte formatındaki mesajı JSON'a çevir
        body = json.loads(message.body.decode("utf-8"))
        print(f"[x] Kuyruktan mesaj alındı: {body['to_email']} adresine mail atılıyor...")

        # Gerçek mail atma fonksiyonunu çağır
        await send_email(
            to_email=body["to_email"],
            subject=body["subject"],
            body=body["body"]
        )


async def main():
    print("[*] Worker başlatılıyor... RabbitMQ'ya bağlanılıyor.")
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()

        # Dinlenecek kuyruğu API ile aynı isimde (email_queue) tanımla
        queue = await channel.declare_queue("email_queue", durable=True)

        print("[*] 'email_queue' kuyruğu dinleniyor. Çıkmak için CTRL+C basın.")

        # Kuyruğa mesaj düştükçe process_message fonksiyonunu tetikle
        await queue.consume(process_message)

        # Script'in kapanmaması için sonsuz döngüde beklet
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())