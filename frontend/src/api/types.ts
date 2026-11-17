// JSON shapes from docs/api-contract.md

export type StemName = 'vocals' | 'instrumental' | 'drums' | 'bass' | 'guitar' | 'piano' | 'other'
export type StemMode = 2 | 4 | 6
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'canceled'
export type JobStep = 'download' | 'prepare' | 'separate' | 'analyze' | 'peaks'
export type SongStatus = 'pending' | 'processing' | 'ready' | 'failed'
export type AnalysisStatus = 'none' | 'ok' | 'failed'
export type Language = 'en' | 'pt-BR'
export type ExportFormat = 'wav' | 'flac' | 'mp3'

export const ERROR_CODES = [
  'UNSUPPORTED_FORMAT',
  'FILE_TOO_LARGE',
  'INVALID_AUDIO',
  'TOO_LONG',
  'TOO_SHORT',
  'DUPLICATE',
  'INVALID_URL',
  'PLAYLIST_NOT_SUPPORTED',
  'DOWNLOAD_FAILED',
  'SEPARATION_FAILED',
  'OUT_OF_MEMORY',
  'DISK_FULL',
  'JOB_ALREADY_ACTIVE',
  'NOT_FOUND',
  'VALIDATION_ERROR',
  'SONG_NOT_READY',
  'INVALID_STATE',
  'FORBIDDEN',
  'INTERNAL_ERROR',
] as const
export type ErrorCode = (typeof ERROR_CODES)[number]

export interface Job {
  id: string
  song_id: string
  song_title: string
  stem_mode: StemMode
  status: JobStatus
  step: JobStep | null
  step_detail: 'downloading_model' | null
  step_index: number
  step_count: number
  step_progress: number
  error_code: string | null
  error_detail: string | null
  attempts: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface LoopState {
  a: number
  b: number
  enabled: boolean
}

export interface MetronomeState {
  enabled: boolean
  volume: number
  offset_ms: number
}

/** §9.6 — every field optional because the server stores whatever we send (default `{}`). */
export interface PlayerState {
  volumes?: Partial<Record<StemName, number>>
  mutes?: Partial<Record<StemName, boolean>>
  solos?: Partial<Record<StemName, boolean>>
  master?: number
  speed?: number
  semitones?: number
  loop?: LoopState | null
  metronome?: Partial<MetronomeState>
}

export interface Song {
  id: string
  title: string
  artist: string | null
  album: string | null
  duration_s: number | null
  source_type: 'file' | 'url' | 'watch'
  source_url: string | null
  original_filename: string | null
  stem_mode: StemMode
  status: SongStatus
  favorite: boolean
  notes: string
  has_cover: boolean
  cover_url: string | null
  bpm: number | null
  key_label: string | null
  analysis_status: AnalysisStatus
  player_state: PlayerState
  tags: string[]
  stems: StemName[]
  active_job: Job | null
  last_job: Job | null
  created_at: string
  updated_at: string
}

export interface Marker {
  id: string
  song_id: string
  kind: 'marker' | 'loop'
  name: string
  start_s: number
  end_s: number | null
  created_at: string
}

export interface Settings {
  language: Language | null
  default_stem_mode: StemMode
  metronome_volume: number
  data_dir: string
  data_dir_locked: boolean
  restart_required: boolean
}

export interface Health {
  ok: boolean
  device: 'mps' | 'cuda' | 'cpu'
  ffmpeg: string
  yt_dlp: string
  data_dir: string
  models_cached: boolean
}

export interface Tag {
  name: string
  count: number
}

/** peaks.json (§7.5) */
export interface Peaks {
  samples_per_peak: number
  sample_rate: number
  stems: Partial<Record<StemName, number[]>>
}

export interface ChordSegment {
  start: number
  end: number
  label: string
}

/** analysis.json (§7.4) */
export interface Analysis {
  version: number
  bpm: number | null
  beats: number[]
  downbeats: number[]
  key: { label: string; tonic: string; scale: string; confidence: number } | null
  chords: ChordSegment[]
}

export type SongSort = 'created_at' | 'title' | 'artist' | 'bpm' | 'duration_s'

export interface SongFilters {
  q?: string
  tag?: string
  favorite?: boolean
  status?: SongStatus
  sort?: SongSort
  order?: 'asc' | 'desc'
}

export interface MixExportRequest {
  gains: Partial<Record<StemName, number>>
  speed: number
  semitones: number
  start_s: number | null
  end_s: number | null
  format: ExportFormat
}
