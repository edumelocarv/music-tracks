import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router'
import { ApiError, toApiError } from '../api/client'
import { addSongUrl, uploadSong } from '../api/endpoints'
import { qk, useSettings } from '../api/queries'
import type { StemMode } from '../api/types'
import { fmt, useT } from '../i18n'
import { CheckIcon, LinkIcon, UploadIcon, XIcon } from './icons'
import { StemModeSelect } from './StemModeSelect'
import { Button, cx, ErrorBox, inputClass, Modal, ProgressBar, Spinner } from './ui'

type ItemState =
  | { kind: 'waiting' }
  | { kind: 'uploading'; progress: number }
  | { kind: 'done'; songId: string }
  | { kind: 'error'; error: ApiError }

interface Item {
  id: number
  file: File
  state: ItemState
}

let nextId = 1

export function AddMusicDialog({ onClose }: { onClose: () => void }) {
  const m = useT()
  const settings = useSettings()
  const [tab, setTab] = useState<'file' | 'url'>('file')
  const [modeOverride, setMode] = useState<StemMode | null>(null)
  const mode: StemMode = modeOverride ?? settings.data?.default_stem_mode ?? 4

  return (
    <Modal title={m.add.title} onClose={onClose} width={600}>
      <div className="mb-4 flex gap-1 rounded-lg bg-bg p-1">
        {(['file', 'url'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cx(
              'flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md text-[13px] font-medium transition-colors',
              tab === t ? 'bg-raised text-fg shadow-sm' : 'text-muted hover:text-fg',
            )}
          >
            {t === 'file' ? <UploadIcon size={14} /> : <LinkIcon size={14} />}
            {t === 'file' ? m.add.tabFile : m.add.tabUrl}
          </button>
        ))}
      </div>
      <div className="mb-5">
        <StemModeSelect value={mode} onChange={setMode} />
      </div>
      {tab === 'file' ? <FileTab mode={mode} onOpen={onClose} /> : <UrlTab mode={mode} onOpen={onClose} />}
    </Modal>
  )
}

function FileTab({ mode, onOpen }: { mode: StemMode; onOpen: () => void }) {
  const m = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<Item[]>([])
  const [drag, setDrag] = useState(false)
  const [running, setRunning] = useState(false)

  const update = (id: number, state: ItemState) => setItems((xs) => xs.map((x) => (x.id === id ? { ...x, state } : x)))

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files).map((file) => ({ id: nextId++, file, state: { kind: 'waiting' } as ItemState }))
    setItems((xs) => [...xs, ...list])
  }

  const waiting = items.filter((i) => i.state.kind === 'waiting')

  // Files are uploaded one request at a time, each with its own result (§8.3).
  const uploadAll = async () => {
    setRunning(true)
    for (const item of waiting) {
      update(item.id, { kind: 'uploading', progress: 0 })
      try {
        const res = await uploadSong(item.file, mode, (p) => update(item.id, { kind: 'uploading', progress: p }))
        update(item.id, { kind: 'done', songId: res.song.id })
      } catch (err) {
        update(item.id, { kind: 'error', error: toApiError(err) })
      }
      void qc.invalidateQueries({ queryKey: qk.songs })
      void qc.invalidateQueries({ queryKey: qk.jobs })
    }
    setRunning(false)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const open = (id: string) => {
    onOpen()
    navigate(`/songs/${id}`)
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDrag(true)
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={cx(
          'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
          drag ? 'border-accent bg-accent/10' : 'border-line-strong bg-bg hover:border-[#4a505a]',
        )}
      >
        <UploadIcon size={24} className="mb-2 text-muted" />
        <p className="text-[13px] font-medium">{m.add.drop}</p>
        <p className="mt-1 text-xs text-faint">
          {m.add.or} <span className="text-accent underline-offset-2 hover:underline">{m.add.choose}</span>
        </p>
        <p className="mt-3 text-[11px] text-faint">{m.add.formats}</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="audio/*,video/*,.mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.aiff,.aif,.wma,.webm,.mp4,.mkv"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {items.length > 0 && (
        <ul className="max-h-64 space-y-1.5 overflow-y-auto">
          {items.map((it) => (
            <li key={it.id} className="rounded-lg border border-line bg-bg px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[13px]" title={it.file.name}>
                  {it.file.name}
                </span>
                <span className="shrink-0 text-[11px] text-faint tabular-nums">{(it.file.size / 1024 / 1024).toFixed(1)} MB</span>
                {it.state.kind === 'waiting' && (
                  <>
                    <span className="text-xs text-faint">{m.add.waiting}</span>
                    {!running && (
                      <button
                        className="text-faint hover:text-fg"
                        onClick={() => setItems((xs) => xs.filter((x) => x.id !== it.id))}
                        aria-label={m.add.remove}
                      >
                        <XIcon size={13} />
                      </button>
                    )}
                  </>
                )}
                {it.state.kind === 'uploading' && <Spinner size={12} className="text-accent" />}
                {it.state.kind === 'done' && (
                  <>
                    <span className="flex items-center gap-1 text-xs text-ok">
                      <CheckIcon size={13} />
                      {m.add.done}
                    </span>
                    <Button size="sm" variant="ghost" onClick={() => open((it.state as { songId: string }).songId)}>
                      {m.add.open}
                    </Button>
                  </>
                )}
              </div>
              {it.state.kind === 'uploading' && <ProgressBar value={it.state.progress * 100} className="mt-2" />}
              {it.state.kind === 'error' && (
                <div className="mt-2 flex items-start gap-2">
                  <ErrorBox error={it.state.error} compact className="flex-1" />
                  {it.state.error.code === 'DUPLICATE' && it.state.error.existingSongId && (
                    <Button size="sm" onClick={() => open((it.state as { error: ApiError }).error.existingSongId!)}>
                      {m.add.openExisting}
                    </Button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        {items.some((i) => i.state.kind === 'done' || i.state.kind === 'error') && !running && (
          <Button variant="ghost" onClick={() => setItems((xs) => xs.filter((x) => x.state.kind === 'waiting'))}>
            {m.add.clearDone}
          </Button>
        )}
        <Button variant="primary" disabled={!waiting.length || running} onClick={() => void uploadAll()}>
          {running ? <Spinner size={12} /> : <UploadIcon size={14} />}
          {running ? m.add.uploading : fmt(m.add.upload, { n: waiting.length || '' }).trim()}
        </Button>
      </div>
    </div>
  )
}

function UrlTab({ mode, onOpen }: { mode: StemMode; onOpen: () => void }) {
  const m = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await addSongUrl(url.trim(), mode)
      void qc.invalidateQueries({ queryKey: qk.songs })
      void qc.invalidateQueries({ queryKey: qk.jobs })
      onOpen()
      navigate(`/songs/${res.song.id}`)
    } catch (err) {
      setError(toApiError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (url.trim() && !busy) void submit()
      }}
    >
      <label className="block space-y-1.5">
        <span className="text-xs font-medium tracking-wide text-muted uppercase">{m.add.urlLabel}</span>
        <input
          autoFocus
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={m.add.urlPlaceholder}
          className={inputClass + ' h-9'}
        />
        <span className="block text-xs text-faint">{m.add.urlHint}</span>
      </label>
      {error && (
        <div className="flex items-start gap-2">
          <ErrorBox error={error} className="flex-1" />
          {error.code === 'DUPLICATE' && error.existingSongId && (
            <Button
              onClick={() => {
                onOpen()
                navigate(`/songs/${error.existingSongId}`)
              }}
            >
              {m.add.openExisting}
            </Button>
          )}
        </div>
      )}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" disabled={!url.trim() || busy}>
          {busy && <Spinner size={12} />}
          {busy ? m.add.checking : m.add.submitUrl}
        </Button>
      </div>
    </form>
  )
}
