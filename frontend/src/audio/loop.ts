/**
 * A-B loop editing rules (§9.2), as pure functions.
 * A draft may have only one end; it can only be enabled with both.
 */
export interface LoopDraft {
  a: number | null
  b: number | null
  enabled: boolean
}

export const MIN_LOOP_S = 0.5
export const EMPTY_LOOP: LoopDraft = { a: null, b: null, enabled: false }

const complete = (l: LoopDraft): l is LoopDraft & { a: number; b: number } => l.a !== null && l.b !== null

/** `[`: set A at `pos`. Inverting the order clears B; a valid order with B − A < 0.5 s is ignored. */
export function setLoopA(loop: LoopDraft, pos: number): LoopDraft {
  if (loop.b !== null && pos >= loop.b) return { a: pos, b: null, enabled: false }
  if (loop.b !== null && loop.b - pos < MIN_LOOP_S) return loop
  return { ...loop, a: pos, enabled: loop.b !== null && loop.enabled }
}

/** `]`: set B at `pos`. Inverting the order clears A; a valid order with B − A < 0.5 s is ignored. */
export function setLoopB(loop: LoopDraft, pos: number): LoopDraft {
  if (loop.a !== null && pos <= loop.a) return { a: null, b: pos, enabled: false }
  if (loop.a !== null && pos - loop.a < MIN_LOOP_S) return loop
  return { ...loop, b: pos, enabled: loop.a !== null && loop.enabled }
}

/** Drag on the ruler / saved loop: sets both ends at once (ignored when shorter than 0.5 s). */
export function setLoopRange(loop: LoopDraft, start: number, end: number, enabled = true): LoopDraft {
  const a = Math.min(start, end)
  const b = Math.max(start, end)
  if (b - a < MIN_LOOP_S) return loop
  return { a, b, enabled }
}

/**
 * `L`: toggles the loop. No-op without both ends. When enabling with the playhead
 * outside [A, B), `seekTo` tells the caller to jump to A.
 */
export function toggleLoop(loop: LoopDraft, position: number): { loop: LoopDraft; seekTo: number | null } {
  if (!complete(loop)) return { loop, seekTo: null }
  if (loop.enabled) return { loop: { ...loop, enabled: false }, seekTo: null }
  const outside = position < loop.a || position >= loop.b
  return { loop: { ...loop, enabled: true }, seekTo: outside ? loop.a : null }
}

/** With the loop on, a seek outside [A, B] turns it off. */
export function loopAfterSeek(loop: LoopDraft, target: number): LoopDraft {
  if (!loop.enabled || !complete(loop)) return loop
  if (target < loop.a || target > loop.b) return { ...loop, enabled: false }
  return loop
}

export function isLoopActive(loop: LoopDraft): loop is { a: number; b: number; enabled: true } {
  return loop.enabled && complete(loop)
}

/** `player_state.loop`: null unless both ends exist. */
export function loopToPersisted(loop: LoopDraft): { a: number; b: number; enabled: boolean } | null {
  return complete(loop) ? { a: loop.a, b: loop.b, enabled: loop.enabled } : null
}
