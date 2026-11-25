from minio import Minio
from minio.error import S3Error
from fastapi import UploadFile, HTTPException
import uuid
from app.core.config import settings
import json

# 1. MinIO İstemcisini (Client) Oluştur
# Sistemin her yerinden MinIO'ya bağlanmak için bu nesneyi kullanacağız.
minio_client = Minio(
    endpoint=settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ACCESS_KEY,
    secret_key=settings.MINIO_SECRET_KEY,
    secure=settings.MINIO_SECURE
)


def ensure_bucket_exists():
    """
    Sistem ilk ayağa kalktığında çalışır. Bucket yoksa oluşturur ve dış dünyaya okuma izni (Public Read) verir.
    """
    try:
        found = minio_client.bucket_exists(settings.MINIO_BUCKET_NAME)
        if not found:
            minio_client.make_bucket(settings.MINIO_BUCKET_NAME)
            print(f"[{settings.MINIO_BUCKET_NAME}] bucket'ı başarıyla oluşturuldu.")

        # --- BUCKET'I DIŞARIYA (FRONTEND'E) OKUMAYA AÇIK HALE GETİREN KOD ---
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "*"},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{settings.MINIO_BUCKET_NAME}/*"]
                }
            ]
        }
        minio_client.set_bucket_policy(settings.MINIO_BUCKET_NAME, json.dumps(policy))
        print(f"[{settings.MINIO_BUCKET_NAME}] okuma izni (Public Read) ayarlandı.")
        # ---------------------------------------------------------------------

    except S3Error as err:
        print(f"MinIO Bucket hatası: {err}")

async def upload_file_to_minio(file: UploadFile) -> str:
    """
    Kullanıcıdan gelen dosyayı alır, adını eşsiz (UUID) yapar ve MinIO'ya fırlatır.
    Geriye, o dosyaya ulaşabileceğimiz indirme linkini (URL) döner.
    """
    try:
        # Dosya adının sonundaki uzantıyı al (.jpg, .pdf vs)
        file_extension = file.filename.split(".")[-1]

        # Aynı isimde dosyalar çakışmasın diye eşsiz bir isim üretiyoruz (örn: 550e8400...jpg)
        unique_file_name = f"{uuid.uuid4()}.{file_extension}"

        # FastAPI'nin UploadFile objesinin içindeki fiziksel dosyayı okumaya hazırla
        file_size = file.size

        # Dosyayı MinIO'ya bas!
        minio_client.put_object(
            bucket_name=settings.MINIO_BUCKET_NAME,
            object_name=unique_file_name,
            data=file.file,
            length=file_size,
            content_type=file.content_type
        )

        # Dosya başarıyla yüklendi. Şimdi Frontend'e vereceğimiz linki oluşturuyoruz.
        # Bu link sayesinde Frontend resmi <img> tagı içinde gösterebilecek.
        file_url = f"http://localhost:9000/{settings.MINIO_BUCKET_NAME}/{unique_file_name}"

        return file_url

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dosya yüklenirken hata oluştu: {str(e)}")




async def delete_file_from_minio(file_url: str):
    """Verilen URL'den dosya adını çıkarır ve MinIO'dan fiziksel olarak siler."""
    try:
        if not file_url:
            return

        # URL'den bucket adını ve dosya adını ayrıştır
        # Örnek URL: http://localhost:9000/artvoice-files/b9c7cfe5...mp3
        bucket_name = settings.MINIO_BUCKET_NAME

        # Split ile dosya adını yakalıyoruz
        object_name = file_url.split(f"/{bucket_name}/")[-1]

        # Minio client ile sil
        minio_client.remove_object(bucket_name, object_name)
        print(f"🗑️ MinIO'dan dosya silindi: {object_name}")

    except Exception as e:
        print(f"MinIO dosya silme hatası: {e}")