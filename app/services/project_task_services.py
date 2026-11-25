import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.models.project_task import Project, Task
from app.models.channel import ChannelMember
from app.schemas.project_task import ProjectCreate, TaskCreate


#  SADECE ADMIN KONTROLÜ ---
async def check_admin_role(db: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID):
    member = await check_channel_membership(db, channel_id, user_id)
    if member.role != "admin":
        raise HTTPException(status_code=403, detail="Bu işlemi sadece kanal adminleri yapabilir.")
    return member


async def check_channel_membership(db: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID):
    """Kullanıcının o kanalda olup olmadığını kontrol eder ve üye bilgisini (rolüyle beraber) döner."""
    stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == user_id
    )
    res = await db.execute(stmt)
    member = res.scalar_one_or_none()

    if not member:
        raise HTTPException(status_code=403, detail="Bu kanalda işlem yapma yetkiniz yok.")
    return member



# --- PROJECTS CRUD ---
async def get_projects_by_channel(db: AsyncSession, channel_id: uuid.UUID, current_user_id: uuid.UUID):
    await check_channel_membership(db, channel_id, current_user_id)  # Herkes görebilir
    stmt = select(Project).where(Project.channel_id == channel_id)
    res = await db.execute(stmt)
    return res.scalars().all()


async def create_project(db: AsyncSession, project: ProjectCreate, current_user_id: uuid.UUID):
    await check_admin_role(db, project.channel_id, current_user_id)  # SADECE ADMİN
    db_project = Project(**project.model_dump())
    db.add(db_project)
    await db.commit()
    await db.refresh(db_project)
    return db_project


async def delete_project(db: AsyncSession, project_id: uuid.UUID, current_user_id: uuid.UUID):
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    db_project = res.scalar_one_or_none()

    if not db_project:
        return None

    await check_admin_role(db, db_project.channel_id, current_user_id)

    # SİLMEDEN ÖNCE KANAL ID'SİNİ KENARA ALIYORUZ (Yayın yapmak için lazım olacak)
    channel_id_to_broadcast = db_project.channel_id

    await db.delete(db_project)
    await db.commit()

    # Sadece True dönmek yerine Kanal ID'sini dönüyoruz
    return channel_id_to_broadcast

# --- TASKS CRUD ---


async def create_task(db: AsyncSession, task: TaskCreate, current_user_id: uuid.UUID):
    await check_admin_role(db, task.channel_id, current_user_id)  # SADECE ADMİN
    db_task = Task(**task.model_dump())
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return db_task



async def assign_user_to_task(db: AsyncSession, task_id: uuid.UUID, assignee_id: uuid.UUID | None,
                              current_user_id: uuid.UUID):
    stmt = select(Task).where(Task.id == task_id)
    res = await db.execute(stmt)
    db_task = res.scalar_one_or_none()
    if not db_task: return None

    # SADECE ADMİNLER GÖREV ATAYABİLİR
    await check_admin_role(db, db_task.channel_id, current_user_id)

    if assignee_id:
        await check_channel_membership(db, db_task.channel_id, assignee_id)

    db_task.assigned_to = assignee_id
    await db.commit()
    await db.refresh(db_task)
    return db_task




# --- 2. GÖREV GİZLİLİĞİ (Sadece kendi görevlerini gör) ---
async def get_tasks(db: AsyncSession, channel_id: uuid.UUID, project_id: uuid.UUID, current_user_id: uuid.UUID):
    member = await check_channel_membership(db, channel_id, current_user_id)

    stmt = select(Task).where(Task.channel_id == channel_id, Task.project_id == project_id)

    # EĞER ADMİN DEĞİLSE, SADECE KENDİSİNE ATANANLARI GÖREBİLİR!
    if member.role != "admin":
        stmt = stmt.where(Task.assigned_to == current_user_id)

    res = await db.execute(stmt)
    return res.scalars().all()


# --- 3. DİĞER FONKSİYONLARDAKİ YETKİLERİ DÜZELTİYORUZ ---
# create_project, delete_project, create_task, assign_user_to_task içindeki
# "await check_admin_or_pm_role(...)" kısımlarını "await check_admin_role(...)" olarak değiştir.

async def update_task_status(db: AsyncSession, task_id: uuid.UUID, status: str, current_user_id: uuid.UUID):
    stmt = select(Task).where(Task.id == task_id)
    res = await db.execute(stmt)
    db_task = res.scalar_one_or_none()

    if db_task:
        member = await check_channel_membership(db, db_task.channel_id, current_user_id)

        # SADECE GÖREVİN SAHİBİ VEYA ADMİN GÜNCELLEYEBİLİR
        if db_task.assigned_to != current_user_id and member.role != "admin":
            raise HTTPException(status_code=403, detail="Bu görevi sadece atanan kişi veya admin güncelleyebilir.")

        db_task.status = status
        await db.commit()
        await db.refresh(db_task)
    return db_task