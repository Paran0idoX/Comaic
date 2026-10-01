import type { ReferenceCategory, ReferenceRole } from '@/api/referenceImages'
import type { VisualAsset } from '@/api/visualBible'

export const REFERENCE_ROLES: Record<ReferenceCategory, ReferenceRole[]> = {
  character: ['identity_face', 'identity_half_body', 'identity_full_body', 'identity_side', 'identity_back'],
  scene: ['scene_master'], prop: ['prop_reference'],
}
export type ReferenceOwner = {
  key: string; category: ReferenceCategory; name: string; characterId: number | null
  subjectId: number | null; description: string; negativeConstraints: string
  sceneVersionId?: number | null
}

/** 原图按业务归属筛选，避免同名对象或跨项目图片混入；旧资产仍保留原归属。 */
export const ownerAssets = (assets: VisualAsset[], owner: ReferenceOwner, projectId: number): VisualAsset[] =>
  assets.filter(asset => asset.project_id === projectId && asset.status !== 'archived' &&
    (owner.category === 'character'
      ? asset.entity_type === 'character' && asset.entity_id === owner.characterId
      : asset.entity_type === owner.category && asset.reference_subject_id === owner.subjectId &&
        (owner.category !== 'scene' || owner.sceneVersionId === undefined || (asset.entity_id ?? null) === owner.sceneVersionId)))
    .sort((a, b) => b.version - a.version || b.id - a.id)

export const autoFaceAsset = (assets: VisualAsset[], owner: ReferenceOwner, projectId: number): VisualAsset | null =>
  ownerAssets(assets, owner, projectId).find(asset => asset.role === 'identity_face' && asset.status === 'approved') ?? null

export const assetImageUrl = (asset: VisualAsset): string | null =>
  asset.local_path ? `/api/visual-bible/assets/${asset.id}/file` : null

export const validReferenceRoles = (category: ReferenceCategory, roles: ReferenceRole[]): ReferenceRole[] =>
  REFERENCE_ROLES[category].filter(role => roles.includes(role))
