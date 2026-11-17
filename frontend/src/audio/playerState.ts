import type { LoopState, MetronomeState, StemName } from '../api/types'

/** Fully-populated player state (§9.6). Only the song's current stems appear in the maps. */
export interface FullPlayerState {
  volumes: Record<string, number>
  mutes: Record<string, boolean>
  solos: Record<string, boolean>
  master: number
  speed: number
  semitones: number
  loop: LoopState | null
  metronome: MetronomeState
}

export const SPEED_MIN = 0.5
export const SPEED_MAX = 1.5
export const SEMITONES_MIN = -12
export const SEMITONES_MAX = 12
export const OFFSET_MIN = -100
export const OFFSET_MAX = 100

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function defaultPlayerState(stems: readonly StemName[], metronomeVolume: number): FullPlayerState {
  return normalizePlayerState({}, stems, metronomeVolume)
}

/**
 * Restores `player_state` from the server: fills defaults (volume 100, no mute/solo, master 100,
 * speed 1, semitones 0, loop null, metronome off with the settings volume and offset 0), drops
 * unknown/out-of-mode stems and clamps every value to its range.
 */
export function normalizePlayerState(
  raw: unknown,
  stems: readonly StemName[],
  metronomeVolume: number,
  duration?: number | null,
): FullPlayerState {
  const r = isObj(raw) ? raw : {}
  const vols = isObj(r.volumes) ? r.volumes : {}
  const mutes = isObj(r.mutes) ? r.mutes : {}
  const solos = isObj(r.solos) ? r.solos : {}
  const out: FullPlayerState = {
    volumes: {},
    mutes: {},
    solos: {},
    master: Math.round(clamp(num(r.master) ?? 100, 0, 100)),
    speed: Math.round(clamp(num(r.speed) ?? 1, SPEED_MIN, SPEED_MAX) * 100) / 100,
    semitones: Math.round(clamp(num(r.semitones) ?? 0, SEMITONES_MIN, SEMITONES_MAX)),
    loop: null,
    metronome: { enabled: false, volume: Math.round(clamp(metronomeVolume, 0, 100)), offset_ms: 0 },
  }
  for (const s of stems) {
    out.volumes[s] = Math.round(clamp(num(vols[s]) ?? 100, 0, 100))
    out.mutes[s] = mutes[s] === true
    out.solos[s] = solos[s] === true
  }
  if (isObj(r.loop)) {
    const a = num(r.loop.a)
    const b = num(r.loop.b)
    const max = duration ?? Infinity
    if (a !== null && b !== null && a >= 0 && b <= max && b - a >= 0.5) {
      out.loop = { a, b, enabled: r.loop.enabled === true }
    }
  }
  if (isObj(r.metronome)) {
    const m = r.metronome
    out.metronome = {
      enabled: m.enabled === true,
      volume: Math.round(clamp(num(m.volume) ?? out.metronome.volume, 0, 100)),
      offset_ms: Math.round(clamp(num(m.offset_ms) ?? 0, OFFSET_MIN, OFFSET_MAX)),
    }
  }
  return out
}
