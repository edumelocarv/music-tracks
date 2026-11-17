import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { ChordSegment, Marker, Peaks, StemName } from '../api/types'
import type { LoopDraft } from '../audio/loop'
import type { FullPlayerState } from '../audio/playerState'
import { cx } from '../components/ui'
import { useT } from '../i18n'
import { useLatest } from '../lib/hooks'
import { STEM_COLORS } from '../lib/stems'
import { drawChords, drawRuler, drawWaveform, setupCanvas, timeToX, xToTime, type View } from './drawing'

const RULER_H = 24
const CHORD_H = 28
const STRIP_W = 232

export interface TracksProps {
  stems: StemName[]
  peaks: Peaks | undefined
  view: View
  duration: number
  downbeats: readonly number[]
  chords: readonly ChordSegment[] | null
  semitones: number
  loop: LoopDraft
  markers: readonly Marker[]
  gains: Record<string, number>
  state: FullPlayerState
  disabled: boolean
  getPosition: () => number
  onFrame: (pos: number) => void
  onSeek: (t: number) => void
  onLoopDrag: (a: number, b: number) => void
  onVolume: (stem: StemName, v: number) => void
  onMute: (stem: StemName) => void
  onSolo: (stem: StemName) => void
  onMaster: (v: number) => void
}

export function Tracks(props: TracksProps) {
  const m = useT()
  const { stems, state, gains } = props
  const laneH = stems.length > 4 ? 58 : 72
  const laneRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    const el = laneRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const chordRow = props.chords !== null
  const headerH = RULER_H + (chordRow ? CHORD_H : 0)
  const totalH = headerH + stems.length * laneH

  return (
    <div className="flex overflow-hidden rounded-xl border border-line bg-panel">
      {/* Mixer strips */}
      <div className="shrink-0 border-r border-line bg-panel-2" style={{ width: STRIP_W }}>
        <div className="flex items-end border-b border-line px-3 pb-1 text-[10px] font-semibold tracking-wider text-faint uppercase" style={{ height: headerH }}>
          {chordRow && <span className="mb-[3px]">{m.player.chord}</span>}
        </div>
        {stems.map((s) => (
          <ChannelStrip
            key={s}
            stem={s}
            height={laneH}
            volume={state.volumes[s] ?? 100}
            muted={!!state.mutes[s]}
            soloed={!!state.solos[s]}
            silent={(gains[s] ?? 1) === 0}
            onVolume={(v) => props.onVolume(s, v)}
            onMute={() => props.onMute(s)}
            onSolo={() => props.onSolo(s)}
          />
        ))}
        <div className="flex h-12 items-center gap-3 border-t border-line-strong px-3">
          <span className="w-14 text-[11px] font-semibold tracking-wider text-muted uppercase">{m.player.master}</span>
          <Fader value={state.master} onChange={props.onMaster} color="#e6e8eb" label={m.player.master} />
          <span className="w-8 text-right text-[11px] text-muted tabular-nums">{state.master}</span>
        </div>
      </div>

      {/* Lanes */}
      <div ref={laneRef} className="relative min-w-0 flex-1" style={{ height: totalH + 48 }}>
        {width > 0 && (
          <>
            <RulerCanvas view={props.view} width={width} />
            {chordRow && <ChordCanvas chords={props.chords!} semitones={props.semitones} view={props.view} width={width} top={RULER_H} />}
            {stems.map((s, i) => (
              <LaneCanvas
                key={s}
                peaks={props.peaks?.stems[s]}
                pps={props.peaks ? props.peaks.sample_rate / props.peaks.samples_per_peak : 1}
                view={props.view}
                width={width}
                height={laneH}
                top={headerH + i * laneH}
                color={STEM_COLORS[s]}
                dimmed={(gains[s] ?? 1) === 0}
                downbeats={props.downbeats}
              />
            ))}
            <Overlay {...props} width={width} height={totalH} />
          </>
        )}
        <div className="absolute inset-x-0 bottom-0 h-12 border-t border-line-strong bg-panel-2" />
      </div>
    </div>
  )
}

function Fader({ value, onChange, color, label, disabled }: { value: number; onChange: (v: number) => void; color: string; label: string; disabled?: boolean }) {
  return (
    <input
      type="range"
      className="fader min-w-0 flex-1"
      min={0}
      max={100}
      step={1}
      value={value}
      disabled={disabled}
      aria-label={label}
      title={`${label}: ${value}%`}
      onChange={(e) => onChange(Number(e.target.value))}
      onDoubleClick={() => onChange(100)}
      style={{ ['--pct' as string]: `${value}%`, ['--fill' as string]: color }}
    />
  )
}

function ChannelStrip(p: {
  stem: StemName
  height: number
  volume: number
  muted: boolean
  soloed: boolean
  silent: boolean
  onVolume: (v: number) => void
  onMute: () => void
  onSolo: () => void
}) {
  const m = useT()
  const color = STEM_COLORS[p.stem]
  return (
    <div className="flex flex-col justify-center gap-1.5 border-b border-line px-3" style={{ height: p.height }}>
      <div className="flex items-center gap-2">
        <span className="h-3.5 w-1 rounded-full" style={{ background: color, opacity: p.silent ? 0.35 : 1 }} />
        <span className={cx('flex-1 truncate text-[13px] font-medium', p.silent && 'text-faint')}>{m.stems[p.stem]}</span>
        <button
          type="button"
          onClick={p.onMute}
          title={m.player.mute}
          aria-pressed={p.muted}
          className={cx(
            'h-6 w-6 rounded text-[11px] font-bold transition-colors',
            p.muted ? 'bg-red-500/80 text-white' : 'bg-raised text-muted hover:text-fg',
          )}
        >
          M
        </button>
        <button
          type="button"
          onClick={p.onSolo}
          title={m.player.solo}
          aria-pressed={p.soloed}
          className={cx(
            'h-6 w-6 rounded text-[11px] font-bold transition-colors',
            p.soloed ? 'bg-amber-400 text-black' : 'bg-raised text-muted hover:text-fg',
          )}
        >
          S
        </button>
      </div>
      <div className="flex items-center gap-2 pl-3">
        <Fader value={p.volume} onChange={p.onVolume} color={color} label={`${m.player.volume} ${m.stems[p.stem]}`} />
        <span className="w-7 text-right text-[11px] text-muted tabular-nums">{p.volume}</span>
      </div>
    </div>
  )
}

function RulerCanvas({ view, width }: { view: View; width: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const ctx = ref.current && setupCanvas(ref.current, width, RULER_H)
    if (ctx) drawRuler(ctx, view, width, RULER_H)
  }, [view, width])
  return <canvas ref={ref} className="absolute top-0 left-0" style={{ width, height: RULER_H }} />
}

function ChordCanvas({ chords, semitones, view, width, top }: { chords: readonly ChordSegment[]; semitones: number; view: View; width: number; top: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const ctx = ref.current && setupCanvas(ref.current, width, CHORD_H)
    if (!ctx) return
    ctx.fillStyle = '#15171b'
    ctx.fillRect(0, 0, width, CHORD_H)
    drawChords(ctx, chords, semitones, view, width, CHORD_H)
    ctx.fillStyle = '#2a2e35'
    ctx.fillRect(0, CHORD_H - 1, width, 1)
  }, [chords, semitones, view, width])
  return <canvas ref={ref} className="absolute left-0" style={{ top, width, height: CHORD_H }} />
}

function LaneCanvas(p: {
  peaks: number[] | undefined
  pps: number
  view: View
  width: number
  height: number
  top: number
  color: string
  dimmed: boolean
  downbeats: readonly number[]
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  const { peaks, pps, view, width, height, color, dimmed, downbeats } = p
  useEffect(() => {
    const ctx = ref.current && setupCanvas(ref.current, width, height)
    if (!ctx) return
    drawWaveform(ctx, peaks, pps, view, width, height - 1, color, dimmed, downbeats)
    ctx.fillStyle = '#2a2e35'
    ctx.fillRect(0, height - 1, width, 1)
  }, [peaks, pps, view, width, height, color, dimmed, downbeats])
  return <canvas ref={ref} className="absolute left-0" style={{ top: p.top, width, height }} />
}

/** Playhead, A-B region, markers and ruler-drag selection; redrawn every animation frame. */
function Overlay(p: TracksProps & { width: number; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const latest = useLatest(p)
  const drag = useRef<{ x0: number; x: number; ruler: boolean; moved: boolean } | null>(null)

  useEffect(() => {
    let raf = 0
    const frame = () => {
      raf = requestAnimationFrame(frame)
      const c = ref.current
      const q = latest.current
      if (!c) return
      const ctx = setupCanvas(c, q.width, q.height)
      if (!ctx) return
      const { view, width, height, loop } = q
      // A-B region
      if (loop.a !== null && loop.b !== null) {
        const x0 = timeToX(loop.a, view, width)
        const x1 = timeToX(loop.b, view, width)
        ctx.fillStyle = loop.enabled ? 'rgba(139,156,255,0.14)' : 'rgba(255,255,255,0.05)'
        ctx.fillRect(x0, 0, x1 - x0, height)
        ctx.fillStyle = loop.enabled ? 'rgba(139,156,255,0.75)' : 'rgba(255,255,255,0.3)'
        ctx.fillRect(x0, 0, x1 - x0, 3)
      }
      ctx.font = '600 10px Inter, ui-sans-serif, system-ui, sans-serif'
      ctx.textBaseline = 'top'
      for (const [t, label] of [
        [loop.a, 'A'],
        [loop.b, 'B'],
      ] as const) {
        if (t === null) continue
        const x = Math.round(timeToX(t, view, width))
        ctx.fillStyle = loop.enabled ? '#8b9cff' : '#9aa1ab'
        ctx.fillRect(x, 0, 1, height)
        ctx.fillRect(label === 'A' ? x : x - 12, 0, 12, 13)
        ctx.fillStyle = '#0e0f12'
        ctx.fillText(label, label === 'A' ? x + 3 : x - 9, 2)
      }
      // Markers
      for (const mk of q.markers) {
        if (mk.kind !== 'marker') continue
        const x = Math.round(timeToX(mk.start_s, view, width)) + 0.5
        if (x < -100 || x > width + 2) continue
        ctx.strokeStyle = 'rgba(251,191,36,0.7)'
        ctx.setLineDash([3, 3])
        ctx.beginPath()
        ctx.moveTo(x, RULER_H)
        ctx.lineTo(x, height)
        ctx.stroke()
        ctx.setLineDash([])
        const tw = Math.min(110, ctx.measureText(mk.name).width + 8)
        ctx.fillStyle = 'rgba(251,191,36,0.9)'
        ctx.fillRect(x, RULER_H - 13, tw, 13)
        ctx.save()
        ctx.beginPath()
        ctx.rect(x, RULER_H - 13, tw, 13)
        ctx.clip()
        ctx.fillStyle = '#1a1405'
        ctx.fillText(mk.name, x + 4, RULER_H - 11)
        ctx.restore()
      }
      // Drag selection on the ruler
      const d = drag.current
      if (d && d.ruler && d.moved) {
        ctx.fillStyle = 'rgba(139,156,255,0.22)'
        ctx.fillRect(Math.min(d.x0, d.x), 0, Math.abs(d.x - d.x0), height)
      }
      // Playhead
      const pos = q.getPosition()
      const px = Math.round(timeToX(pos, view, width))
      if (px >= -1 && px <= width + 1) {
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(px, 0, 1.5, height)
        ctx.beginPath()
        ctx.moveTo(px - 5, 0)
        ctx.lineTo(px + 6.5, 0)
        ctx.lineTo(px + 0.75, 7)
        ctx.closePath()
        ctx.fill()
      }
      q.onFrame(pos)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [latest])

  const localX = (e: ReactPointerEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return Math.max(0, Math.min(r.width, e.clientX - r.left))
  }

  return (
    <canvas
      ref={ref}
      className={cx('absolute top-0 left-0', p.disabled ? 'cursor-default' : 'cursor-text')}
      style={{ width: p.width, height: p.height }}
      onPointerDown={(e) => {
        if (p.disabled || e.button !== 0) return
        const r = e.currentTarget.getBoundingClientRect()
        const x = localX(e)
        drag.current = { x0: x, x, ruler: e.clientY - r.top < RULER_H, moved: false }
        e.currentTarget.setPointerCapture(e.pointerId)
      }}
      onPointerMove={(e) => {
        const d = drag.current
        if (!d) return
        d.x = localX(e)
        if (Math.abs(d.x - d.x0) > 4) d.moved = true
      }}
      onPointerUp={(e) => {
        const d = drag.current
        drag.current = null
        if (!d) return
        const { view, width, duration } = latest.current
        const clampT = (t: number) => Math.max(0, Math.min(duration, t))
        if (d.ruler && d.moved) {
          p.onLoopDrag(clampT(xToTime(d.x0, view, width)), clampT(xToTime(localX(e), view, width)))
        } else {
          p.onSeek(clampT(xToTime(localX(e), view, width)))
        }
      }}
      onPointerCancel={() => {
        drag.current = null
      }}
    />
  )
}
