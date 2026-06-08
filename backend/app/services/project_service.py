from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    async def get_list(
        self,
        db: AsyncSession,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Project], int]:
        query = select(Project)
        count_query = select(func.count()).select_from(Project)
        if status:
            query = query.where(Project.status == status)
            count_query = count_query.where(Project.status == status)
        total = (await db.execute(count_query)).scalar_one()
        offset = (page - 1) * page_size
        query = query.order_by(Project.updated_at.desc()).offset(offset).limit(page_size)
        projects = (await db.execute(query)).scalars().all()
        return projects, total

    async def get_by_id(self, db: AsyncSession, project_id: str) -> Project | None:
        return await db.get(Project, project_id)

    async def create(self, db: AsyncSession, data: ProjectCreate) -> Project:
        project = Project(
            name=data.name,
            description=data.description,
            genre=data.genre,
            word_count_target=data.word_count_target,
            settings=data.settings,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project

    async def update(
        self, db: AsyncSession, project_id: str, data: ProjectUpdate
    ) -> Project | None:
        project = await db.get(Project, project_id)
        if not project:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(project, key, value)
        await db.commit()
        await db.refresh(project)
        return project

    async def delete(self, db: AsyncSession, project_id: str) -> bool:
        project = await db.get(Project, project_id)
        if not project:
            return False
        await db.delete(project)
        await db.commit()
        return True


project_service = ProjectService()
