from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.services.minio_services import ensure_bucket_exists

from app.api.v1 import auth, channels, websockets,dms,messages,tasks,projects


# 3. Lifespan: FastAPI ayağa kalkarken ve kapanırken çalışacak gizli motor
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- UYGULAMA BAŞLARKEN ÇALIŞACAK KODLAR ---
    ensure_bucket_exists()

    yield  # Uygulamanın çalıştığı süre boyunca burası beklenir



# 4. FastAPI objesini oluştururken lifespan parametresini içeri veriyoruz!
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="ArtVoice Kurumsal İletişim Platformu API",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Rotaları ana uygulamaya bağlıyoruz
app.include_router(auth.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(websockets.router, prefix="/api/v1")
app.include_router(dms.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")

