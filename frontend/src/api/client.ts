export const API_BASE = '/api'

/** Error returned by the API (`{"error": {"code", "detail", ...extra}}`) or a network failure. */
export class ApiError extends Error {
  readonly code: string
  readonly detail: string | null
  readonly status: number
  readonly extra: Record<string, unknown>

  constructor(code: string, detail: string | null, status: number, extra: Record<string, unknown> = {}) {
    super(`${code}${detail ? `: ${detail}` : ''}`)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
    this.status = status
    this.extra = extra
  }

  get existingSongId(): string | null {
    const v = this.extra.existing_song_id
    return typeof v === 'string' ? v : null
  }
}

export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  if (err instanceof Error) return new ApiError('NETWORK_ERROR', err.message, 0)
  return new ApiError('INTERNAL_ERROR', String(err), 0)
}

/** Builds an ApiError from a parsed JSON body (or anything else) and HTTP status. */
export function errorFromBody(body: unknown, status: number): ApiError {
  if (body && typeof body === 'object' && 'error' in body) {
    const e = (body as { error: unknown }).error
    if (e && typeof e === 'object') {
      const { code, detail, ...extra } = e as Record<string, unknown>
      return new ApiError(
        typeof code === 'string' ? code : 'INTERNAL_ERROR',
        typeof detail === 'string' ? detail : detail == null ? null : JSON.stringify(detail),
        status,
        extra,
      )
    }
  }
  // FastAPI default validation shape ({"detail": [...]}) or an unexpected body
  if (body && typeof body === 'object' && 'detail' in body) {
    return new ApiError(status === 422 ? 'VALIDATION_ERROR' : 'INTERNAL_ERROR', JSON.stringify((body as { detail: unknown }).detail), status)
  }
  return new ApiError(status === 404 ? 'NOT_FOUND' : 'INTERNAL_ERROR', `HTTP ${status}`, status)
}

export async function errorFromResponse(res: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // not JSON
  }
  return errorFromBody(body, res.status)
}

export async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init
  let res: Response
  try {
    res = await fetch(API_BASE + path, {
      ...rest,
      headers: json !== undefined ? { 'Content-Type': 'application/json', ...headers } : headers,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    })
  } catch (err) {
    throw toApiError(err)
  }
  if (!res.ok) throw await errorFromResponse(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

/** Multipart upload with progress (fetch has no upload progress). */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  opts: { method?: string; onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(opts.method ?? 'POST', API_BASE + path)
    xhr.responseType = 'text'
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total)
    }
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(errorFromBody(body, xhr.status))
    }
    xhr.onerror = () => reject(new ApiError('NETWORK_ERROR', 'Network error', 0))
    xhr.onabort = () => reject(new ApiError('ABORTED', null, 0))
    opts.signal?.addEventListener('abort', () => xhr.abort())
    xhr.send(form)
  })
}

/** Parses `filename*=UTF-8''...` (preferred) or `filename="..."` from Content-Disposition. */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const star = /filename\*\s*=\s*([^']*)''([^;]+)/i.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[2].trim().replace(/^"|"$/g, ''))
    } catch {
      // fall through
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header)
  return plain ? plain[1] : null
}
