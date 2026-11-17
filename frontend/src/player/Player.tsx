import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { createMarker, deleteMarker, getAnalysis, getPeaks, listMarkers, patchMarker, patchSong, patchSongKeepalive, stemUrl } from '../api/endpoints'
import { qk } from '../api/queries'
import type { Marker, MetronomeState, PlayerState, Song, StemName } from '../api/types'
import { StemEngine } from '../audio/engine'
import {
  EMPTY_LOOP,
  isLoopActive,
  loopAfterSeek,
  loopToPersisted,
  setLoopA,
  setLoopB,
  setLoopRange,
  toggleLoop,
  type LoopDraft,
} from '../audio/loop'
import { effectiveGains, masterGain } from '../audio/mix'
import { clamp, normalizePlayerState, type FullPlayerState } from '../audio/playerState'
import { RefreshIcon } from '../components/icons'
import { Button, ErrorBox, ErrorText, ProgressBar, Spinner } from '../components/ui'
import { fmt, useT } from '../i18n'
import { formatTimePrecise } from '../lib/format'
import { isTypingTarget, useLatest } from '../lib/hooks'
import { AnalysisBar } from './AnalysisBar'
import { MarkersPanel } from './MarkersPanel'
import { PositionStore } from './positionStore'
import { Tracks } from './Tracks'
import { Transport } from './Transport'

/** What the export dialog needs from the live player. */
export interface PlayerSnapshot {
  stems: StemName[]
  state: FullPlayerState
  loop: LoopDraft
}

const EMPTY: readonly number[] = []

export function Player({
  song,
  metronomeDefault,
  snapshotRef,
  version,
  onReprocess,
}: {
  song: Song
  metronomeDefault: number
  snapshotRef: RefObject<PlayerSnapshot | null>
  /** Bumped when a reprocess finishes, to refetch peaks/analysis. */
  version: number
  onReprocess: () => void
}) {
  const m = useT()
  const qc = useQueryClient()
  const stems = song.stems
  const stemsKey = stems.join(',')
  const songId = song.id

  // ---------- data ----------
  const peaks = useQuery({ queryKey: qk.peaks(songId, version), queryFn: () => getPeaks(songId), staleTime: Infinity, retry: 1 })
  const analysis = useQuery({
    queryKey: qk.analysis(songId, version),
    queryFn: () => getAnalysis(songId),
    enabled: song.analysis_status === 'ok',
    staleTime: Infinity,
    retry: 1,
  })
  const markers = useQuery({ queryKey: qk.markers(songId), queryFn: () => listMarkers(songId) })
  const beats = analysis.data?.beats ?? EMPTY
  const downbeats = analysis.data?.downbeats ?? EMPTY
  const metronomeAvailable = beats.length > 0

  // ---------- engine ----------
  const [attempt, setAttempt] = useState(0)
  const [engine, setEngine] = useState<StemEngine | null>(null)
  const [progress, setProgress] = useState<{ k: number; n: number }>({ k: 0, n: stems.length })
  const [loadError, setLoadError] = useState<unknown>(null)
  const [playError, setPlayError] = useState<unknown>(null)

  useEffect(() => {
    const ac = new AbortController()
    let cancelled = false
    let loaded: StemEngine | null = null
    setEngine(null)
    setLoadError(null)
    setProgress({ k: 0, n: stems.length })
    StemEngine.load({
      urls: stems.map((s) => stemUrl(songId, s)),
      durationHint: song.duration_s,
      signal: ac.signal,
      onProgress: (k, n) => {
        if (!cancelled) setProgress({ k, n })
      },
    })
      .then((e) => {
        if (cancelled) {
          e.dispose()
          return
        }
        loaded = e
        setEngine(e)
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err)
      })
    return () => {
      cancelled = true
      ac.abort()
      loaded?.dispose()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [songId, stemsKey, attempt])

  // ---------- player state (§9.6) ----------
  const [initial] = useState(() => normalizePlayerState(song.player_state, stems, metronomeDefault, song.duration_s))
  const [ps, setPs] = useState<FullPlayerState>(initial)
  const [loop, setLoop] = useState<LoopDraft>(initial.loop ?? EMPTY_LOOP)
  const [playing, setPlaying] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [viewStart, setViewStart] = useState(0)
  const positions = useMemo(() => new PositionStore(), [])
  const timeRef = useRef<HTMLSpanElement>(null)

  const duration = engine?.duration ?? song.duration_s ?? 0
  const span = duration > 0 ? duration / zoom : 1
  const view = useMemo(() => ({ start: zoom === 1 ? 0 : clamp(viewStart, 0, Math.max(0, duration - span)), span }), [zoom, viewStart, duration, span])

  const mix = useMemo(() => ({ volumes: ps.volumes, mutes: ps.mutes, solos: ps.solos, master: ps.master }), [ps.volumes, ps.mutes, ps.solos, ps.master])
  const gains = useMemo(() => effectiveGains(stems, mix), [stems, mix])

  snapshotRef.current = { stems, state: ps, loop }

  const activeRange = (l: LoopDraft) => (isLoopActive(l) ? { a: l.a, b: l.b } : null)

  // Initial transport config once the engine is ready.
  useEffect(() => {
    if (!engine) return
    engine.onEnded = () => setPlaying(false)
    engine.applyState({ playing: false, rate: ps.speed, semitones: ps.semitones, loop: activeRange(loop) }, 0)
    setPlaying(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine])

  useEffect(() => {
    engine?.setStemGains(stems.map((s) => gains[s] ?? 1))
    engine?.setMaster(masterGain(mix))
  }, [engine, gains, mix, stems])

  useEffect(() => {
    engine?.applyState({ rate: ps.speed, semitones: ps.semitones })
  }, [engine, ps.speed, ps.semitones])

  useEffect(() => {
    engine?.setBeats([...beats], [...downbeats])
  }, [engine, beats, downbeats])

  useEffect(() => {
    engine?.setMetronome(ps.metronome.enabled && metronomeAvailable, ps.metronome.volume, ps.metronome.offset_ms)
  }, [engine, ps.metronome, metronomeAvailable])

  // ---------- persistence: debounced 1 s PATCH, flushed on unmount / unload ----------
  const persisted: PlayerState = useMemo(
    () => ({
      volumes: ps.volumes,
      mutes: ps.mutes,
      solos: ps.solos,
      master: ps.master,
      speed: ps.speed,
      semitones: ps.semitones,
      loop: loopToPersisted(loop),
      metronome: ps.metronome,
    }),
    [ps, loop],
  )
  const savedJson = useRef(JSON.stringify(persisted))
  const pending = useRef<PlayerState | null>(null)

  const flush = useCallback(
    (keepalive: boolean) => {
      const st = pending.current
      if (!st) return
      pending.current = null
      savedJson.current = JSON.stringify(st)
      if (keepalive) patchSongKeepalive(songId, { player_state: st })
      else void patchSong(songId, { player_state: st }).catch(() => undefined)
      qc.setQueryData<Song>(qk.song(songId), (old) => (old ? { ...old, player_state: st } : old))
    },
    [songId, qc],
  )

  useEffect(() => {
    const json = JSON.stringify(persisted)
    if (json === savedJson.current) return
    pending.current = persisted
    const id = setTimeout(() => flush(false), 1000)
    return () => clearTimeout(id)
  }, [persisted, flush])

  useEffect(() => {
    const onUnload = () => flush(true)
    window.addEventListener('beforeunload', onUnload)
    return () => {
      window.removeEventListener('beforeunload', onUnload)
      flush(true)
    }
  }, [flush])

  // ---------- actions ----------
  const getPosition = useCallback(() => (engine ? engine.position() : 0), [engine])

  const commitLoop = (next: LoopDraft, seekTo?: number | null) => {
    setLoop(next)
    engine?.applyState({ loop: activeRange(next) }, seekTo ?? undefined)
    if (seekTo != null) positions.set(seekTo)
  }

  const seek = (target: number) => {
    if (!engine) return
    const t = clamp(target, 0, duration)
    const next = loopAfterSeek(loop, t)
    if (next !== loop) commitLoop(next, t)
    else engine.seek(t)
    positions.set(t)
  }

  const playPause = () => {
    if (!engine) return
    if (engine.playing) {
      engine.pause()
      setPlaying(false)
    } else {
      setPlayError(null)
      setPlaying(true)
      engine.play().catch((err: unknown) => {
        setPlaying(false)
        setPlayError(err)
      })
    }
  }

  const markerMutation = useMutation({
    mutationFn: (mk: { kind: Marker['kind']; name: string; start_s: number; end_s?: number | null }) => createMarker(songId, mk),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.markers(songId) }),
  })
  const renameMutation = useMutation({
    mutationFn: ({ mk, name }: { mk: Marker; name: string }) => patchMarker(songId, mk.id, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.markers(songId) }),
  })
  const deleteMutation = useMutation({
    mutationFn: (mk: Marker) => deleteMarker(songId, mk.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.markers(songId) }),
  })

  const addMarker = () => {
    if (!engine) return
    const count = (markers.data ?? []).filter((x) => x.kind === 'marker').length
    markerMutation.mutate({ kind: 'marker', name: fmt(m.markers.defaultName, { n: count + 1 }), start_s: round3(engine.position()) })
  }

  const saveLoop = () => {
    if (loop.a === null || loop.b === null) return
    const count = (markers.data ?? []).filter((x) => x.kind === 'loop').length
    markerMutation.mutate({ kind: 'loop', name: fmt(m.player.loopNameDefault, { n: count + 1 }), start_s: round3(loop.a), end_s: round3(loop.b) })
  }

  const enableRange = (a: number, b: number) => {
    const next = setLoopRange(loop, a, b, true)
    if (next === loop || next.a === null || next.b === null) return
    const pos = getPosition()
    commitLoop(next, pos < next.a || pos >= next.b ? next.a : null)
  }

  const setStemFlag = (key: 'mutes' | 'solos', stem: StemName) =>
    setPs((s) => ({ ...s, [key]: { ...s[key], [stem]: !s[key][stem] } }))

  const actions = {
    playPause,
    nudge: (d: number) => engine && seek(engine.position() + d),
    setA: () => {
      if (!engine) return
      const next = setLoopA(loop, engine.position())
      if (next !== loop) commitLoop(next)
    },
    setB: () => {
      if (!engine) return
      const next = setLoopB(loop, engine.position())
      if (next !== loop) commitLoop(next)
    },
    toggleLoop: () => {
      if (!engine) return
      const r = toggleLoop(loop, engine.position())
      if (r.loop !== loop) commitLoop(r.loop, r.seekTo)
    },
    addMarker,
    toggleMetronome: () => {
      if (metronomeAvailable) setPs((s) => ({ ...s, metronome: { ...s.metronome, enabled: !s.metronome.enabled } }))
    },
  }
  const actionsRef = useLatest(actions)

  // ---------- keyboard shortcuts (§9.2) ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (document.querySelector('[role="dialog"]')) return
      const a = actionsRef.current
      switch (e.key) {
        case ' ':
          e.preventDefault()
          if (!e.repeat) a.playPause()
          break
        case 'ArrowLeft':
          e.preventDefault()
          a.nudge(-5)
          break
        case 'ArrowRight':
          e.preventDefault()
          a.nudge(5)
          break
        case '[':
          a.setA()
          break
        case ']':
          a.setB()
          break
        case 'l':
        case 'L':
          a.toggleLoop()
          break
        case 'm':
        case 'M':
          if (!e.repeat) a.addMarker()
          break
        case 'k':
        case 'K':
          a.toggleMetronome()
          break
        default:
          return
      }
    }
    // Prevent Space from also "clicking" a focused button.
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === ' ' && !isTypingTarget(e.target) && e.target instanceof HTMLButtonElement) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [actionsRef])

  // ---------- per-frame UI (called from the waveform rAF loop) ----------
  const frameState = useLatest({ zoom, view, playing, duration })
  const lastText = useRef('')
  const onFrame = useCallback(
    (pos: number) => {
      positions.set(pos)
      const text = formatTimePrecise(pos)
      if (text !== lastText.current && timeRef.current) {
        timeRef.current.textContent = text
        lastText.current = text
      }
      const f = frameState.current
      if (f.zoom > 1 && f.playing && (pos < f.view.start || pos > f.view.start + f.view.span * 0.97)) {
        setViewStart(clamp(pos - f.view.span * 0.03, 0, Math.max(0, f.duration - f.view.span)))
      }
    },
    [positions, frameState],
  )

  // ---------- render ----------
  const loading = !engine && !loadError
  const chords = song.analysis_status === 'ok' ? (analysis.data?.chords ?? null) : null

  return (
    <div className="space-y-4">
      <AnalysisBar
        bpm={analysis.data?.bpm ?? song.bpm}
        speed={ps.speed}
        keyLabel={analysis.data?.key?.label ?? song.key_label}
        semitones={ps.semitones}
        chords={chords}
        analysisFailed={song.analysis_status === 'failed'}
        positions={positions}
        onReprocess={onReprocess}
      />

      <div className="rounded-xl border border-line bg-panel px-4 py-3">
        <Transport
          disabled={!engine}
          playing={playing}
          duration={duration}
          timeRef={timeRef}
          speed={ps.speed}
          semitones={ps.semitones}
          loop={loop}
          metronome={ps.metronome}
          metronomeAvailable={metronomeAvailable}
          zoom={zoom}
          onPlayPause={playPause}
          onToStart={() => seek(isLoopActive(loop) ? loop.a : 0)}
          onNudge={actions.nudge}
          onSpeed={(v) => setPs((s) => ({ ...s, speed: v }))}
          onSemitones={(v) => setPs((s) => ({ ...s, semitones: v }))}
          onSetA={actions.setA}
          onSetB={actions.setB}
          onToggleLoop={actions.toggleLoop}
          onClearLoop={() => commitLoop(EMPTY_LOOP)}
          onSaveLoop={saveLoop}
          onMetronome={(patch: Partial<MetronomeState>) => setPs((s) => ({ ...s, metronome: { ...s.metronome, ...patch } }))}
          onZoom={(z) => {
            setZoom(z)
            const pos = getPosition()
            const sp = duration / z
            setViewStart(clamp(pos - sp / 2, 0, Math.max(0, duration - sp)))
          }}
        />
        {playError ? <ErrorText code="AUDIO_ENGINE" detail={String(playError)} m={m} compact className="mt-2" /> : null}
      </div>

      <div className="relative">
        <Tracks
          stems={stems}
          peaks={peaks.data}
          view={view}
          duration={duration}
          downbeats={downbeats}
          chords={chords}
          semitones={ps.semitones}
          loop={loop}
          markers={markers.data ?? []}
          gains={gains}
          state={ps}
          disabled={!engine}
          getPosition={getPosition}
          onFrame={onFrame}
          onSeek={seek}
          onLoopDrag={enableRange}
          onVolume={(stem, v) => setPs((s) => ({ ...s, volumes: { ...s.volumes, [stem]: v } }))}
          onMute={(stem) => setStemFlag('mutes', stem)}
          onSolo={(stem) => setStemFlag('solos', stem)}
          onMaster={(v) => setPs((s) => ({ ...s, master: v }))}
        />
        {(loading || !!loadError) && (
          <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-bg/70 backdrop-blur-[1px]">
            <div className="w-80 rounded-xl border border-line-strong bg-panel p-5 text-center shadow-2xl shadow-black/50">
              {loadError ? (
                <>
                  <p className="mb-3 text-[13px] font-medium">{m.player.loadError}</p>
                  <details className="mb-3 text-left text-xs text-faint">
                    <summary className="cursor-pointer select-none hover:text-muted">{m.app.details}</summary>
                    <pre className="mt-1.5 max-h-32 overflow-auto rounded bg-bg p-2 font-mono text-[11px] break-all whitespace-pre-wrap">{errorDetail(loadError)}</pre>
                  </details>
                  <Button variant="primary" onClick={() => setAttempt((a) => a + 1)}>
                    <RefreshIcon size={13} />
                    {m.app.retry}
                  </Button>
                </>
              ) : (
                <>
                  <div className="mb-3 flex items-center justify-center gap-2 text-[13px] text-muted">
                    <Spinner size={13} />
                    {progress.k < progress.n ? fmt(m.player.loadingStems, { k: progress.k + 1, n: progress.n }) : m.player.preparing}
                  </div>
                  <ProgressBar value={(progress.k / Math.max(1, progress.n)) * 100} />
                </>
              )}
            </div>
          </div>
        )}
        {peaks.error ? <ErrorBox error={peaks.error} compact className="mt-2" /> : null}
      </div>

      {zoom > 1 && duration > 0 && (
        <input
          type="range"
          className="fader w-full"
          min={0}
          max={Math.max(0, duration - span)}
          step={0.01}
          value={view.start}
          onChange={(e) => setViewStart(Number(e.target.value))}
          style={{ ['--pct' as string]: '0%' }}
          aria-label={m.player.zoom}
        />
      )}

      <p className="text-[11px] text-faint">
        {m.player.shortcutsList} · {m.player.clickToSeek}
      </p>

      <MarkersPanel
        markers={markers.data ?? []}
        activeLoop={activeRange(loop)}
        error={markerMutation.error ?? renameMutation.error ?? deleteMutation.error}
        disabled={!engine}
        onAdd={addMarker}
        onJump={seek}
        onActivateLoop={(mk) => {
          if (mk.end_s != null) enableRange(mk.start_s, mk.end_s)
        }}
        onRename={(mk, name) => renameMutation.mutate({ mk, name })}
        onDelete={(mk) => deleteMutation.mutate(mk)}
      />
    </div>
  )
}

const round3 = (v: number) => Math.round(v * 1000) / 1000

function errorDetail(err: unknown): string {
  if (err instanceof Error) return `${err.name}: ${err.message}`
  return String(err)
}
