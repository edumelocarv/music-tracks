import type { ChordSegment } from '../api/types'
import { displayChord } from '../music/theory'

export interface View {
  start: number
  span: number
}

/** Prepares a canvas for its CSS size × devicePixelRatio; returns the 2D context in CSS pixels. */
export function setupCanvas(canvas: HTMLCanvasElement, width: number, height: number): CanvasRenderingContext2D | null {
  const dpr = window.devicePixelRatio || 1
  const w = Math.max(1, Math.round(width * dpr))
  const h = Math.max(1, Math.round(height * dpr))
  if (canvas.width !== w) canvas.width = w
  if (canvas.height !== h) canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)
  return ctx
}

export const timeToX = (t: number, view: View, width: number) => ((t - view.start) / view.span) * width
export const xToTime = (x: number, view: View, width: number) => view.start + (x / width) * view.span

/** Draws a stem waveform from peaks ([min0, max0, min1, max1, ...] in −127..127). */
export function drawWaveform(
  ctx: CanvasRenderingContext2D,
  peaks: number[] | undefined,
  peaksPerSecond: number,
  view: View,
  width: number,
  height: number,
  color: string,
  dimmed: boolean,
  downbeats: readonly number[],
) {
  // Downbeat (bar) grid behind the waveform.
  ctx.fillStyle = 'rgba(255,255,255,0.05)'
  for (const d of downbeats) {
    if (d < view.start || d > view.start + view.span) continue
    ctx.fillRect(Math.round(timeToX(d, view, width)), 0, 1, height)
  }
  const mid = height / 2
  ctx.fillStyle = 'rgba(255,255,255,0.06)'
  ctx.fillRect(0, Math.round(mid), width, 1)
  if (!peaks || !peaks.length) return
  const n = peaks.length / 2
  const scale = (height / 2 - 2) / 127
  ctx.fillStyle = color
  ctx.globalAlpha = dimmed ? 0.22 : 0.9
  const dpr = window.devicePixelRatio || 1
  const step = 1 / dpr
  for (let x = 0; x < width; x += step) {
    const t0 = view.start + (x / width) * view.span
    const t1 = view.start + ((x + step) / width) * view.span
    let i0 = Math.floor(t0 * peaksPerSecond)
    let i1 = Math.floor(t1 * peaksPerSecond)
    if (i0 >= n || i1 < 0) continue
    i0 = Math.max(0, i0)
    i1 = Math.min(n - 1, Math.max(i0, i1))
    let lo = 127
    let hi = -127
    for (let i = i0; i <= i1; i++) {
      const a = peaks[2 * i]
      const b = peaks[2 * i + 1]
      if (a < lo) lo = a
      if (b > hi) hi = b
    }
    if (hi < lo) continue
    const y0 = mid - hi * scale
    const y1 = mid - lo * scale
    ctx.fillRect(x, y0, step, Math.max(step, y1 - y0))
  }
  ctx.globalAlpha = 1
}

/** Time ruler with adaptive tick spacing. */
export function drawRuler(ctx: CanvasRenderingContext2D, view: View, width: number, height: number) {
  ctx.fillStyle = '#1b1e23'
  ctx.fillRect(0, 0, width, height)
  const pxPerSec = width / view.span
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60]
  const major = steps.find((s) => s * pxPerSec >= 70) ?? 120
  const minor = major / (major >= 10 ? 5 : 2)
  ctx.font = '10px ui-monospace, Menlo, monospace'
  ctx.textBaseline = 'top'
  const start = Math.floor(view.start / minor) * minor
  for (let t = start; t <= view.start + view.span; t += minor) {
    const x = Math.round(timeToX(t, view, width)) + 0.5
    const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6
    ctx.fillStyle = isMajor ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.14)'
    ctx.fillRect(x, isMajor ? height - 9 : height - 5, 1, isMajor ? 9 : 5)
    if (isMajor && t >= 0) {
      ctx.fillStyle = '#9aa1ab'
      const m = Math.floor(t / 60)
      const s = t - m * 60
      ctx.fillText(`${m}:${(major < 1 ? s.toFixed(1) : Math.round(s).toString()).padStart(major < 1 ? 4 : 2, '0')}`, x + 3, 3)
    }
  }
  ctx.fillStyle = '#2a2e35'
  ctx.fillRect(0, height - 1, width, 1)
}

/** Chord lane: one block per chord segment, labels transposed. */
export function drawChords(
  ctx: CanvasRenderingContext2D,
  chords: readonly ChordSegment[],
  semitones: number,
  view: View,
  width: number,
  height: number,
) {
  ctx.font = '600 11px Inter, ui-sans-serif, system-ui, sans-serif'
  ctx.textBaseline = 'middle'
  const end = view.start + view.span
  let alt = false
  for (const c of chords) {
    alt = !alt
    if (c.end < view.start || c.start > end) continue
    const x0 = timeToX(c.start, view, width)
    const x1 = timeToX(c.end, view, width)
    const none = c.label === 'N'
    ctx.fillStyle = none ? 'rgba(255,255,255,0.015)' : alt ? 'rgba(139,156,255,0.13)' : 'rgba(139,156,255,0.08)'
    ctx.fillRect(x0 + 0.5, 3, Math.max(0, x1 - x0 - 1), height - 6)
    const label = displayChord(c.label, semitones)
    const w = x1 - x0
    // Only draw labels that fit entirely (a clipped "Dm" reads as "Dn"); zooming in reveals the rest.
    const visibleW = Math.min(x1, width) - Math.max(x0, 0)
    if (visibleW >= ctx.measureText(label).width + 8) {
      ctx.save()
      ctx.beginPath()
      ctx.rect(x0, 0, w, height)
      ctx.clip()
      ctx.fillStyle = none ? '#6b727d' : '#d6dbff'
      ctx.fillText(label, Math.max(x0, 0) + 6, height / 2)
      ctx.restore()
    }
  }
}
