# Python 3.12'nin hafif sürümünü kullanıyoruz
FROM python:3.12-slim

# Konteyner içindeki çalışma dizinimiz
WORKDIR /app

# Gerekli sistem paketlerini kuruyoruz
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Bağımlılıkları kopyala ve yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# NOT: Proje dosyalarını buraya COPY ile kopyalamıyoruz.
# docker-compose.yml içinde 'volumes' ile bağlayacağız ki anlık güncellemeleri görsün.