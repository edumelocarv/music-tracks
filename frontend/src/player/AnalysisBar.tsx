import { useSyncExternalStore, type ReactNode } from 'react'
import type { ChordSegment } from '../api/types'
import { AlertIcon, RefreshIcon } from '../components/icons'
import { Button } from '../components/ui'
import { useI18n } from '../i18n'
import { formatBpm } from '../lib/format'
import { displayChord, displayKey } from '../music/theory'
import type { PositionStore } from './positionStore'

/** Index of the chord containing `t`, or -1. */
export function chordIndexAt(chords: readonly ChordSegment[], t: number): number {
  let lo = 0
  let hi = chords.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (chords[mid].start <= t) {
      ans = mid
      lo = mid + 1
    } else hi = mid - 1
  }
  return ans >= 0 && t < chords[ans].end ? ans : -1
}

export function AnalysisBar(p: {
  bpm: number | null
  speed: number
  keyLabel: string | null
  semitones: number
  chords: readonly ChordSegment[] | null
  analysisFailed: boolean
  positions: PositionStore
  onReprocess: () => void
}) {
  const { m, lang } = useI18n()
  if (p.analysisFailed) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-warn/25 bg-warn/5 px-4 py-2.5 text-[13px] text-warn">
        <AlertIcon size={15} />
        <span className="flex-1">{m.song.analysisUnavailable}</span>
        <Button size="sm" onClick={p.onReprocess}>
          <RefreshIcon size={12} />
          {m.song.reprocess}
        </Button>
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-stretch gap-2">
      <Stat label={m.player.bpm}>
        {p.bpm != null ? (
          <>
            <span className={p.speed !== 1 ? 'text-accent' : undefined}>{formatBpm(p.bpm * p.speed)}</span>
            {p.speed !== 1 && <span className="ml-1.5 text-[13px] font-normal text-faint">({formatBpm(p.bpm)})</span>}
          </>
        ) : (
          <span className="text-faint">{m.app.none}</span>
        )}
      </Stat>
      <Stat label={m.player.key}>
        {p.keyLabel ? (
          <>
            <span className={p.semitones !== 0 ? 'text-accent' : undefined}>{displayKey(p.keyLabel, lang, p.semitones)}</span>
            {p.semitones !== 0 && <span className="ml-1.5 text-[13px] font-normal text-faint">({displayKey(p.keyLabel, lang)})</span>}
          </>
        ) : (
          <span className="text-faint">{m.app.none}</span>
        )}
      </Stat>
      {p.chords && p.chords.length > 0 && <ChordNow chords={p.chords} semitones={p.semitones} positions={p.positions} />}
    </div>
  )
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-[110px] rounded-lg border border-line bg-panel px-3.5 py-2">
      <div className="text-[10px] font-semibold tracking-wider text-faint uppercase">{label}</div>
      <div className="mt-0.5 text-[17px] font-semibold tabular-nums">{children}</div>
    </div>
  )
}

function ChordNow({ chords, semitones, positions }: { chords: readonly ChordSegment[]; semitones: number; positions: PositionStore }) {
  const { m } = useI18n()
  const idx = useSyncExternalStore(positions.subscribe, () => chordIndexAt(chords, positions.get()))
  const current = idx >= 0 ? chords[idx] : null
  let next: ChordSegment | null = null
  for (let i = idx + 1; i < chords.length; i++) {
    if (chords[i].label !== 'N' && chords[i].label !== current?.label) {
      next = chords[i]
      break
    }
  }
  if (idx < 0 && chords.length && positions.get() < chords[0].start) next = chords[0]
  return (
    <div className="flex min-w-[200px] items-center gap-4 rounded-lg border border-accent/25 bg-accent/5 px-3.5 py-2">
      <div>
        <div className="text-[10px] font-semibold tracking-wider text-faint uppercase">{m.player.chord}</div>
        <div className="mt-0.5 text-2xl leading-tight font-bold text-[#d6dbff]">{current ? displayChord(current.label, semitones) : '—'}</div>
      </div>
      <div className="text-faint">→</div>
      <div>
        <div className="text-[10px] font-semibold tracking-wider text-faint uppercase">{m.player.nextChord}</div>
        <div className="mt-0.5 text-[17px] font-semibold text-muted">{next ? displayChord(next.label, semitones) : '—'}</div>
      </div>
    </div>
  )
}
