export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export type DocumentSummary = {
  id: number
  filename: string
  file_type: 'pdf' | 'docx' | 'txt'
  character_count: number
  status: string
  chunk_count: number
  created_at: string
  updated_at: string
}

export type RetrievalHit = {
  chunk_id: number
  document_id: number
  chunk_index: number
  text: string
  score: number
  model: string | null
  dimension: number
}

export type ChatSource = {
  chunk_id: number
  document_id: number
  chunk_index: number
  filename: string | null
  text: string
  score: number
}

export type ChatResponse = {
  question: string
  answer: string
  sources: ChatSource[]
}

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options)
  } catch {
    throw new ApiError('无法连接后端服务，请确认 FastAPI 已启动。', 0)
  }

  const contentType = response.headers.get('content-type') || ''
  const body = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const message =
      typeof body === 'object' && body?.error?.message
        ? body.error.message
        : `后端请求失败（HTTP ${response.status}）。`
    const code = typeof body === 'object' ? body?.error?.code : undefined
    throw new ApiError(message, response.status, code)
  }

  return body as T
}

export async function getHealth(): Promise<{ status: string }> {
  return request<{ status: string }>('/health')
}

export async function listDocuments(): Promise<{
  items: DocumentSummary[]
  total: number
}> {
  return request('/api/v1/documents?limit=100&offset=0')
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const formData = new FormData()
  formData.append('file', file)
  return request<DocumentSummary>('/api/v1/documents', {
    method: 'POST',
    body: formData,
  })
}

export async function embedDocument(documentId: number): Promise<{
  document_id: number
  chunk_count: number
  embedded_count: number
  dimension: number
  model: string | null
  status: string
}> {
  return request(`/api/v1/documents/${documentId}/embed`, { method: 'POST' })
}

export async function searchDocuments(payload: {
  query: string
  top_k?: number
  document_id?: number | null
  min_score?: number | null
}): Promise<{ query: string; hits: RetrievalHit[] }> {
  return request('/api/v1/retrieval/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function askQuestion(payload: {
  question: string
  top_k?: number
  document_id?: number | null
  min_score?: number | null
}): Promise<ChatResponse> {
  return request('/api/v1/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
