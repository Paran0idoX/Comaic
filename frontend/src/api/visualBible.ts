import { apiHeaders, currentApiLocale, parseApiErrorResponse } from './errors'

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
  positive_tag: string
  negative_tag: string
  positive_natural_language: string
  negative_natural_language: string
  color_palette: unknown[]
  lighting: string
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
    approve: boolean
  },
): Promise<VisualAsset> =>
  requestJson(`/api/visual-bible/images/${imageId}/promote`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
