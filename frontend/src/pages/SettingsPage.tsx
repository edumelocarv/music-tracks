import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { putSettings } from '../api/endpoints'
import { qk, useHealth, useSettings } from '../api/queries'
import type { Language, Settings } from '../api/types'
import { AlertIcon, CheckIcon } from '../components/icons'
import { StemModeSelect } from '../components/StemModeSelect'
import { Button, ErrorBox, inputClass, selectClass, Spinner } from '../components/ui'
import { useI18n } from '../i18n'

export function SettingsPage() {
  const { m, lang, setLang } = useI18n()
  const qc = useQueryClient()
  const settings = useSettings()
  const health = useHealth()
  const [dataDir, setDataDir] = useState('')
  const [volume, setVolume] = useState(70)

  useEffect(() => {
    if (settings.data) {
      setDataDir(settings.data.data_dir)
      setVolume(settings.data.metronome_volume)
    }
  }, [settings.data])

  const save = useMutation({
    mutationFn: putSettings,
    onSuccess: (s: Settings) => qc.setQueryData(qk.settings, s),
  })
  const saveDir = useMutation({
    mutationFn: (d: string) => putSettings({ data_dir: d }),
    onSuccess: (s: Settings) => qc.setQueryData(qk.settings, s),
  })

  if (settings.isLoading) {
    return (
      <div className="flex justify-center py-20 text-muted">
        <Spinner size={22} />
      </div>
    )
  }
  if (settings.error || !settings.data) {
    return (
      <div className="mx-auto max-w-3xl px-6 py-8">
        <ErrorBox error={settings.error} />
      </div>
    )
  }
  const s = settings.data

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
      <h1 className="text-xl font-semibold tracking-tight">{m.settings.title}</h1>

      {s.restart_required && (
        <div className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/10 px-4 py-3 text-[13px] text-warn">
          <AlertIcon size={16} />
          {m.settings.restartRequired}
        </div>
      )}

      <Card title={m.settings.general}>
        <Row label={m.settings.language}>
          <select
            className={selectClass + ' w-80'}
            value={s.language ?? ''}
            onChange={(e) => {
              const v = (e.target.value || null) as Language | null
              setLang(v)
              save.mutate({ language: v })
            }}
          >
            <option value="">
              {m.settings.languageAuto} — {m.languages[lang]}
            </option>
            <option value="en">{m.languages.en}</option>
            <option value="pt-BR">{m.languages['pt-BR']}</option>
          </select>
        </Row>
        <div className="py-4">
          <p className="mb-2 text-[13px] font-medium">{m.settings.defaultStemMode}</p>
          <StemModeSelect value={s.default_stem_mode} onChange={(v) => save.mutate({ default_stem_mode: v })} />
        </div>
        <Row label={m.settings.metronomeVolume}>
          <div className="flex w-64 items-center gap-3">
            <input
              type="range"
              className="fader flex-1"
              min={0}
              max={100}
              value={volume}
              style={{ ['--pct' as string]: `${volume}%` }}
              onChange={(e) => setVolume(Number(e.target.value))}
              onPointerUp={() => save.mutate({ metronome_volume: volume })}
              onKeyUp={() => save.mutate({ metronome_volume: volume })}
            />
            <span className="w-10 text-right text-[13px] text-muted tabular-nums">{volume}%</span>
          </div>
        </Row>
        {save.error && <ErrorBox error={save.error} className="mt-2" />}
      </Card>

      <Card title={m.settings.dataDir}>
        <p className="pb-3 text-[13px] leading-relaxed text-muted">{m.settings.dataDirHint}</p>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            saveDir.mutate(dataDir.trim())
          }}
        >
          <input
            className={inputClass + ' font-mono text-xs'}
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            disabled={s.data_dir_locked}
            spellCheck={false}
          />
          {!s.data_dir_locked && (
            <Button type="submit" variant="primary" disabled={saveDir.isPending || dataDir.trim() === s.data_dir || !dataDir.trim()}>
              {saveDir.isPending ? <Spinner size={12} /> : saveDir.isSuccess && dataDir.trim() === s.data_dir ? <CheckIcon size={14} /> : null}
              {m.app.save}
            </Button>
          )}
        </form>
        {s.data_dir_locked && <p className="mt-2 text-xs text-faint">{m.settings.dataDirLocked}</p>}
        {saveDir.error && <ErrorBox error={saveDir.error} className="mt-3" />}
      </Card>

      <Card title={m.settings.system}>
        {health.isLoading ? (
          <Spinner />
        ) : health.error || !health.data ? (
          <ErrorBox error={health.error} />
        ) : (
          <dl className="divide-y divide-line">
            <Info label={m.settings.device} value={health.data.device === 'mps' ? m.settings.deviceMps : m.settings.deviceCpu} />
            <Info
              label={m.settings.models}
              value={
                health.data.models_cached ? (
                  <span className="text-ok">{m.settings.modelsYes}</span>
                ) : (
                  <span className="text-warn">{m.settings.modelsNo}</span>
                )
              }
            />
            <Info label={m.settings.ffmpeg} value={<span className="font-mono text-xs">{health.data.ffmpeg}</span>} />
            <Info label={m.settings.ytdlp} value={<span className="font-mono text-xs">{health.data.yt_dlp}</span>} />
            <Info label={m.settings.activeDataDir} value={<span className="font-mono text-xs break-all">{health.data.data_dir}</span>} />
            <Info
              label={m.settings.watchFolder}
              value={<span className="font-mono text-xs break-all">{health.data.data_dir.replace(/\/$/, '')}/inbox</span>}
            />
          </dl>
        )}
      </Card>
    </div>
  )
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-panel">
      <h2 className="border-b border-line px-5 py-3 text-[13px] font-semibold">{title}</h2>
      <div className="px-5 py-3">{children}</div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <span className="text-[13px] font-medium">{label}</span>
      {children}
    </div>
  )
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6 py-2.5 text-[13px]">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  )
}
