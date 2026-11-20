import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ---------------------------------------------------------------------------
// 外部知识声明对接：合作图谱文件导入、复核清单、边证据与换号建边
// ---------------------------------------------------------------------------

export type EvidenceEnvelope<T> = { ok: boolean; total?: number; items: T[] }

export async function registerNamespace(values: Record<string, string>): Promise<unknown> {
  const response = await request('/api/knowledge-evidence/namespaces', {
    method: 'POST',
    body: JSON.stringify(values),
  })
  return await response.json()
}

export async function importPartnerFile(payload: Record<string, unknown>): Promise<unknown> {
  const response = await request('/api/knowledge-evidence/partner-imports', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}

export async function listPartnerImports(): Promise<EvidenceEnvelope<Record<string, unknown>>> {
  const response = await request('/api/knowledge-evidence/partner-imports')
  if (!response.ok) throw new Error('来件登记读取失败')
  return await response.json()
}

export async function listClaims(status = ''): Promise<EvidenceEnvelope<Record<string, unknown>>> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await request(`/api/knowledge-evidence/claims${query}`)
  if (!response.ok) throw new Error('外部声明数据包读取失败')
  return await response.json()
}

export async function listEdgeEvidence(edgeId = ''): Promise<EvidenceEnvelope<Record<string, unknown>>> {
  const query = edgeId ? `?edge_id=${encodeURIComponent(edgeId)}` : ''
  const response = await request(`/api/knowledge-evidence/edge-evidence${query}`)
  if (!response.ok) throw new Error('边证据清单读取失败')
  return await response.json()
}

export async function listReviewChecklist(
  status = '',
): Promise<EvidenceEnvelope<Record<string, unknown>>> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await request(`/api/knowledge-evidence/review-checklist${query}`)
  if (!response.ok) throw new Error('图谱复核清单读取失败')
  return await response.json()
}

export async function verifyProvenance(reviewId: number): Promise<unknown> {
  const response = await request(
    `/api/knowledge-evidence/review-checklist/${reviewId}/verify-provenance`,
    { method: 'POST' },
  )
  return await response.json()
}

export async function registerRenumberedEdge(
  values: Record<string, string>,
): Promise<unknown> {
  const response = await request('/api/knowledge-evidence/edges/register-renumber', {
    method: 'POST',
    body: JSON.stringify(values),
  })
  return await response.json()
}
