import { describe, expect, it } from 'vitest'
import { normalizePlayerState } from './playerState'

describe('player_state restore', () => {
  it('{} → §9.6 defaults with the settings metronome volume', () => {
    expect(normalizePlayerState({}, ['vocals', 'instrumental'], 70)).toEqual({
      volumes: { vocals: 100, instrumental: 100 },
      mutes: { vocals: false, instrumental: false },
      solos: { vocals: false, instrumental: false },
      master: 100,
      speed: 1,
      semitones: 0,
      loop: null,
      metronome: { enabled: false, volume: 70, offset_ms: 0 },
    })
  })

  it('4-stem state opened in 6-stem mode keeps known stems and defaults guitar/piano', () => {
    const saved = {
      volumes: { vocals: 20, drums: 50, bass: 80, other: 90 },
      mutes: { vocals: true },
      solos: { bass: true },
      master: 60,
      speed: 0.75,
      semitones: -2,
      loop: { a: 10, b: 20, enabled: true },
      metronome: { enabled: true, volume: 40, offset_ms: -30 },
    }
    const s = normalizePlayerState(saved, ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'], 70)
    expect(s.volumes).toEqual({ vocals: 20, drums: 50, bass: 80, guitar: 100, piano: 100, other: 90 })
    expect(s.mutes.vocals).toBe(true)
    expect(s.mutes.guitar).toBe(false)
    expect(s.solos.bass).toBe(true)
    expect(s.solos.piano).toBe(false)
    expect(s.master).toBe(60)
    expect(s.speed).toBe(0.75)
    expect(s.semitones).toBe(-2)
    expect(s.loop).toEqual({ a: 10, b: 20, enabled: true })
    expect(s.metronome).toEqual({ enabled: true, volume: 40, offset_ms: -30 })
  })

  it('clamps out-of-range values', () => {
    const s = normalizePlayerState({ speed: 3, semitones: -40, master: 500, metronome: { offset_ms: 900 } }, ['vocals'], 70)
    expect(s.speed).toBe(1.5)
    expect(s.semitones).toBe(-12)
    expect(s.master).toBe(100)
    expect(s.metronome.offset_ms).toBe(100)
  })
})
