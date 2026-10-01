"""场景与物品命名目录的数据访问，不调用模型或外部工具。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.comic import ReferenceSubject, ScriptScene, ScriptGenerationTask
from backend.models.enums import VisualEntityType


class ReferenceSubjectRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, subject_id: int) -> ReferenceSubject | None:
        return self.session.get(ReferenceSubject, subject_id)

    def get_by_key(self, project_id: int, entity_type: VisualEntityType, key: str):
        return self.session.scalar(select(ReferenceSubject).where(
            ReferenceSubject.project_id == project_id,
            ReferenceSubject.entity_type == entity_type,
            ReferenceSubject.key == key,
        ))

    def list(self, project_id: int, entity_type: VisualEntityType | None = None):
        query = select(ReferenceSubject).where(ReferenceSubject.project_id == project_id)
        if entity_type is not None:
            query = query.where(ReferenceSubject.entity_type == entity_type)
        return list(self.session.scalars(query.order_by(ReferenceSubject.entity_type, ReferenceSubject.name, ReferenceSubject.id)))

    def list_scenes(self, project_id: int):
        return list(self.session.scalars(select(ScriptScene).join(ScriptGenerationTask).where(
            ScriptGenerationTask.project_id == project_id
        ).order_by(ScriptScene.id)))

    def save(self, subject: ReferenceSubject):
        self.session.add(subject)
        self.session.commit()
        self.session.refresh(subject)
        return subject
