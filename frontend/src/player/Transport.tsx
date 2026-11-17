import { useEffect, useState, type ReactNode, type RefObject } from 'react'
import type { LoopDraft } from '../audio/loop'
import { OFFSET_MAX, OFFSET_MIN, SEMITONES_MAX, SEMITONES_MIN, SPEED_MAX, SPEED_MIN } from '../audio/playerState'
import type { MetronomeState } from '../api/types'
import { Back5Icon, Fwd5Icon, LoopIcon, MetronomeIcon, PauseIcon, PlayIcon, SkipBackIcon, XIcon } from '../components/icons'
import { cx, IconButton } from '../components/ui'
import { useT } from '../i18n'
import { formatDuration, formatTimePrecise } from '../lib/format'

export const ZOOMS = [1, 2, 4, 8] as const

export interface TransportProps {
  disabled: boolean
  playing: boolean
  duration: number
  timeRef: RefObject<HTMLSpanElement | null>
  speed: number
  semitones: number
  loop: LoopDraft
  metronome: MetronomeState
  metronomeAvailable: boolean
  zoom: number
  onPlayPause: () => void
  onToStart: () => void
  onNudge: (delta: number) => void
  onSpeed: (s: number) => void
  onSemitones: (s: number) => void
  onSetA: () => void
  onSetB: () => void
  onToggleLoop: () => void
  onClearLoop: () => void
  onSaveLoop: () => void
  onMetronome: (m: Partial<MetronomeState>) => void
  onZoom: (z: number) => void
}

const round2 = (v: number) => Math.round(v * 100) / 100

export function Transport(p: TransportProps) {
  const m = useT()
  const loopComplete = p.loop.a !== null && p.loop.b !== null
  return (
    <div className="space-y-2">
      {/* Row 1: transport + time */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-1">
          <IconButton label={m.player.toStart} onClick={p.onToStart} disabled={p.disabled}>
            <SkipBackIcon size={15} />
          </IconButton>
          <IconButton label={m.player.back5} onClick={() => p.onNudge(-5)} disabled={p.disabled}>
            <Back5Icon size={16} />
          </IconButton>
          <button
            type="button"
            onClick={p.onPlayPause}
            disabled={p.disabled}
            title={`${p.playing ? m.player.pause : m.player.play} (Space)`}
            aria-label={p.playing ? m.player.pause : m.player.play}
            className="mx-1 flex h-10 w-10 items-center justify-center rounded-full bg-fg text-bg shadow-md shadow-black/40 transition hover:scale-105 hover:bg-white disabled:opacity-40 disabled:hover:scale-100"
          >
            {p.playing ? <PauseIcon size={17} /> : <PlayIcon size={17} className="translate-x-px" />}
          </button>
          <IconButton label={m.player.fwd5} onClick={() => p.onNudge(5)} disabled={p.disabled}>
            <Fwd5Icon size={16} />
          </IconButton>
        </div>
        <div className="font-mono text-[15px] tabular-nums">
          <span ref={p.timeRef} className="text-fg">
            {formatTimePrecise(0)}
          </span>
          <span className="text-faint"> / {formatDuration(p.duration)}</span>
        </div>

        <Group label={m.player.speed}>
          <Stepper
            value={Math.round(p.speed * 100)}
            min={SPEED_MIN * 100}
            max={SPEED_MAX * 100}
            step={5}
            suffix="%"
            disabled={p.disabled}
            onChange={(v) => p.onSpeed(round2(v / 100))}
            highlight={p.speed !== 1}
            onReset={() => p.onSpeed(1)}
            resetLabel={m.player.reset}
          />
        </Group>

        <Group label={m.player.transpose}>
          <Stepper
            value={p.semitones}
            min={SEMITONES_MIN}
            max={SEMITONES_MAX}
            step={1}
            format={(v) => (v > 0 ? `+${v}` : String(v))}
            disabled={p.disabled}
            onChange={p.onSemitones}
            highlight={p.semitones !== 0}
            onReset={() => p.onSemitones(0)}
            resetLabel={m.player.reset}
          />
        </Group>
      </div>

      {/* Row 2: loop, metronome, zoom */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Group label={m.player.loop}>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={p.onToggleLoop}
              disabled={p.disabled || !loopComplete}
              title={m.player.loopToggle}
              aria-pressed={p.loop.enabled}
              className={cx(
                'flex h-7 items-center gap-1 rounded-md border px-2 text-xs font-medium transition-colors disabled:opacity-40',
                p.loop.enabled ? 'border-accent/50 bg-accent/20 text-accent' : 'border-line-strong text-muted hover:text-fg',
              )}
            >
              <LoopIcon size={13} />L
            </button>
            <PointButton label="A" title={m.player.setA} value={p.loop.a} onClick={p.onSetA} disabled={p.disabled} active={p.loop.enabled} />
            <PointButton label="B" title={m.player.setB} value={p.loop.b} onClick={p.onSetB} disabled={p.disabled} active={p.loop.enabled} />
            {(p.loop.a !== null || p.loop.b !== null) && (
              <IconButton label={m.player.clearLoop} onClick={p.onClearLoop} className="h-7 w-7">
                <XIcon size={13} />
              </IconButton>
            )}
            {loopComplete && (
              <button type="button" onClick={p.onSaveLoop} className="h-7 rounded-md px-2 text-xs text-muted hover:bg-raised hover:text-fg">
                {m.player.saveLoop}
              </button>
            )}
          </div>
        </Group>

        <Group label={m.player.metronome}>
          <div className="flex items-center gap-2" title={p.metronomeAvailable ? undefined : m.player.metronomeDisabled}>
            <button
              type="button"
              onClick={() => p.onMetronome({ enabled: !p.metronome.enabled })}
              disabled={p.disabled || !p.metronomeAvailable}
              aria-pressed={p.metronome.enabled}
              title={p.metronomeAvailable ? m.player.metronomeToggle : m.player.metronomeDisabled}
              className={cx(
                'flex h-7 items-center gap-1 rounded-md border px-2 text-xs font-medium transition-colors disabled:opacity-40',
                p.metronome.enabled ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-300' : 'border-line-strong text-muted hover:text-fg',
              )}
            >
              <MetronomeIcon size={13} />K
            </button>
            <input
              type="range"
              className="fader w-20"
              min={0}
              max={100}
              value={p.metronome.volume}
              disabled={!p.metronomeAvailable}
              aria-label={m.player.metronomeVolume}
              title={`${m.player.metronomeVolume}: ${p.metronome.volume}%`}
              onChange={(e) => p.onMetronome({ volume: Number(e.target.value) })}
              style={{ ['--pct' as string]: `${p.metronome.volume}%`, ['--fill' as string]: '#34d399' }}
            />
            <label className="flex items-center gap-1 text-[11px] text-faint" title={m.player.metronomeOffset}>
              {m.player.metronomeOffset}
              <NumberInput
                value={p.metronome.offset_ms}
                min={OFFSET_MIN}
                max={OFFSET_MAX}
                disabled={!p.metronomeAvailable}
                onChange={(v) => p.onMetronome({ offset_ms: v })}
                className="w-14"
              />
              ms
            </label>
          </div>
        </Group>

        <Group label={m.player.zoom} className="ml-auto">
          <div className="flex rounded-md border border-line-strong p-0.5">
            {ZOOMS.map((z) => (
              <button
                key={z}
                type="button"
                onClick={() => p.onZoom(z)}
                aria-pressed={p.zoom === z}
                className={cx(
                  'h-6 rounded px-2 text-xs font-medium tabular-nums transition-colors',
                  p.zoom === z ? 'bg-raised text-fg' : 'text-faint hover:text-fg',
                )}
              >
                {z}×
              </button>
            ))}
          </div>
        </Group>
      </div>
    </div>
  )
}

function Group({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx('flex items-center gap-2', className)}>
      <span className="text-[11px] font-semibold tracking-wider text-faint uppercase">{label}</span>
      {children}
    </div>
  )
}

function PointButton({ label, title, value, onClick, disabled, active }: { label: string; title: string; value: number | null; onClick: () => void; disabled: boolean; active: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cx(
        'flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors disabled:opacity-40',
        value !== null ? (active ? 'border-accent/40 text-fg' : 'border-line-strong text-fg') : 'border-dashed border-line-strong text-faint hover:text-fg',
      )}
    >
      <span className="font-bold">{label}</span>
      <span className="font-mono tabular-nums">{value !== null ? formatTimePrecise(value) : '–:––'}</span>
    </button>
  )
}

function Stepper(p: {
  value: number
  min: number
  max: number
  step: number
  suffix?: string
  format?: (v: number) => string
  disabled: boolean
  highlight: boolean
  onChange: (v: number) => void
  onReset: () => void
  resetLabel: string
}) {
  const clamp = (v: number) => Math.min(p.max, Math.max(p.min, v))
  // Buttons snap to the step grid (e.g. 87% + 5 → 90%).
  const up = () => p.onChange(clamp(Math.floor(p.value / p.step) * p.step + p.step))
  const down = () => p.onChange(clamp(Math.ceil(p.value / p.step) * p.step - p.step))
  return (
    <div className="flex items-center">
      <button
        type="button"
        onClick={down}
        disabled={p.disabled || p.value <= p.min}
        className="h-7 w-7 rounded-l-md border border-line-strong text-muted hover:bg-raised hover:text-fg disabled:opacity-40"
      >
        −
      </button>
      <div className={cx('flex h-7 items-center border-y border-line-strong px-1', p.highlight && 'bg-accent/10')}>
        <NumberInput
          value={p.value}
          min={p.min}
          max={p.max}
          disabled={p.disabled}
          onChange={(v) => p.onChange(v)}
          display={p.format}
          className={cx('w-12 border-0 bg-transparent', p.highlight && 'text-accent')}
        />
        {p.suffix && <span className="pr-1 text-xs text-faint">{p.suffix}</span>}
      </div>
      <button
        type="button"
        onClick={up}
        disabled={p.disabled || p.value >= p.max}
        className="h-7 w-7 rounded-r-md border border-line-strong text-muted hover:bg-raised hover:text-fg disabled:opacity-40"
      >
        +
      </button>
      {p.highlight && (
        <button type="button" onClick={p.onReset} title={p.resetLabel} className="ml-1 h-7 rounded px-1.5 text-[11px] text-faint hover:text-fg">
          ↺
        </button>
      )}
    </div>
  )
}

/** Integer input committed on Enter/blur, clamped to [min, max]. */
function NumberInput(p: {
  value: number
  min: number
  max: number
  disabled?: boolean
  onChange: (v: number) => void
  display?: (v: number) => string
  className?: string
}) {
  const shown = p.display ? p.display(p.value) : String(p.value)
  const [text, setText] = useState(shown)
  const [focused, setFocused] = useState(false)
  useEffect(() => {
    if (!focused) setText(shown)
  }, [shown, focused])
  const commit = () => {
    const v = parseInt(text.replace('+', ''), 10)
    if (Number.isFinite(v)) p.onChange(Math.min(p.max, Math.max(p.min, v)))
    else setText(shown)
  }
  return (
    <input
      type="text"
      inputMode="numeric"
      value={focused ? text : shown}
      disabled={p.disabled}
      onFocus={(e) => {
        setFocused(true)
        setText(String(p.value))
        e.currentTarget.select()
      }}
      onBlur={() => {
        setFocused(false)
        commit()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') {
          setText(shown)
          e.currentTarget.blur()
        }
        if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
          e.preventDefault()
          const v = Math.min(p.max, Math.max(p.min, p.value + (e.key === 'ArrowUp' ? 1 : -1)))
          p.onChange(v)
          setText(String(v))
        }
      }}
      onChange={(e) => setText(e.target.value)}
      className={cx(
        'h-6 rounded border border-line-strong bg-bg px-1 text-center font-mono text-xs text-fg tabular-nums outline-none focus:border-accent disabled:opacity-40',
        p.className,
      )}
    />
  )
}
