import { describe, expect, it } from 'vitest'
import { EMPTY_LOOP, loopAfterSeek, loopToPersisted, setLoopA, setLoopB, setLoopRange, toggleLoop } from './loop'

describe('A-B loop rules', () => {
  it('sets A then B', () => {
    const l = setLoopB(setLoopA(EMPTY_LOOP, 10), 20)
    expect(l).toEqual({ a: 10, b: 20, enabled: false })
  })
  it('[ after B clears B', () => {
    const l = setLoopA({ a: 10, b: 20, enabled: true }, 25)
    expect(l).toEqual({ a: 25, b: null, enabled: false })
  })
  it('] before A clears A', () => {
    expect(setLoopB({ a: 10, b: 20, enabled: false }, 5)).toEqual({ a: null, b: 5, enabled: false })
  })
  it('ignores B − A = 0.4 s', () => {
    const l = { a: 10, b: null, enabled: false }
    expect(setLoopB(l, 10.4)).toBe(l)
    const l2 = { a: null, b: 10, enabled: false }
    expect(setLoopA(l2, 9.6)).toBe(l2)
    expect(setLoopRange(EMPTY_LOOP, 3, 3.4)).toBe(EMPTY_LOOP)
  })
  it('L does nothing without both ends', () => {
    const l = { a: 3, b: null, enabled: false }
    expect(toggleLoop(l, 0)).toEqual({ loop: l, seekTo: null })
  })
  it('enabling with the playhead outside jumps to A', () => {
    expect(toggleLoop({ a: 10, b: 20, enabled: false }, 30)).toEqual({ loop: { a: 10, b: 20, enabled: true }, seekTo: 10 })
    expect(toggleLoop({ a: 10, b: 20, enabled: false }, 15).seekTo).toBeNull()
    expect(toggleLoop({ a: 10, b: 20, enabled: true }, 15).loop.enabled).toBe(false)
  })
  it('seek outside the section with the loop on turns it off', () => {
    const l = { a: 10, b: 20, enabled: true }
    expect(loopAfterSeek(l, 25).enabled).toBe(false)
    expect(loopAfterSeek(l, 5).enabled).toBe(false)
    expect(loopAfterSeek(l, 15)).toBe(l)
  })
  it('persists null with a single end', () => {
    expect(loopToPersisted({ a: 1, b: null, enabled: false })).toBeNull()
    expect(loopToPersisted({ a: 1, b: 2, enabled: true })).toEqual({ a: 1, b: 2, enabled: true })
  })
})
