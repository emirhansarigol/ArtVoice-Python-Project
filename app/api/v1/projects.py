import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.database import get_db
from app.schemas.project_task import ProjectResponse, ProjectCreate
from app.services import project_task_services
from app.api.dependencies import get_current_user
from app.models.user import User

# MENTOR DOKUNUŞU: WebSocket Yöneticisi eklendi
from app.core.websocket_manager import manager

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/{channel_id}", response_model=List[ProjectResponse])
async def read_projects(
        channel_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    return await project_task_services.get_projects_by_channel(db, channel_id, current_user.id)


@router.post("/", response_model=ProjectResponse)
async def project_create(
        project: ProjectCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. Projeyi oluştur
    created_project = await project_task_services.create_project(db, project, current_user.id)

    # 2. WEBSOCKET YAYINI: Kanaldaki herkese "Yeni Proje/Sütun Eklendi" duyurusu yap
    ws_payload = {
        "type": "project_created",
        "project": {
            "id": str(created_project.id),
            "name": created_project.name,
            "description": created_project.description,
            "channel_id": str(created_project.channel_id),
            "created_at": created_project.created_at.isoformat()
        }
    }
    await manager.broadcast_to_channel(ws_payload, str(created_project.channel_id))

    return created_project


@router.delete("/{project_id}")
async def delete_project_endpoint(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    # 1. Projeyi sil (Artık servis bize silinen projenin kanal ID'sini dönüyor)
    deleted_channel_id = await project_task_services.delete_project(db, project_id, current_user.id)

    if not deleted_channel_id:
        raise HTTPException(status_code=404, detail="Proje bulunamadı")

    # 2. WEBSOCKET YAYINI: Kanaldaki herkese "Proje Silindi, Ekransan Kaldırın" duyurusu yap
    ws_payload = {
        "type": "project_deleted",
        "project_id": str(project_id)
    }
    await manager.broadcast_to_channel(ws_payload, str(deleted_channel_id))

    return {"message": "Proje başarıyla silindi"}