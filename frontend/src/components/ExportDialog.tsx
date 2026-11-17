import { useState, type ReactNode, type RefObject } from 'react'
import { downloadGet, exportMix, stemExportUrl, zipExportUrl } from '../api/endpoints'
import type { ExportFormat, Song, StemName } from '../api/types'
import { exportGains } from '../audio/mix'
import { defaultPlayerState } from '../audio/playerState'
import { useT } from '../i18n'
import { formatTimePrecise } from '../lib/format'
import { STEM_COLORS } from '../lib/stems'
import type { PlayerSnapshot } from '../player/Player'
import { CheckIcon, DownloadIcon } from './icons'
import { Button, cx, ErrorBox, Modal, selectClass, Spinner } from './ui'

type Kind = 'stem' | 'zip' | 'mix'
const FORMATS: ExportFormat[] = ['wav', 'flac', 'mp3']

export function ExportDialog({ song, snapshotRef, onClose }: { song: Song; snapshotRef: RefObject<PlayerSnapshot | null>; onClose: () => void }) {
  const m = useT()
  const snap = snapshotRef.current ?? { stems: song.stems, state: defaultPlayerState(song.stems, 70), loop: { a: null, b: null, enabled: false } }
  const [format, setFormat] = useState<ExportFormat>('wav')
  const [stem, setStem] = useState<StemName>(song.stems[0])
  const [applySpeed, setApplySpeed] = useState(false)
  const loop = snap.loop.a !== null && snap.loop.b !== null ? { a: snap.loop.a, b: snap.loop.b } : null
  const [onlyLoop, setOnlyLoop] = useState(false)
  const [busy, setBusy] = useState<Kind | null>(null)
  const [done, setDone] = useState<Kind | null>(null)
  const [error, setError] = useState<unknown>(null)

  const base = `${song.artist ? `${song.artist} - ` : ''}${song.title}`
  const run = async (kind: Kind, fn: () => Promise<void>) => {
    setBusy(kind)
    setDone(null)
    setError(null)
    try {
      await fn()
      setDone(kind)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  const exportMixNow = () =>
    run('mix', () =>
      exportMix(
        song.id,
        {
          gains: exportGains(snap.stems, snap.state),
          speed: applySpeed ? snap.state.speed : 1,
          semitones: applySpeed ? snap.state.semitones : 0,
          start_s: onlyLoop && loop ? loop.a : null,
          end_s: onlyLoop && loop ? loop.b : null,
          format,
        },
        `${base} [mix].${format}`,
      ),
    )

  const action = (kind: Kind, onClick: () => void) => (
    <Button variant={kind === 'mix' ? 'primary' : 'secondary'} onClick={onClick} disabled={busy !== null} className="w-36">
      {busy === kind ? <Spinner size={12} /> : done === kind ? <CheckIcon size={14} /> : <DownloadIcon size={14} />}
      {busy === kind ? m.export.generating : done === kind ? m.export.done : m.export.download}
    </Button>
  )

  return (
    <Modal title={m.export.title} onClose={onClose} width={560}>
      <div className="mb-4 flex items-center gap-3">
        <span className="text-xs font-medium tracking-wide text-muted uppercase">{m.export.format}</span>
        <div className="flex rounded-md border border-line-strong p-0.5">
          {FORMATS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFormat(f)}
              aria-pressed={format === f}
              className={cx('h-7 rounded px-3 text-xs font-semibold uppercase', format === f ? 'bg-raised text-fg' : 'text-faint hover:text-fg')}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="divide-y divide-line rounded-lg border border-line">
        <Section title={m.export.stem}>
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ background: STEM_COLORS[stem] }} />
            <select className={selectClass + ' flex-1'} value={stem} onChange={(e) => setStem(e.target.value as StemName)}>
              {song.stems.map((s) => (
                <option key={s} value={s}>
                  {m.stems[s]}
                </option>
              ))}
            </select>
            {action('stem', () => run('stem', () => downloadGet(stemExportUrl(song.id, stem, format), `${base} [${stem}].${format}`)))}
          </div>
        </Section>
        <Section title={m.export.zip}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-faint">{song.stems.map((s) => m.stems[s]).join(', ')}</span>
            {action('zip', () => run('zip', () => downloadGet(zipExportUrl(song.id, format), `${base} [stems].zip`)))}
          </div>
        </Section>
        <Section title={m.export.mix}>
          <p className="mb-2 text-xs text-faint">{m.export.mixHint}</p>
          <div className="mb-3 flex gap-1">
            {snap.stems.map((s) => {
              const g = exportGains(snap.stems, snap.state)[s]
              return (
                <div key={s} className="flex-1" title={`${m.stems[s]} ${Math.round(g * 100)}%`}>
                  <div className="h-1.5 overflow-hidden rounded-full bg-line">
                    <div className="h-full rounded-full" style={{ width: `${g * 100}%`, background: STEM_COLORS[s] }} />
                  </div>
                  <div className="mt-1 truncate text-[10px] text-faint">{m.stems[s]}</div>
                </div>
              )
            })}
          </div>
          <div className="flex items-end justify-between gap-3">
            <div className="space-y-1.5 text-[13px]">
              <Check checked={applySpeed} onChange={setApplySpeed}>
                {m.export.applySpeedPitch}{' '}
                <span className="text-faint">
                  ({Math.round(snap.state.speed * 100)}%, {snap.state.semitones > 0 ? '+' : ''}
                  {snap.state.semitones})
                </span>
              </Check>
              {loop && (
                <Check checked={onlyLoop} onChange={setOnlyLoop}>
                  {m.export.onlyLoop}{' '}
                  <span className="text-faint">
                    ({formatTimePrecise(loop.a)} – {formatTimePrecise(loop.b)})
                  </span>
                </Check>
              )}
            </div>
            {action('mix', exportMixNow)}
          </div>
        </Section>
      </div>
      {error ? <ErrorBox error={error} className="mt-3" /> : null}
    </Modal>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-4 py-3">
      <h3 className="mb-2 text-[13px] font-semibold">{title}</h3>
      {children}
    </div>
  )
}

function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-center gap-2">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-3.5 w-3.5 accent-[#6f82ff]" />
      <span>{children}</span>
    </label>
  )
}
