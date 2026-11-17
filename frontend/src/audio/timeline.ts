/**
 * Pure timing logic for the stretch node (§9.1, §9.3).
 *
 * A *segment* mirrors one `node.schedule()` call: from context time `output` on, the
 * source is read from `input` at `rate` (or held, when inactive), wrapping inside
 * [loopStart, loopEnd) when that range is non-empty — exactly like the worklet does.
 * All source times are "tempo de origem" (seconds in the original audio).
 */

export interface Segment {
  /** Audio context time at which this segment starts being heard. */
  output: number
  /** Source position at `output`. */
  input: number
  rate: number
  active: boolean
  semitones: number
  loopStart: number
  /** Loop disabled when loopEnd <= loopStart. */
  loopEnd: number
}

export const INITIAL_SEGMENT: Segment = {
  output: 0,
  input: 0,
  rate: 1,
  active: false,
  semitones: 0,
  loopStart: 0,
  loopEnd: 0,
}

export function loopLength(s: Pick<Segment, 'loopStart' | 'loopEnd'>): number {
  return s.loopEnd > s.loopStart ? s.loopEnd - s.loopStart : 0
}

/** Positions at or past `loopEnd` wrap back into the loop; positions before the loop are untouched. */
export function wrapIntoLoop(pos: number, loopStart: number, loopEnd: number): number {
  const len = loopEnd - loopStart
  if (len <= 0 || pos < loopEnd) return pos
  return loopStart + ((pos - loopStart) % len)
}

/** Source position of a segment at context time `t` (`t` should be >= seg.output). */
export function positionInSegment(seg: Segment, t: number): number {
  const raw = seg.input + (seg.active ? (t - seg.output) * seg.rate : 0)
  return wrapIntoLoop(raw, seg.loopStart, seg.loopEnd)
}

/** Index of the segment in effect at context time `t` (the last with output <= t; the first if none). */
export function segmentIndexAt(segments: readonly Segment[], t: number): number {
  let lo = 0
  let hi = segments.length - 1
  let ans = 0
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (segments[mid].output <= t) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans
}

export function segmentAt(segments: readonly Segment[], t: number): Segment {
  return segments.length ? segments[segmentIndexAt(segments, t)] : INITIAL_SEGMENT
}

/** posição(t) = seg.input + (seg.active ? (t − seg.output) × seg.rate : 0), wrapped into the loop. */
export function positionAt(segments: readonly Segment[], t: number): number {
  return positionInSegment(segmentAt(segments, t), t)
}

export type SegmentChange = Partial<Omit<Segment, 'output'>>

/**
 * Adds a segment at context time `at`, mirroring the worklet's `schedule()`:
 * segments with output >= `now` (not yet started) are discarded, then the new segment
 * is appended. Fields not in `change` — and `input`, the position at `at` — are taken
 * from the list *including* those pending segments, so quick successive changes
 * (seek, then speed) compose instead of undoing each other. Old history (segments
 * superseded more than `keepHistory` seconds before `now`) is dropped.
 */
export function scheduleSegment(
  segments: readonly Segment[],
  now: number,
  at: number,
  change: SegmentChange,
  keepHistory = 2,
): { segments: Segment[]; segment: Segment } {
  const base = segmentAt(segments, at)
  const kept = segments.filter((s) => s.output < now)
  const seg: Segment = {
    rate: base.rate,
    active: base.active,
    semitones: base.semitones,
    loopStart: base.loopStart,
    loopEnd: base.loopEnd,
    input: segments.length ? positionInSegment(base, Math.max(at, base.output)) : base.input,
    ...change,
    output: at,
  }
  let first = 0
  while (first + 1 < kept.length && kept[first + 1].output <= now - keepHistory) first++
  return { segments: [...kept.slice(first), seg], segment: seg }
}

/** Context time at which beat `b` (source time) plays within a segment, ignoring loops. */
export function beatToContextTime(seg: Segment, b: number): number {
  return seg.output + (b - seg.input) / seg.rate
}

export interface Click {
  /** Context time (without the user's offset). */
  time: number
  beatIndex: number
}

/** First index i with arr[i] >= x. */
function lowerBound(arr: readonly number[], x: number): number {
  let lo = 0
  let hi = arr.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (arr[mid] < x) lo = mid + 1
    else hi = mid
  }
  return lo
}

/**
 * Beats (sorted source times) that are heard in context-time window [from, to),
 * across all segments and loop repetitions:
 * time = seg.output + (b − seg.input) / seg.rate (+ k × loopLength / rate after wrapping).
 */
export function clicksInWindow(segments: readonly Segment[], beats: readonly number[], from: number, to: number): Click[] {
  const out: Click[] = []
  if (!beats.length || to <= from) return out
  const startIdx = segmentIndexAt(segments, from)

  for (let i = startIdx; i < segments.length; i++) {
    const seg = segments[i]
    const segEnd = i + 1 < segments.length ? segments[i + 1].output : Infinity
    const lo = Math.max(from, seg.output)
    const hi = Math.min(to, segEnd)
    if (seg.output >= to) break
    if (hi <= lo || !seg.active || seg.rate <= 0) continue

    // Emits beats in source range [srcStart, srcEnd) played from context time ctxStart.
    const emit = (ctxStart: number, srcStart: number, srcEnd: number) => {
      const srcLo = Math.max(srcStart, srcStart + (lo - ctxStart) * seg.rate)
      const srcHi = Math.min(srcEnd, srcStart + (hi - ctxStart) * seg.rate)
      if (srcHi <= srcLo) return
      for (let j = lowerBound(beats, srcLo); j < beats.length && beats[j] < srcHi; j++) {
        const time = ctxStart + (beats[j] - srcStart) / seg.rate
        if (time >= lo && time < hi) out.push({ time, beatIndex: j })
      }
    }

    const len = loopLength(seg)
    const input = wrapIntoLoop(seg.input, seg.loopStart, seg.loopEnd)
    if (len <= 0) {
      emit(seg.output, input, Infinity)
      continue
    }
    // First pass: from the segment's input up to the loop end.
    emit(seg.output, input, seg.loopEnd)
    // Repetitions of the loop body.
    const t0 = seg.output + (seg.loopEnd - input) / seg.rate
    const period = len / seg.rate
    let k = Math.max(0, Math.floor((lo - t0) / period))
    for (; t0 + k * period < hi; k++) {
      emit(t0 + k * period, seg.loopStart, seg.loopEnd)
    }
  }
  out.sort((a, b) => a.time - b.time)
  return out
}
