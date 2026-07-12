import json

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse

from backend.api.schemas.visual_bible import (
    ApprovalRequest,
    AssignOutfitRequest,
    ModelProfileRequest,
    ModelProfileResponse,
    OutfitVariantRequest,
    OutfitVariantResponse,
    PromoteImageRequest,
    SceneVisualVersionRequest,
    SceneVisualVersionResponse,
    SelectSceneVersionRequest,
    StyleProfileRequest,
    StyleProfileResponse,
    VisualAssetLocatorRequest,
    VisualAssetResponse,
)
from backend.i18n.errors import http_exception
from backend.i18n.locale import request_locale
from backend.models.comic import (
    ModelProfile,
    OutfitVariant,
    SceneVisualVersion,
    StyleProfile,
    VisualAsset,
)
from backend.models.database import SessionLocal
from backend.models.enums import (
    ApprovalStatus,
    ModelFamily,
    VisualAssetRole,
    VisualEntityType,
)
from backend.repositories.visual_bible_repository import VisualBibleRepository
from backend.services.visual_bible_service import MAX_ASSET_BYTES, VisualBibleService


router = APIRouter(prefix="/api/visual-bible", tags=["visual-bible"])


def model_profile_response(profile: ModelProfile) -> ModelProfileResponse:
    return ModelProfileResponse(
        id=profile.id,
        name=profile.name,
        family=profile.family,
        variant=profile.variant,
        checkpoint_name=profile.checkpoint_name,
        checkpoint_hash=profile.checkpoint_hash,
        component_manifest=json.loads(profile.component_manifest_json),
        default_render=json.loads(profile.default_render_json),
        compiler_key=profile.compiler_key,
        compiler_version=profile.compiler_version,
        license=profile.license,
        commercial_use_allowed=profile.commercial_use_allowed,
        paid_service_allowed=profile.paid_service_allowed,
        fine_tuning_allowed=profile.fine_tuning_allowed,
        redistribution_allowed=profile.redistribution_allowed,
        license_notice=profile.license_notice,
        is_enabled=profile.is_enabled,
        is_default=profile.is_default,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def outfit_response(item: OutfitVariant) -> OutfitVariantResponse:
    return OutfitVariantResponse(
        id=item.id,
        project_id=item.project_id,
        outline_character_id=item.outline_character_id,
        key=item.key,
        version=item.version,
        name=item.name,
        garment_components=json.loads(item.garment_components_json),
        layer_order=json.loads(item.layer_order_json),
        colors=json.loads(item.colors_json),
        materials=json.loads(item.materials_json),
        patterns=json.loads(item.patterns_json),
        accessories=json.loads(item.accessories_json),
        trigger_tokens=json.loads(item.trigger_tokens_json),
        negative_constraints=item.negative_constraints,
        status=item.status,
        approved_at=item.approved_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def style_response(item: StyleProfile) -> StyleProfileResponse:
    return StyleProfileResponse(
        id=item.id,
        project_id=item.project_id,
        key=item.key,
        version=item.version,
        name=item.name,
        model_family=item.model_family,
        positive_tokens=item.positive_tokens,
        negative_tokens=item.negative_tokens,
        color_palette=json.loads(item.color_palette_json),
        lighting=item.lighting,
        render_defaults=json.loads(item.render_defaults_json),
        status=item.status,
        approved_at=item.approved_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def scene_response(item: SceneVisualVersion) -> SceneVisualVersionResponse:
    return SceneVisualVersionResponse(
        id=item.id,
        project_id=item.project_id,
        script_scene_id=item.script_scene_id,
        version=item.version,
        landmarks=json.loads(item.landmarks_json),
        spatial_relations=json.loads(item.spatial_relations_json),
        camera_presets=json.loads(item.camera_presets_json),
        object_states=json.loads(item.object_states_json),
        color_palette=json.loads(item.color_palette_json),
        lighting_state=json.loads(item.lighting_state_json),
        status=item.status,
        approved_at=item.approved_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def asset_response(item: VisualAsset) -> VisualAssetResponse:
    return VisualAssetResponse(
        id=item.id,
        project_id=item.project_id,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        entity_key=item.entity_key,
        role=item.role,
        model_family=item.model_family,
        storage_kind=item.storage_kind.value,
        local_path=item.local_path,
        renderer_locator=item.renderer_locator,
        mime_type=item.mime_type,
        sha256=item.sha256,
        width=item.width,
        height=item.height,
        version=item.version,
        status=item.status,
        source=item.source.value,
        source_image_id=item.source_image_id,
        crop_metadata=json.loads(item.crop_metadata_json),
        mask_asset_id=item.mask_asset_id,
        approved_at=item.approved_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/model-profiles", response_model=list[ModelProfileResponse])
def list_model_profiles() -> list[ModelProfileResponse]:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        return [model_profile_response(item) for item in service.list_model_profiles()]


@router.post(
    "/model-profiles",
    response_model=ModelProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_model_profile(payload: ModelProfileRequest, request: Request) -> ModelProfileResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.create_model_profile(**payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return model_profile_response(item)


@router.put("/model-profiles/{profile_id}", response_model=ModelProfileResponse)
def update_model_profile(
    profile_id: int,
    payload: ModelProfileRequest,
    request: Request,
) -> ModelProfileResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.update_model_profile(profile_id=profile_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return model_profile_response(item)


@router.get("/projects/{project_id}/outfits", response_model=list[OutfitVariantResponse])
def list_outfits(
    project_id: int,
    request: Request,
    outline_character_id: int | None = None,
) -> list[OutfitVariantResponse]:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            items = service.list_outfits(
                project_id=project_id,
                outline_character_id=outline_character_id,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return [outfit_response(item) for item in items]


@router.post(
    "/projects/{project_id}/outfits",
    response_model=OutfitVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_outfit(
    project_id: int,
    payload: OutfitVariantRequest,
    request: Request,
) -> OutfitVariantResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.create_outfit(project_id=project_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return outfit_response(item)


@router.get("/projects/{project_id}/styles", response_model=list[StyleProfileResponse])
def list_styles(project_id: int, request: Request) -> list[StyleProfileResponse]:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            items = service.list_styles(project_id=project_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return [style_response(item) for item in items]


@router.post(
    "/projects/{project_id}/styles",
    response_model=StyleProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_style(
    project_id: int,
    payload: StyleProfileRequest,
    request: Request,
) -> StyleProfileResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.create_style(project_id=project_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return style_response(item)


@router.get(
    "/projects/{project_id}/scene-versions",
    response_model=list[SceneVisualVersionResponse],
)
def list_scene_versions(
    project_id: int,
    request: Request,
    script_scene_id: int | None = None,
) -> list[SceneVisualVersionResponse]:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            items = service.list_scene_versions(
                project_id=project_id,
                script_scene_id=script_scene_id,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return [scene_response(item) for item in items]


@router.post(
    "/projects/{project_id}/scene-versions",
    response_model=SceneVisualVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_scene_version(
    project_id: int,
    payload: SceneVisualVersionRequest,
    request: Request,
) -> SceneVisualVersionResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.create_scene_version(project_id=project_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return scene_response(item)


@router.post("/configurations/{kind}/{item_id}/status")
def set_configuration_status(
    kind: str,
    item_id: int,
    payload: ApprovalRequest,
    request: Request,
) -> dict:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.set_configuration_status(
                kind=kind,
                item_id=item_id,
                status=payload.status,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return {"id": item.id, "status": item.status.value}


@router.put("/script-characters/{character_id}/outfit")
def assign_outfit(
    character_id: int,
    payload: AssignOutfitRequest,
    request: Request,
) -> dict:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.assign_outfit(
                script_character_id=character_id,
                outfit_variant_id=payload.outfit_variant_id,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return {"id": item.id, "outfit_variant_id": item.outfit_variant_id}


@router.put("/script-scenes/{scene_id}/visual-version")
def select_scene_version(
    scene_id: int,
    payload: SelectSceneVersionRequest,
    request: Request,
) -> dict:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.select_scene_version(
                script_scene_id=scene_id,
                version_id=payload.scene_visual_version_id,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return {"id": item.id, "selected_visual_version_id": item.selected_visual_version_id}


@router.get("/projects/{project_id}/assets", response_model=list[VisualAssetResponse])
def list_assets(
    project_id: int,
    request: Request,
    entity_type: VisualEntityType | None = None,
    entity_id: int | None = None,
    approval_status: ApprovalStatus | None = None,
) -> list[VisualAssetResponse]:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            items = service.list_assets(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                status=approval_status,
            )
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return [asset_response(item) for item in items]


@router.post(
    "/projects/{project_id}/assets/upload",
    response_model=VisualAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    project_id: int,
    request: Request,
    file: UploadFile = File(...),
    entity_type: VisualEntityType = Form(...),
    role: VisualAssetRole = Form(...),
    model_family: ModelFamily = Form(ModelFamily.GENERIC),
    entity_id: int | None = Form(None),
    entity_key: str | None = Form(None),
    crop_metadata_json: str = Form("{}"),
    mask_asset_id: int | None = Form(None),
    approve: bool = Form(False),
) -> VisualAssetResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            crop_metadata = json.loads(crop_metadata_json)
            if not isinstance(crop_metadata, dict):
                raise ValueError("crop_metadata_json must be an object.")
            # 只多读一个字节用于判定超限，避免恶意 multipart 占满进程内存。
            content = await file.read(MAX_ASSET_BYTES + 1)
            item = service.upload_asset(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_key=entity_key,
                role=role,
                model_family=model_family,
                content=content,
                crop_metadata=crop_metadata,
                mask_asset_id=mask_asset_id,
                approve=approve,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise http_exception(ValueError(str(exc)), request_locale(request)) from exc
        finally:
            await file.close()
        return asset_response(item)


@router.post(
    "/projects/{project_id}/assets/register",
    response_model=VisualAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_asset(
    project_id: int,
    payload: VisualAssetLocatorRequest,
    request: Request,
) -> VisualAssetResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.register_renderer_asset(project_id=project_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return asset_response(item)


@router.post("/assets/{asset_id}/status", response_model=VisualAssetResponse)
def set_asset_status(
    asset_id: int,
    payload: ApprovalRequest,
    request: Request,
) -> VisualAssetResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.set_asset_status(asset_id=asset_id, status=payload.status)
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return asset_response(item)


@router.post("/images/{image_id}/promote", response_model=VisualAssetResponse)
def promote_image(
    image_id: int,
    payload: PromoteImageRequest,
    request: Request,
) -> VisualAssetResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            item = service.promote_image(image_id=image_id, **payload.model_dump())
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return asset_response(item)


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: int, request: Request) -> FileResponse:
    with SessionLocal() as session:
        service = VisualBibleService(VisualBibleRepository(session))
        try:
            path, mime_type = service.asset_file(asset_id)
        except ValueError as exc:
            raise http_exception(exc, request_locale(request)) from exc
        return FileResponse(path, media_type=mime_type)
