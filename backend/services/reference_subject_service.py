"""命名参考主体与脚本场景的显式关联，避免目录 id 和视觉版本 id 混用。"""

from uuid import uuid4

from backend.i18n.errors import AppError
from backend.models.comic import ComicProject, ReferenceSubject, ScriptScene
from backend.models.enums import VisualEntityType
from backend.repositories.reference_subject_repository import ReferenceSubjectRepository


class ReferenceSubjectService:
    def __init__(self, repository: ReferenceSubjectRepository):
        self.repository = repository

    def require_project(self, project_id: int):
        if self.repository.session.get(ComicProject, project_id) is None:
            raise AppError("reference.project_not_found", status_code=404)

    def get(self, subject_id: int):
        subject = self.repository.get(subject_id)
        if subject is None:
            raise AppError("reference.subject_not_found", status_code=404)
        return subject

    def create(self, *, project_id: int, entity_type: VisualEntityType, name: str,
               description: str = "", negative_constraints: str = "", key: str | None = None):
        self.require_project(project_id)
        if entity_type not in {VisualEntityType.SCENE, VisualEntityType.PROP}:
            raise AppError("reference.subject_type_invalid", status_code=422)
        name = name.strip()
        normalized_key = (key or f"{entity_type.value}_{uuid4().hex}").strip()
        if not name or len(name) > 255 or not normalized_key or len(normalized_key) > 120:
            raise AppError("reference.subject_invalid", status_code=422)
        if self.repository.get_by_key(project_id, entity_type, normalized_key):
            raise AppError("reference.subject_key_exists", status_code=409)
        return self.repository.save(ReferenceSubject(project_id=project_id, entity_type=entity_type,
            key=normalized_key, name=name, description=description, negative_constraints=negative_constraints))

    def update(self, subject_id: int, *, name: str, description: str = "", negative_constraints: str = ""):
        subject = self.get(subject_id)
        if not name.strip() or len(name.strip()) > 255:
            raise AppError("reference.subject_invalid", status_code=422)
        subject.name = name.strip()
        subject.description = description
        subject.negative_constraints = negative_constraints
        return self.repository.save(subject)

    def list(self, project_id: int, entity_type: VisualEntityType | None = None):
        self.require_project(project_id)
        self.sync_script_scenes(project_id)
        return self.repository.list(project_id, entity_type)

    def sync_script_scenes(self, project_id: int):
        """按源场景 id 派生一次目录项；重试、读取和续跑均不重复创建。"""
        changed = False
        for scene in self.repository.list_scenes(project_id):
            if scene.reference_subject_id is not None:
                continue
            key = f"script_scene_{scene.id}"
            subject = self.repository.get_by_key(project_id, VisualEntityType.SCENE, key)
            if subject is None:
                subject = ReferenceSubject(project_id=project_id, entity_type=VisualEntityType.SCENE,
                    key=key, name=scene.name or scene.scene_key,
                    description="\n".join(value for value in (scene.location_type, scene.environment_details,
                        scene.time_of_day, scene.lighting, scene.weather, scene.color_palette, scene.visual_anchors) if value),
                    negative_constraints=scene.negative_constraints)
                self.repository.session.add(subject)
                self.repository.session.flush()
            scene.reference_subject_id = subject.id
            changed = True
        if changed:
            self.repository.session.commit()

    def assign_scene(self, scene_id: int, reference_subject_id: int | None):
        scene = self.repository.session.get(ScriptScene, scene_id)
        if scene is None:
            raise AppError("reference.scene_not_found", status_code=404)
        if reference_subject_id is not None:
            subject = self.get(reference_subject_id)
            if subject.entity_type != VisualEntityType.SCENE or subject.project_id != scene.task.project_id:
                raise AppError("reference.owner_invalid", status_code=422)
        scene.reference_subject_id = reference_subject_id
        self.repository.session.commit()
        return scene
