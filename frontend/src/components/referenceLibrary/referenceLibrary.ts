import type { ReferenceCategory, ReferenceRole } from '@/api/referenceImages'
import type { VisualAsset } from '@/api/visualBible'

export const REFERENCE_ROLES: Record<ReferenceCategory, ReferenceRole[]> = {
  character: ['identity_face', 'identity_full_body', 'identity_side', 'identity_back'],
  scene: ['scene_master'], prop: ['prop_reference'],
}
export type ReferenceOwner = {
  key: string; category: ReferenceCategory; name: string; characterId: number | null
  subjectId: number | null; description: string; negativeConstraints: string
  sceneVersionId?: number | null
  sceneDefinitionVersion?: number
}

/** 快速选图只传展示数据和明确的确认目标，弹窗不负责请求或改变素材归属。 */
export type QuickReferenceImage = {
  key: string; imageUrl: string | null; label: string; applicability: string | null
  approved: boolean; canApprove: boolean
  target: { kind: 'asset'; id: number } | { kind: 'image'; id: number; taskId: number }
}

/** 互斥只发生在同一用途与适用范围；人物造型和场景版本分别保留自己的确认图。 */
export const sameReferenceSlot = (asset: VisualAsset, confirmed: VisualAsset): boolean => {
  if (asset.project_id !== confirmed.project_id || asset.entity_type !== confirmed.entity_type || asset.role !== confirmed.role) return false
  if (confirmed.entity_type === 'character' && REFERENCE_ROLES.character.includes(confirmed.role as ReferenceRole)) {
    return asset.entity_id === confirmed.entity_id && (confirmed.role === 'identity_face' ||
      (asset.outfit_variant_id ?? null) === (confirmed.outfit_variant_id ?? null))
  }
  if (confirmed.entity_type === 'scene' && confirmed.role === 'scene_master') {
    return (asset.entity_id ?? null) === (confirmed.entity_id ?? null) &&
      ((asset.reference_subject_id ?? null) === (confirmed.reference_subject_id ?? null) ||
        confirmed.entity_id != null && asset.reference_subject_id == null) &&
      (confirmed.reference_subject_id != null || confirmed.entity_id != null || asset.entity_key === confirmed.entity_key)
  }
  return confirmed.entity_type === 'prop' && confirmed.role === 'prop_reference' &&
    (asset.entity_id ?? null) === (confirmed.entity_id ?? null) &&
    (asset.reference_subject_id ?? null) === (confirmed.reference_subject_id ?? null) &&
    (confirmed.reference_subject_id != null || asset.entity_key === confirmed.entity_key)
}

/** 原图按业务归属筛选，避免同名对象或跨项目图片混入；旧资产仍保留原归属。 */
export const ownerAssets = (assets: VisualAsset[], owner: ReferenceOwner, projectId: number): VisualAsset[] =>
  assets.filter(asset => asset.role !== 'identity_half_body' && asset.project_id === projectId && asset.status !== 'archived' &&
    (owner.category === 'character'
      ? asset.entity_type === 'character' && asset.entity_id === owner.characterId
      : asset.entity_type === owner.category && asset.reference_subject_id === owner.subjectId &&
        (owner.category !== 'scene' || owner.sceneVersionId === undefined || (asset.entity_id ?? null) === owner.sceneVersionId)))
    .sort((a, b) => b.version - a.version || b.id - a.id)

export const autoFaceAsset = (assets: VisualAsset[], owner: ReferenceOwner, projectId: number): VisualAsset | null =>
  ownerAssets(assets, owner, projectId).find(asset => asset.role === 'identity_face' && asset.status === 'approved' && Boolean(asset.local_path)) ?? null

export const assetImageUrl = (asset: VisualAsset): string | null =>
  asset.local_path ? `/api/visual-bible/assets/${asset.id}/file` : null

export const validReferenceRoles = (category: ReferenceCategory, roles: ReferenceRole[]): ReferenceRole[] =>
  REFERENCE_ROLES[category].filter(role => roles.includes(role))
/** 人物身体图使用竖幅；每种用途独立保留手动尺寸。 */
export const defaultReferenceSize = (role: string) => role === 'identity_face' ? { width: 768, height: 768 }
  : ['identity_full_body', 'identity_side', 'identity_back'].includes(role) ? { width: 512, height: 768 }
  : { width: 1024, height: 1024 }
