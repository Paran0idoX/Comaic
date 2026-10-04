"""视觉摘要的持久化与修订冲突检查，不调用模型。"""

import json
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from backend.i18n.errors import AppError
from backend.models.comic import ReferenceVisualProfile
from backend.models.reference_visual import ReferenceProfileResponse, PROFILE_FORMAT_VERSION
from backend.models.time import utc_now
from backend.utils.json_utils import canonical_json


def profile_response(profile):
    return ReferenceProfileResponse(id=profile.id, project_id=profile.project_id, kind=profile.kind,
        owner_id=profile.owner_id, source_hash=profile.source_hash, revision=profile.revision,
        format_version=profile.format_version, data=json.loads(profile.data_json))


class ReferenceVisualProfileRepository:
    def __init__(self, session):
        self.session = session

    def find(self, project_id, kind, owner_id):
        return self.session.scalar(select(ReferenceVisualProfile).where(
            ReferenceVisualProfile.project_id == project_id, ReferenceVisualProfile.kind == kind,
            ReferenceVisualProfile.owner_id == owner_id).execution_options(populate_existing=True))

    def get(self, profile_id):
        return self.session.get(ReferenceVisualProfile, profile_id, populate_existing=True)

    def save(self, *, project_id, kind, owner_id, source_hash, data, expected_revision):
        """比较修订号，避免迟到的模型结果覆盖人工编辑或另一次提炼。"""
        existing = self.find(project_id, kind, owner_id)
        if existing is None:
            if expected_revision is not None:
                raise AppError("reference.profile_conflict", status_code=409)
            existing = ReferenceVisualProfile(project_id=project_id, kind=kind, owner_id=owner_id,
                source_hash=source_hash, format_version=PROFILE_FORMAT_VERSION, revision=1,
                data_json=canonical_json(data))
            self.session.add(existing)
            try:
                self.session.flush()
            except IntegrityError as exc:
                self.session.rollback()
                raise AppError("reference.profile_conflict", status_code=409) from exc
        else:
            if expected_revision is None:
                raise AppError("reference.profile_conflict", status_code=409)
            result = self.session.execute(update(ReferenceVisualProfile).where(
                ReferenceVisualProfile.id == existing.id, ReferenceVisualProfile.revision == expected_revision
            ).values(source_hash=source_hash, data_json=canonical_json(data),
                format_version=PROFILE_FORMAT_VERSION, revision=expected_revision + 1, updated_at=utc_now()))
            if result.rowcount != 1:
                raise AppError("reference.profile_conflict", status_code=409)
            self.session.expire(existing)
        return existing
