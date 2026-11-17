import { describe, expect, it } from 'vitest'
import type { StemName } from '../api/types'
import { effectiveGains, exportGains, masterGain, type MixState } from './mix'

const stems: StemName[] = ['vocals', 'drums', 'bass', 'other']
const mix = (m: Partial<MixState>): MixState => ({ volumes: {}, mutes: {}, solos: {}, master: 100, ...m })

describe('effective gains', () => {
  it('defaults to unity', () => {
    expect(effectiveGains(stems, mix({}))).toEqual({ vocals: 1, drums: 1, bass: 1, other: 1 })
  })
  it('uses volume / 100', () => {
    expect(effectiveGains(stems, mix({ volumes: { bass: 70 } })).bass).toBeCloseTo(0.7)
  })
  it('mutes', () => {
    const g = effectiveGains(stems, mix({ mutes: { vocals: true } }))
    expect(g.vocals).toBe(0)
    expect(g.drums).toBe(1)
  })
  it('solo silences the others; several solos allowed', () => {
    const g = effectiveGains(stems, mix({ solos: { bass: true, drums: true }, volumes: { bass: 70 } }))
    expect(g).toEqual({ vocals: 0, drums: 1, bass: 0.7, other: 0 })
  })
  it('mute wins over solo', () => {
    expect(effectiveGains(stems, mix({ solos: { bass: true }, mutes: { bass: true } })).bass).toBe(0)
  })
  it('export gains include the master', () => {
    const m = mix({ master: 50, volumes: { vocals: 80 }, mutes: { other: true } })
    expect(masterGain(m)).toBe(0.5)
    expect(exportGains(stems, m)).toEqual({ vocals: 0.4, drums: 0.5, bass: 0.5, other: 0 })
  })
})
