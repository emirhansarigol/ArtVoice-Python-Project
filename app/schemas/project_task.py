from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: Optional[str] = "pending"
    assigned_to: Optional[uuid.UUID] = None  # YENİ

class TaskCreate(TaskBase):
    project_id: uuid.UUID
    channel_id: uuid.UUID

class TaskResponse(TaskBase):
    id: uuid.UUID
    project_id: uuid.UUID
    channel_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    channel_id: uuid.UUID

class ProjectResponse(ProjectBase):
    id: uuid.UUID
    channel_id: uuid.UUID
    created_at: datetime
    tasks: List[TaskResponse] = []

    class Config:
        from_attributes = True

class TaskStatusUpdate(BaseModel):
    status: str

class TaskAssigneeUpdate(BaseModel):
    assignee_id: Optional[uuid.UUID] = None