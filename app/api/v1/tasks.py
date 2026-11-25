import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.schemas.project_task import TaskResponse, TaskCreate, TaskStatusUpdate, TaskAssigneeUpdate
from app.db.database import get_db
from app.services import project_task_services
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.channel import ChannelMember
from app.core.websocket_manager import manager

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# --- GİZLİLİK İÇİN YARDIMCI FONKSİYON ---
async def notify_task_stakeholders(db: AsyncSession, channel_id: str, ws_payload: dict, assigned_to: str | None):
    """
    WebSocket ile "Kanaldaki herkese" yayın yapmak yerine (Çünkü görevler gizli),
    bu görevi GÖRMEYE YETKİSİ OLANLARA (Yani sadece Adminlere ve Görevin Sahibine) özel sinyal fırlatır.
    """
    # 1. Kanaldaki tüm adminleri bul
    stmt_admins = select(ChannelMember.user_id).where(
        ChannelMember.channel_id == uuid.UUID(channel_id),
        ChannelMember.role == "admin"
    )
    res_admins = await db.execute(stmt_admins)
    admin_ids = [str(a_id) for a_id in res_admins.scalars().all()]

    # 2. Adminlere mesajı yolla
    for a_id in admin_ids:
        await manager.send_personal_message(message=ws_payload, user_id=a_id)

    # 3. Eğer görevin atandığı kişi varsa ve bu kişi admin değilse, ona da özel mesaj yolla
    if assigned_to and assigned_to not in admin_ids:
        await manager.send_personal_message(message=ws_payload, user_id=assigned_to)


# --- ENDPOINTLER ---

@router.get("/", response_model=List[TaskResponse])
async def read_tasks(channel_id: uuid.UUID, project_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    return await project_task_services.get_tasks(db, channel_id, project_id, current_user.id)


@router.post("/", response_model=TaskResponse)
async def task_create(task: TaskCreate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    created_task = await project_task_services.create_task(db, task, current_user.id)

    payload = {
        "type": "task_created",
        "task": {
            "id": str(created_task.id),
            "project_id": str(created_task.project_id),
            "title": created_task.title,
            "status": created_task.status,
            "assigned_to": str(created_task.assigned_to) if created_task.assigned_to else None
        }
    }
    # YENİ NESİL YAYIN: Herkes yerine sadece yetkililere (Hedefe Gönderim)
    await notify_task_stakeholders(db, str(task.channel_id), payload,
                                   str(created_task.assigned_to) if created_task.assigned_to else None)

    return created_task


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def update_task(task_id: uuid.UUID, payload: TaskStatusUpdate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    updated_task = await project_task_services.update_task_status(db, task_id, payload.status, current_user.id)
    if not updated_task: raise HTTPException(status_code=404, detail="Görev bulunamadı")

    ws_payload = {
        "type": "task_updated",
        "task_id": str(updated_task.id),
        "new_status": updated_task.status
    }
    # YENİ NESİL YAYIN
    await notify_task_stakeholders(db, str(updated_task.channel_id), ws_payload,
                                   str(updated_task.assigned_to) if updated_task.assigned_to else None)

    return updated_task


@router.patch("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(task_id: uuid.UUID, payload: TaskAssigneeUpdate, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    updated_task = await project_task_services.assign_user_to_task(db, task_id, payload.assignee_id, current_user.id)
    if not updated_task: raise HTTPException(status_code=404, detail="Görev bulunamadı.")

    ws_payload = {
        "type": "task_assigned",
        "task_id": str(updated_task.id),
        "assigned_to": str(updated_task.assigned_to) if updated_task.assigned_to else None
    }
    # YENİ NESİL YAYIN
    await notify_task_stakeholders(db, str(updated_task.channel_id), ws_payload,
                                   str(updated_task.assigned_to) if updated_task.assigned_to else None)

    return updated_task