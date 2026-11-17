import { API_BASE, buildQuery, errorFromResponse, filenameFromDisposition, request, toApiError, uploadWithProgress } from './client'
import type {
  Analysis,
  ExportFormat,
  Health,
  Job,
  Marker,
  MixExportRequest,
  Peaks,
  PlayerState,
  Settings,
  Song,
  SongFilters,
  StemMode,
  StemName,
  Tag,
} from './types'

// ---- health / settings / tags ----
export const getHealth = () => request<Health>('/health')
export const getSettings = () => request<Settings>('/settings')
export const putSettings = (patch: Partial<Pick<Settings, 'language' | 'default_stem_mode' | 'metronome_volume' | 'data_dir'>>) =>
  request<Settings>('/settings', { method: 'PUT', json: patch })
export const getTags = () => request<{ tags: Tag[] }>('/tags').then((r) => r.tags)

// ---- songs ----
export const listSongs = (f: SongFilters) =>
  request<{ songs: Song[] }>(
    `/songs${buildQuery({ q: f.q?.trim(), tag: f.tag, favorite: f.favorite ? true : undefined, status: f.status, sort: f.sort, order: f.order })}`,
  ).then((r) => r.songs)

export const getSong = (id: string) => request<Song>(`/songs/${id}`)

export interface SongPatch {
  title?: string
  artist?: string | null
  album?: string | null
  favorite?: boolean
  notes?: string
  tags?: string[]
  player_state?: PlayerState
}
export const patchSong = (id: string, patch: SongPatch) => request<Song>(`/songs/${id}`, { method: 'PATCH', json: patch })

/** Fire-and-forget PATCH that survives page unload. */
export function patchSongKeepalive(id: string, patch: SongPatch): void {
  try {
    void fetch(`${API_BASE}/songs/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // ignore
  }
}

export const deleteSong = (id: string) => request<void>(`/songs/${id}`, { method: 'DELETE' })

export function uploadSong(file: File, stemMode: StemMode, onProgress?: (f: number) => void) {
  const form = new FormData()
  form.append('file', file)
  form.append('stem_mode', String(stemMode))
  return uploadWithProgress<{ song: Song; job: Job }>('/songs/upload', form, { onProgress })
}

export const addSongUrl = (url: string, stemMode: StemMode) =>
  request<{ song: Song; job: Job }>('/songs/url', { method: 'POST', json: { url, stem_mode: stemMode } })

export function uploadCover(id: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return uploadWithProgress<Song>(`/songs/${id}/cover`, form, { method: 'PUT' })
}
export const deleteCover = (id: string) => request<Song>(`/songs/${id}/cover`, { method: 'DELETE' })

export const reprocessSong = (id: string, stemMode: StemMode) =>
  request<{ job: Job }>(`/songs/${id}/reprocess`, { method: 'POST', json: { stem_mode: stemMode } })

export const stemUrl = (id: string, stem: StemName) => `${API_BASE}/songs/${id}/stems/${stem}.flac`
export const getPeaks = (id: string) => request<Peaks>(`/songs/${id}/peaks`)
export const getAnalysis = (id: string) => request<Analysis>(`/songs/${id}/analysis`)

// ---- markers ----
export const listMarkers = (id: string) => request<{ markers: Marker[] }>(`/songs/${id}/markers`).then((r) => r.markers)
export const createMarker = (id: string, m: { kind: Marker['kind']; name: string; start_s: number; end_s?: number | null }) =>
  request<Marker>(`/songs/${id}/markers`, { method: 'POST', json: m })
export const patchMarker = (id: string, mid: string, patch: { name?: string; start_s?: number; end_s?: number | null }) =>
  request<Marker>(`/songs/${id}/markers/${mid}`, { method: 'PATCH', json: patch })
export const deleteMarker = (id: string, mid: string) => request<void>(`/songs/${id}/markers/${mid}`, { method: 'DELETE' })

// ---- jobs ----
export const listJobs = (limit = 20) => request<{ jobs: Job[] }>(`/jobs?limit=${limit}`).then((r) => r.jobs)
export const cancelJob = (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: 'POST' })
export const retryJob = (jobId: string) => request<{ job: Job }>(`/jobs/${jobId}/retry`, { method: 'POST' })

// ---- exports ----
export const stemExportUrl = (id: string, stem: StemName, format: ExportFormat) =>
  `${API_BASE}/songs/${id}/export/stem/${stem}?format=${format}`
export const zipExportUrl = (id: string, format: ExportFormat) => `${API_BASE}/songs/${id}/export/zip?format=${format}`

/** Triggers a browser download of a GET endpoint after checking it succeeds. */
export async function downloadGet(url: string, fallbackName: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(url)
  } catch (err) {
    throw toApiError(err)
  }
  if (!res.ok) throw await errorFromResponse(res)
  await saveResponse(res, fallbackName)
}

export async function exportMix(id: string, body: MixExportRequest, fallbackName: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/songs/${id}/export/mix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    throw toApiError(err)
  }
  if (!res.ok) throw await errorFromResponse(res)
  await saveResponse(res, fallbackName)
}

async function saveResponse(res: Response, fallbackName: string) {
  const name = filenameFromDisposition(res.headers.get('Content-Disposition')) ?? fallbackName
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 60_000)
}
