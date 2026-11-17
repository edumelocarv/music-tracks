import { describe, expect, it } from 'vitest'
import {
  beatToContextTime,
  clicksInWindow,
  INITIAL_SEGMENT,
  positionAt,
  scheduleSegment,
  wrapIntoLoop,
  type Segment,
} from './timeline'

const seg = (s: Partial<Segment>): Segment => ({ ...INITIAL_SEGMENT, ...s })

describe('positionAt', () => {
  it('is 0 and held before playing', () => {
    expect(positionAt([INITIAL_SEGMENT], 5)).toBe(0)
  })

  it('advances at rate 1 after play', () => {
    const s = [seg({ output: 10, input: 0, active: true })]
    expect(positionAt(s, 12.5)).toBeCloseTo(2.5)
  })

  it('handles speed changes', () => {
    let segs: Segment[] = [INITIAL_SEGMENT]
    segs = scheduleSegment(segs, 0.9, 1, { active: true, input: 0 }).segments // play at t=1
    segs = scheduleSegment(segs, 4.9, 5, { rate: 0.5 }).segments // half speed at t=5 (pos 4)
    expect(positionAt(segs, 5)).toBeCloseTo(4)
    expect(positionAt(segs, 9)).toBeCloseTo(6)
    segs = scheduleSegment(segs, 8.9, 9, { rate: 1.5 }).segments // pos 6
    expect(positionAt(segs, 11)).toBeCloseTo(9)
  })

  it('holds the position while paused and resumes from it', () => {
    let segs: Segment[] = [INITIAL_SEGMENT]
    segs = scheduleSegment(segs, 0, 0.1, { active: true, input: 0 }).segments
    segs = scheduleSegment(segs, 3, 3.1, { active: false }).segments // pause at pos 3
    expect(positionAt(segs, 3.1)).toBeCloseTo(3)
    expect(positionAt(segs, 50)).toBeCloseTo(3)
    segs = scheduleSegment(segs, 60, 60.1, { active: true }).segments
    expect(positionAt(segs, 61.1)).toBeCloseTo(4)
  })

  it('seeks', () => {
    let segs: Segment[] = [INITIAL_SEGMENT]
    segs = scheduleSegment(segs, 0, 0.1, { active: true, input: 0 }).segments
    segs = scheduleSegment(segs, 5, 5.1, { input: 100 }).segments
    expect(positionAt(segs, 5.05)).toBeCloseTo(4.95) // old segment still heard until 5.1
    expect(positionAt(segs, 6.1)).toBeCloseTo(101)
  })

  it('wraps inside an active loop, including a lead-in before A', () => {
    const s = [seg({ output: 0, input: 8, active: true, loopStart: 10, loopEnd: 14 })]
    expect(positionAt(s, 1)).toBeCloseTo(9) // before the loop: untouched
    expect(positionAt(s, 5)).toBeCloseTo(13)
    expect(positionAt(s, 6)).toBeCloseTo(10) // reached B → A
    expect(positionAt(s, 7.5)).toBeCloseTo(11.5)
    expect(positionAt(s, 6 + 4 * 3 + 1)).toBeCloseTo(11)
  })

  it('wraps with a non-unit rate', () => {
    const s = [seg({ output: 0, input: 10, rate: 0.5, active: true, loopStart: 10, loopEnd: 12 })]
    expect(positionAt(s, 3)).toBeCloseTo(11.5)
    expect(positionAt(s, 5)).toBeCloseTo(10.5)
  })

  it('wrapIntoLoop is a no-op without a loop', () => {
    expect(wrapIntoLoop(50, 0, 0)).toBe(50)
    expect(wrapIntoLoop(14, 10, 14)).toBe(10)
  })
})

describe('scheduleSegment', () => {
  it('discards pending segments like the worklet, but composes their changes', () => {
    let segs: Segment[] = [INITIAL_SEGMENT]
    segs = scheduleSegment(segs, 0, 0.1, { active: true, input: 0 }).segments
    // seek, then (before it is heard) a speed change
    segs = scheduleSegment(segs, 10, 10.1, { input: 50 }).segments
    const r = scheduleSegment(segs, 10.05, 10.15, { rate: 0.5 })
    expect(r.segments.filter((s) => s.output >= 10.05)).toHaveLength(1)
    expect(r.segment.input).toBeCloseTo(50.05)
    expect(r.segment.rate).toBe(0.5)
    expect(r.segment.active).toBe(true)
  })

  it('drops old history', () => {
    let segs: Segment[] = [INITIAL_SEGMENT]
    for (let t = 1; t < 20; t++) segs = scheduleSegment(segs, t, t + 0.1, { active: t % 2 === 0 }).segments
    expect(segs.length).toBeLessThan(5)
    expect(positionAt(segs, 19.1)).toBeGreaterThan(0)
  })
})

describe('beat → context time', () => {
  it('maps with speed', () => {
    const s = seg({ output: 100, input: 10, rate: 0.5, active: true })
    expect(beatToContextTime(s, 12)).toBeCloseTo(104)
    const fast = seg({ output: 100, input: 10, rate: 1.5, active: true })
    expect(beatToContextTime(fast, 13)).toBeCloseTo(102)
  })

  it('lists clicks in a window', () => {
    const beats = [0, 0.5, 1, 1.5, 2, 2.5, 3]
    const s = [seg({ output: 10, input: 0.5, rate: 0.5, active: true })]
    const c = clicksInWindow(s, beats, 10, 12.01)
    expect(c.map((x) => x.beatIndex)).toEqual([1, 2, 3])
    expect(c.map((x) => x.time)).toEqual([10, 11, 12])
  })

  it('ignores paused segments and respects segment boundaries', () => {
    const beats = [0, 1, 2, 3, 4, 5]
    const s = [seg({ output: 0, input: 0, active: true }), seg({ output: 2.5, input: 2.5, active: false })]
    expect(clicksInWindow(s, beats, 0, 10).map((x) => x.beatIndex)).toEqual([0, 1, 2])
  })

  it('repeats beats across loop repetitions', () => {
    const beats = [9, 10, 11, 12, 13, 14]
    const s = [seg({ output: 0, input: 9, active: true, loopStart: 10, loopEnd: 12 })]
    const c = clicksInWindow(s, beats, 0, 7)
    // 9@0, 10@1, 11@2, wrap at t=3 → 10@3, 11@4, 10@5, 11@6
    expect(c.map((x) => x.beatIndex)).toEqual([0, 1, 2, 1, 2, 1, 2])
    expect(c.map((x) => x.time)).toEqual([0, 1, 2, 3, 4, 5, 6])
  })

  it('repeats loop beats with speed', () => {
    const beats = [10, 11]
    const s = [seg({ output: 0, input: 10, rate: 2, active: true, loopStart: 10, loopEnd: 12 })]
    const c = clicksInWindow(s, beats, 0.9, 3)
    expect(c.map((x) => x.time)).toEqual([1, 1.5, 2, 2.5])
  })
})
