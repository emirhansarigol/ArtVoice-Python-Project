from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ArtVoice API"
    VERSION: str = "1.0.0"

    # Güvenlik (JWT)
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Veritabanı
    DATABASE_URL: str

    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    REDIS_URL: str
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    MINIO_BUCKET_NAME: str = "artvoice-files"

    # .env dosyasını otomatik okuması için Pydantic v2 ayarı
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)


# Projenin her yerinde sadece "settings" objesini import edip kullanacağız
settings = Settings()