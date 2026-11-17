import type { StretchNode } from 'signalsmith-stretch'
import { clicksInWindow, INITIAL_SEGMENT, positionInSegment, scheduleSegment, segmentAt, type Segment } from './timeline'

/**
 * Multitrack player (§9.1): all stems live in ONE signalsmith-stretch node with 2N output
 * channels → ChannelSplitter(2N) → per-stem ChannelMerger(2) + GainNode → master → destination.
 * Every playback change is a segment scheduled at `currentTime + latency`; the same segment
 * list is mirrored here (see timeline.ts) to compute the position and metronome clicks.
 */

export const SAMPLE_RATE = 44100
const SCHEDULER_INTERVAL_MS = 25
const LOOKAHEAD_S = 0.2
const CLICK_S = 0.03

export interface EngineLoadOptions {
  urls: string[]
  /** Duration hint (s) to pre-allocate channel arrays. */
  durationHint?: number | null
  onProgress?: (loaded: number, total: number) => void
  signal?: AbortSignal
}

export interface TransportState {
  playing: boolean
  rate: number
  semitones: number
  /** Active loop, or null. */
  loop: { a: number; b: number } | null
}

interface ScheduledClick {
  src: AudioBufferSourceNode
  /** Beat context time without the user offset. */
  beatTime: number
}

export class StemEngine {
  readonly ctx: AudioContext
  readonly node: StretchNode
  readonly duration: number
  readonly stemCount: number
  private readonly latency: number
  private readonly stemGains: GainNode[]
  private readonly master: GainNode
  private readonly clickGain: GainNode
  private readonly clickBuffers: { accent: AudioBuffer; normal: AudioBuffer }
  private segments: Segment[] = [{ ...INITIAL_SEGMENT }]
  private state: TransportState = { playing: false, rate: 1, semitones: 0, loop: null }
  private timer: ReturnType<typeof setInterval> | null = null
  private disposed = false

  // metronome
  private beats: number[] = []
  private downbeat: boolean[] = []
  private metronomeOn = false
  private offsetS = 0
  private scheduledUntil = -Infinity
  private clicks: ScheduledClick[] = []

  /** Called when playback stops by itself at the end of the song. */
  onEnded: (() => void) | null = null

  private constructor(ctx: AudioContext, node: StretchNode, stemCount: number, duration: number, latency: number) {
    this.ctx = ctx
    this.node = node
    this.stemCount = stemCount
    this.duration = duration
    this.latency = latency

    const splitter = ctx.createChannelSplitter(2 * stemCount)
    node.connect(splitter)
    this.master = ctx.createGain()
    this.master.connect(ctx.destination)
    this.stemGains = []
    for (let i = 0; i < stemCount; i++) {
      const merger = ctx.createChannelMerger(2)
      splitter.connect(merger, 2 * i, 0)
      splitter.connect(merger, 2 * i + 1, 1)
      const g = ctx.createGain()
      merger.connect(g)
      g.connect(this.master)
      this.stemGains.push(g)
    }
    // Metronome clicks bypass the stretcher (§9.3).
    this.clickGain = ctx.createGain()
    this.clickGain.connect(ctx.destination)
    this.clickBuffers = { accent: makeClick(ctx, 1500), normal: makeClick(ctx, 1000) }
    this.timer = setInterval(() => this.tick(), SCHEDULER_INTERVAL_MS)
  }

  /** Downloads and decodes the stems one at a time, then builds the graph. */
  static async load(opts: EngineLoadOptions): Promise<StemEngine> {
    const { urls, signal } = opts
    const n = urls.length
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE, latencyHint: 'playback' })
    try {
      opts.onProgress?.(0, n)
      let capacity = Math.max(1, Math.ceil((opts.durationHint ?? 0) * SAMPLE_RATE) + SAMPLE_RATE)
      let chans: Float32Array[] = Array.from({ length: 2 * n }, () => new Float32Array(capacity))
      let maxLen = 0
      for (let i = 0; i < n; i++) {
        const res = await fetch(urls[i], { signal })
        if (!res.ok) throw new Error(`HTTP ${res.status} for ${urls[i]}`)
        const encoded = await res.arrayBuffer()
        signal?.throwIfAborted()
        const decoded = await ctx.decodeAudioData(encoded)
        signal?.throwIfAborted()
        if (decoded.length > capacity) {
          // Rare: grow the pre-allocated arrays.
          capacity = decoded.length
          chans = chans.map((c) => {
            const grown = new Float32Array(capacity)
            grown.set(c)
            return grown
          })
        }
        const left = decoded.getChannelData(0)
        const right = decoded.numberOfChannels > 1 ? decoded.getChannelData(1) : left
        chans[2 * i].set(left)
        chans[2 * i + 1].set(right)
        maxLen = Math.max(maxLen, decoded.length)
        opts.onProgress?.(i + 1, n)
      }
      // Length = longest decoded stem (the rest stays zero).
      const views = chans.map((c) => c.subarray(0, maxLen))
      // Lazy-loaded: the package inlines its WASM (~110 kB).
      const { default: SignalsmithStretch } = await import('signalsmith-stretch')
      const node = await SignalsmithStretch(ctx, {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [2 * n],
      })
      signal?.throwIfAborted()
      // One call with all 2N channels; the buffers are transferred (no copy).
      await node.addBuffers(views, views.map((c) => c.buffer))
      const latency = await node.latency()
      const engine = new StemEngine(ctx, node, n, maxLen / SAMPLE_RATE, latency)
      engine.applyState({}, 0)
      return engine
    } catch (err) {
      void ctx.close().catch(() => undefined)
      throw err
    }
  }

  // ---------- transport ----------

  get playing(): boolean {
    return this.state.playing
  }

  /** Context time of what is being heard right now (for the visual playhead). */
  heardTime(): number {
    const ctx = this.ctx
    const ts = ctx.getOutputTimestamp?.()
    if (ts && typeof ts.contextTime === 'number' && typeof ts.performanceTime === 'number' && ts.contextTime > 0) {
      const extrapolated = ts.contextTime + (performance.now() - ts.performanceTime) / 1000
      return Math.min(ctx.currentTime, Math.max(ts.contextTime, extrapolated))
    }
    return Math.max(0, ctx.currentTime - (ctx.outputLatency || ctx.baseLatency || 0))
  }

  /** Source position currently heard (seconds). */
  position(): number {
    const t = this.heardTime()
    return clampPos(positionInSegment(segmentAt(this.segments, t), t), this.duration)
  }

  /**
   * Applies a transport change as one scheduled segment.
   * `position` seeks; omitted keeps the current (scheduled) position.
   */
  applyState(change: Partial<TransportState>, position?: number): void {
    if (this.disposed) return
    this.state = { ...this.state, ...change }
    const { playing, rate, semitones, loop } = this.state
    const now = this.ctx.currentTime
    const at = now + this.latency
    // Pending segments discarded by this change may already have clicks scheduled.
    const firstDiscarded = this.segments.reduce((m, sg) => (sg.output >= now ? Math.min(m, sg.output) : m), at)
    const { segments, segment } = scheduleSegment(this.segments, now, at, {
      active: playing,
      rate,
      semitones,
      loopStart: loop ? loop.a : 0,
      loopEnd: loop ? loop.b : 0,
      ...(position !== undefined ? { input: clampPos(position, this.duration) } : {}),
    })
    this.segments = segments
    void this.node.schedule({
      output: segment.output,
      input: segment.input,
      rate: segment.rate,
      active: segment.active,
      semitones: segment.semitones,
      loopStart: segment.loopStart,
      loopEnd: segment.loopEnd,
    })
    this.rescheduleClicksFrom(Math.min(firstDiscarded, segment.output))
  }

  async play(): Promise<void> {
    if (this.ctx.state !== 'running') await this.ctx.resume()
    let pos: number | undefined
    if (!this.state.loop && this.position() >= this.duration - 0.05) pos = 0
    this.applyState({ playing: true }, pos)
  }

  pause(): void {
    this.applyState({ playing: false })
  }

  seek(position: number): void {
    this.applyState({}, position)
  }

  // ---------- mixer ----------

  setStemGains(gains: number[]): void {
    const t = this.ctx.currentTime
    gains.forEach((g, i) => this.stemGains[i]?.gain.setTargetAtTime(g, t, 0.01))
  }

  setMaster(gain: number): void {
    this.master.gain.setTargetAtTime(gain, this.ctx.currentTime, 0.01)
  }

  // ---------- metronome ----------

  setBeats(beats: number[], downbeats: number[]): void {
    this.beats = [...beats].sort((a, b) => a - b)
    const db = [...downbeats].sort((a, b) => a - b)
    let j = 0
    this.downbeat = this.beats.map((b) => {
      while (j < db.length && db[j] < b - 0.05) j++
      return j < db.length && Math.abs(db[j] - b) <= 0.05
    })
    this.resetClicks()
  }

  setMetronome(enabled: boolean, volume: number, offsetMs: number): void {
    this.clickGain.gain.setTargetAtTime(Math.max(0, Math.min(1, volume / 100)), this.ctx.currentTime, 0.01)
    const offset = offsetMs / 1000
    if (enabled !== this.metronomeOn || offset !== this.offsetS) {
      this.metronomeOn = enabled
      this.offsetS = offset
      this.resetClicks()
    }
  }

  private resetClicks() {
    this.rescheduleClicksFrom(-Infinity)
    this.scheduledUntil = -Infinity
  }

  /** Cancels clicks of beats at/after `from` (context time) so the scheduler recomputes them. */
  private rescheduleClicksFrom(from: number) {
    this.clicks = this.clicks.filter((c) => {
      if (c.beatTime >= from) {
        try {
          c.src.stop()
        } catch {
          // not started
        }
        c.src.disconnect()
        return false
      }
      return true
    })
    this.scheduledUntil = Math.min(this.scheduledUntil, from)
  }

  private tick() {
    if (this.disposed) return
    const now = this.ctx.currentTime
    // End of song (no loop): pause and return to 0.
    // Only while the heard segment is itself playing (not a paused one still in the latency window).
    const heard = this.heardTime()
    const seg = segmentAt(this.segments, heard)
    if (this.state.playing && !this.state.loop && seg.active && positionInSegment(seg, heard) >= this.duration - 0.01) {
      this.applyState({ playing: false }, 0)
      this.onEnded?.()
    }
    if (!this.metronomeOn || !this.beats.length || this.ctx.state !== 'running') return
    // Window in beat time (without offset) such that click times fall in [now, now + lookahead).
    const from = Math.max(this.scheduledUntil, now - this.offsetS)
    const to = now + LOOKAHEAD_S - this.offsetS
    if (to <= from) return
    for (const c of clicksInWindow(this.segments, this.beats, from, to)) {
      const when = c.time + this.offsetS
      if (when < now) continue
      const src = this.ctx.createBufferSource()
      src.buffer = this.downbeat[c.beatIndex] ? this.clickBuffers.accent : this.clickBuffers.normal
      src.connect(this.clickGain)
      src.start(when)
      const rec: ScheduledClick = { src, beatTime: c.time }
      src.onended = () => {
        src.disconnect()
        this.clicks = this.clicks.filter((x) => x !== rec)
      }
      this.clicks.push(rec)
    }
    this.scheduledUntil = to
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    if (this.timer) clearInterval(this.timer)
    this.rescheduleClicksFrom(-Infinity)
    try {
      this.node.disconnect()
      void this.node.dropBuffers()
    } catch {
      // ignore
    }
    void this.ctx.close().catch(() => undefined)
  }
}

function clampPos(p: number, duration: number): number {
  if (!Number.isFinite(p) || p < 0) return 0
  return Math.min(p, duration)
}

/** Short sine click (30 ms) with a fast attack and exponential-ish decay. */
function makeClick(ctx: BaseAudioContext, freq: number): AudioBuffer {
  const len = Math.round(CLICK_S * ctx.sampleRate)
  const buf = ctx.createBuffer(1, len, ctx.sampleRate)
  const d = buf.getChannelData(0)
  const attack = Math.round(0.002 * ctx.sampleRate)
  for (let i = 0; i < len; i++) {
    const env = i < attack ? i / attack : Math.pow(1 - (i - attack) / (len - attack), 2)
    d[i] = Math.sin((2 * Math.PI * freq * i) / ctx.sampleRate) * env * 0.8
  }
  return buf
}
