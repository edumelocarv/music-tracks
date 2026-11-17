import type { StemName } from '../api/types'

export interface MixState {
  /** 0–100 per stem; missing → 100. */
  volumes: Partial<Record<StemName, number>>
  mutes: Partial<Record<StemName, boolean>>
  solos: Partial<Record<StemName, boolean>>
  /** 0–100. */
  master: number
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v)

/**
 * Effective linear gain of one stem, before the master (§9.2):
 * 0 if muted, or if any stem is soloed and this one isn't; else volume/100.
 */
export function stemGain(stem: StemName, stems: readonly StemName[], mix: MixState): number {
  if (mix.mutes[stem]) return 0
  const anySolo = stems.some((s) => mix.solos[s])
  if (anySolo && !mix.solos[stem]) return 0
  return clamp01((mix.volumes[stem] ?? 100) / 100)
}

/** Per-stem gains (pre-master) for the mixer GainNodes. */
export function effectiveGains(stems: readonly StemName[], mix: MixState): Record<StemName, number> {
  const out = {} as Record<StemName, number>
  for (const s of stems) out[s] = stemGain(s, stems, mix)
  return out
}

export function masterGain(mix: Pick<MixState, 'master'>): number {
  return clamp01(mix.master / 100)
}

/** Gains for the mix export (§10): effective gain × master, rounded to 4 decimals. */
export function exportGains(stems: readonly StemName[], mix: MixState): Record<StemName, number> {
  const m = masterGain(mix)
  const out = {} as Record<StemName, number>
  for (const s of stems) out[s] = Math.round(stemGain(s, stems, mix) * m * 10_000) / 10_000
  return out
}
