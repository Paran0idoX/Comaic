import { apiHeaders, currentApiLocale, parseApiErrorResponse } from './errors'

export type ModelFamily = 'anima' | 'z_image' | 'generic'
export type ApprovalStatus = 'draft' | 'approved' | 'archived'
export type VisualEntityType = 'character' | 'outfit' | 'scene' | 'style' | 'prop' | 'control'
export type VisualAssetRole =
  | 'identity_face'
  | 'identity_half_body'
  | 'identity_full_body'
  | 'outfit_front'
  | 'outfit_back'
  | 'outfit_detail'
  | 'scene_master'
  | 'style_reference'
  | 'prop_reference'
  | 'pose'
  | 'depth'
  | 'canny'
  | 'lineart'
  | 'segmentation'
  | 'mask'
  | 'lora'

export type ModelProfile = {
  id: number
  name: string
  family: ModelFamily
  variant: string
  checkpoint_name: string
  checkpoint_hash: string | null
  component_manifest: Record<string, unknown>
  default_render: Record<string, unknown>
  compiler_key: string
  compiler_version: string
  license: string | null
  commercial_use_allowed: boolean | null
  paid_service_allowed: boolean | null
  fine_tuning_allowed: boolean | null
  redistribution_allowed: boolean | null
  license_notice: string | null
  is_enabled: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

export type ModelProfilePayload = Omit<
  ModelProfile,
  'id' | 'compiler_key' | 'compiler_version' | 'created_at' | 'updated_at'
>

export type OutfitVariant = {
  id: number
  project_id: number
  outline_character_id: number
  key: string
  version: number
  name: string
  garment_components: unknown[]
  layer_order: unknown[]
  colors: unknown[]
  materials: unknown[]
  patterns: unknown[]
  accessories: unknown[]
  trigger_tokens: unknown[]
  negative_constraints: string
  status: ApprovalStatus
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type StyleProfile = {
  id: number
  project_id: number
  key: string
  version: number
  name: string
  model_family: ModelFamily
  positive_tokens: string
  negative_tokens: string
  color_palette: unknown[]
  lighting: string
  render_defaults: Record<string, unknown>
  status: ApprovalStatus
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type SceneVisualVersion = {
  id: number
  project_id: number
  script_scene_id: number
  version: number
  landmarks: unknown[]
  spatial_relations: Record<string, unknown>
  camera_presets: unknown[]
  object_states: Record<string, unknown>
  color_palette: unknown[]
  lighting_state: Record<string, unknown>
  status: ApprovalStatus
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type VisualAsset = {
  id: number
  project_id: number
  entity_type: VisualEntityType
  entity_id: number | null
  entity_key: string | null
  role: VisualAssetRole
  model_family: ModelFamily
  storage_kind: 'local_file' | 'renderer_locator'
  local_path: string | null
  renderer_locator: string | null
  mime_type: string | null
  sha256: string | null
  width: number | null
  height: number | null
  version: number
  status: ApprovalStatus
  source: string
  source_image_id: number | null
  crop_metadata: Record<string, unknown>
  mask_asset_id: number | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

const requestJson = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const response = await fetch(url, { ...options, headers: apiHeaders(options.headers) })
  if (!response.ok) throw await parseApiErrorResponse(response)
  return (await response.json()) as T
}

export const listModelProfiles = (): Promise<ModelProfile[]> =>
  requestJson('/api/visual-bible/model-profiles')

export const createModelProfile = (payload: ModelProfilePayload): Promise<ModelProfile> =>
  requestJson('/api/visual-bible/model-profiles', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateModelProfile = (
  id: number,
  payload: ModelProfilePayload,
): Promise<ModelProfile> =>
  requestJson(`/api/visual-bible/model-profiles/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const listOutfits = (projectId: number): Promise<OutfitVariant[]> =>
  requestJson(`/api/visual-bible/projects/${projectId}/outfits`)

export const createOutfit = (
  projectId: number,
  payload: Omit<OutfitVariant, 'id' | 'project_id' | 'version' | 'status' | 'approved_at' | 'created_at' | 'updated_at'>,
): Promise<OutfitVariant> =>
  requestJson(`/api/visual-bible/projects/${projectId}/outfits`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const listStyles = (projectId: number): Promise<StyleProfile[]> =>
  requestJson(`/api/visual-bible/projects/${projectId}/styles`)

export const createStyle = (
  projectId: number,
  payload: Omit<StyleProfile, 'id' | 'project_id' | 'version' | 'status' | 'approved_at' | 'created_at' | 'updated_at'>,
): Promise<StyleProfile> =>
  requestJson(`/api/visual-bible/projects/${projectId}/styles`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const listSceneVersions = (projectId: number): Promise<SceneVisualVersion[]> =>
  requestJson(`/api/visual-bible/projects/${projectId}/scene-versions`)

export const createSceneVersion = (
  projectId: number,
  payload: Omit<SceneVisualVersion, 'id' | 'project_id' | 'version' | 'status' | 'approved_at' | 'created_at' | 'updated_at'>,
): Promise<SceneVisualVersion> =>
  requestJson(`/api/visual-bible/projects/${projectId}/scene-versions`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const setConfigurationStatus = (
  kind: 'outfit' | 'style' | 'scene',
  id: number,
  status: ApprovalStatus,
): Promise<{ id: number; status: ApprovalStatus }> =>
  requestJson(`/api/visual-bible/configurations/${kind}/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })

export const assignOutfitVariant = (
  scriptCharacterId: number,
  outfitVariantId: number | null,
): Promise<{ id: number; outfit_variant_id: number | null }> =>
  requestJson(`/api/visual-bible/script-characters/${scriptCharacterId}/outfit`, {
    method: 'PUT',
    body: JSON.stringify({ outfit_variant_id: outfitVariantId }),
  })

export const selectSceneVisualVersion = (
  scriptSceneId: number,
  sceneVisualVersionId: number | null,
): Promise<{ id: number; selected_visual_version_id: number | null }> =>
  requestJson(`/api/visual-bible/script-scenes/${scriptSceneId}/visual-version`, {
    method: 'PUT',
    body: JSON.stringify({ scene_visual_version_id: sceneVisualVersionId }),
  })

export const listVisualAssets = (projectId: number): Promise<VisualAsset[]> =>
  requestJson(`/api/visual-bible/projects/${projectId}/assets`)

export const uploadVisualAsset = async (projectId: number, form: FormData): Promise<VisualAsset> => {
  const response = await fetch(`/api/visual-bible/projects/${projectId}/assets/upload`, {
    method: 'POST',
    body: form,
    headers: {
      'X-Locale': currentApiLocale(),
      'Accept-Language': currentApiLocale(),
    },
  })
  if (!response.ok) throw await parseApiErrorResponse(response)
  return (await response.json()) as VisualAsset
}

export const registerVisualAsset = (
  projectId: number,
  payload: {
    entity_type: VisualEntityType
    entity_id: number | null
    entity_key?: string | null
    role: VisualAssetRole
    model_family: ModelFamily
    renderer_locator: string
    sha256?: string | null
    approve: boolean
  },
): Promise<VisualAsset> =>
  requestJson(`/api/visual-bible/projects/${projectId}/assets/register`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const setVisualAssetStatus = (
  id: number,
  status: ApprovalStatus,
): Promise<VisualAsset> =>
  requestJson(`/api/visual-bible/assets/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })

export const promoteGeneratedImage = (
  imageId: number,
  payload: {
    entity_type: VisualEntityType
    entity_id: number | null
    entity_key?: string | null
    role: VisualAssetRole
    model_family: ModelFamily
    approve: boolean
  },
): Promise<VisualAsset> =>
  requestJson(`/api/visual-bible/images/${imageId}/promote`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
