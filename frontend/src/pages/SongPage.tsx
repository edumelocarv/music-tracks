import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { cancelJob, deleteCover, deleteSong, getSong, patchSong, reprocessSong, retryJob, uploadCover, type SongPatch } from '../api/endpoints'
import { qk, useActiveJobForSong, useSettings, useTags } from '../api/queries'
import type { Job, Song, StemMode } from '../api/types'
import { ExportDialog } from '../components/ExportDialog'
import { ArrowLeftIcon, DownloadIcon, ImageIcon, MusicIcon, RefreshIcon, StarIcon, TrashIcon, XIcon } from '../components/icons'
import { InlineEdit, TagEditor } from '../components/SongHeaderParts'
import { StemModeSelect } from '../components/StemModeSelect'
import { Button, ConfirmDialog, cx, ErrorBox, ErrorText, JobProgress, Modal, Spinner } from '../components/ui'
import { fmt, useI18n, useT } from '../i18n'
import { formatBpm, formatDuration } from '../lib/format'
import { Player, type PlayerSnapshot } from '../player/Player'
import { displayKey } from '../music/theory'

export function SongPage() {
  const { id = '' } = useParams()
  const m = useT()
  const qc = useQueryClient()
  const song = useQuery({ queryKey: qk.song(id), queryFn: () => getSong(id), retry: (n, err) => (err as { status?: number }).status !== 404 && n < 1 })
  const settings = useSettings()
  const activeJob = useActiveJobForSong(id, song.data?.active_job ?? null)
  const snapshotRef = useRef<PlayerSnapshot | null>(null)
  const [version, setVersion] = useState(0)
  const [dialog, setDialog] = useState<'reprocess' | 'delete' | 'export' | null>(null)

  // When the watched job finishes, refetch the song; if it was a successful reprocess, reload the player.
  const watched = useRef<string | null>(null)
  const activeId = activeJob?.id ?? null
  useEffect(() => {
    if (activeId) watched.current = activeId
    else if (watched.current) void qc.invalidateQueries({ queryKey: qk.song(id) })
  }, [activeId, id, qc])
  useEffect(() => {
    const lj = song.data?.last_job
    if (!watched.current || !lj || lj.id !== watched.current) return
    if (lj.status === 'queued' || lj.status === 'running') return
    watched.current = null
    if (lj.status === 'done') {
      setVersion((v) => v + 1)
      void qc.invalidateQueries({ queryKey: ['peaks', id] })
      void qc.invalidateQueries({ queryKey: ['analysis', id] })
    }
  }, [song.data, id, qc])

  if (song.isLoading) {
    return (
      <div className="flex justify-center py-24 text-muted">
        <Spinner size={22} />
      </div>
    )
  }
  if (song.error || !song.data) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-12">
        <BackLink />
        {(song.error as { code?: string } | null)?.code === 'NOT_FOUND' ? <p className="mt-6 text-muted">{m.app.notFound}</p> : <ErrorBox error={song.error} className="mt-6" />}
      </div>
    )
  }

  const s = song.data
  const ready = s.status === 'ready' && s.stems.length > 0

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 px-6 py-5">
      <BackLink />
      <SongHeader song={s} onAction={setDialog} ready={ready} busy={!!activeJob} />

      {ready && activeJob && <ReprocessBanner job={activeJob} />}

      {(s.status === 'pending' || s.status === 'processing') && <ProcessingCard job={activeJob ?? s.active_job ?? s.last_job} />}
      {s.status === 'failed' && <FailedCard song={s} onDelete={() => setDialog('delete')} />}
      {ready &&
        (settings.isLoading ? (
          <div className="flex justify-center py-10 text-muted">
            <Spinner />
          </div>
        ) : (
          <Player
            key={`${s.id}:${s.stems.join(',')}:${version}`}
            song={s}
            version={version}
            metronomeDefault={settings.data?.metronome_volume ?? 70}
            snapshotRef={snapshotRef}
            onReprocess={() => setDialog('reprocess')}
          />
        ))}

      <NotesCard song={s} />

      {dialog === 'reprocess' && <ReprocessDialog song={s} onClose={() => setDialog(null)} />}
      {dialog === 'delete' && <DeleteDialog song={s} onClose={() => setDialog(null)} />}
      {dialog === 'export' && <ExportDialog song={s} snapshotRef={snapshotRef} onClose={() => setDialog(null)} />}
    </div>
  )
}

function BackLink() {
  const m = useT()
  return (
    <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-muted hover:text-fg">
      <ArrowLeftIcon size={13} />
      {m.app.back}
    </Link>
  )
}

function useSongPatch(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: SongPatch) => patchSong(id, patch),
    onMutate: (patch) => {
      qc.setQueryData<Song>(qk.song(id), (old) => (old ? ({ ...old, ...patch } as Song) : old))
    },
    onSuccess: (song) => {
      qc.setQueryData<Song>(qk.song(id), (old) => (old ? { ...song, player_state: old.player_state } : song))
      void qc.invalidateQueries({ queryKey: ['songs', 'list'] })
      void qc.invalidateQueries({ queryKey: qk.tags })
    },
    onError: () => qc.invalidateQueries({ queryKey: qk.song(id) }),
  })
}

function SongHeader({ song, ready, busy, onAction }: { song: Song; ready: boolean; busy: boolean; onAction: (d: 'reprocess' | 'delete' | 'export') => void }) {
  const { m, lang } = useI18n()
  const qc = useQueryClient()
  const patch = useSongPatch(song.id)
  const tags = useTags()
  const fileRef = useRef<HTMLInputElement>(null)
  const cover = useMutation({
    mutationFn: (f: File | null) => (f ? uploadCover(song.id, f) : deleteCover(song.id)),
    onSuccess: (s) => {
      qc.setQueryData(qk.song(song.id), s)
      void qc.invalidateQueries({ queryKey: ['songs', 'list'] })
    },
  })

  return (
    <header className="flex gap-5 rounded-xl border border-line bg-panel p-4">
      <div className="group relative h-32 w-32 shrink-0 overflow-hidden rounded-lg bg-raised">
        {song.cover_url ? (
          <img src={song.cover_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-[#2a2f3a] to-[#16181d]">
            <MusicIcon size={36} className="text-white/20" />
          </div>
        )}
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-black/60 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <button type="button" onClick={() => fileRef.current?.click()} className="flex items-center gap-1 rounded-md bg-white/10 px-2 py-1 text-[11px] font-medium hover:bg-white/20">
            <ImageIcon size={12} />
            {m.song.changeCover}
          </button>
          {song.has_cover && (
            <button type="button" onClick={() => cover.mutate(null)} className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-white/70 hover:text-white">
              <XIcon size={11} />
              {m.song.removeCover}
            </button>
          )}
        </div>
        {cover.isPending && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60">
            <Spinner />
          </div>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) cover.mutate(f)
            e.target.value = ''
          }}
        />
      </div>

      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-start gap-2">
          <h1 className="min-w-0 flex-1 text-2xl font-semibold tracking-tight">
            <InlineEdit value={song.title} label={m.song.titleLabel} placeholder={m.song.titleLabel} required onSave={(v) => patch.mutate({ title: v })} inputClassName="text-2xl h-9" />
          </h1>
          <button
            type="button"
            onClick={() => patch.mutate({ favorite: !song.favorite })}
            title={song.favorite ? m.library.unfavorite : m.library.favorite}
            aria-pressed={song.favorite}
            className={cx('mt-1 rounded-md p-1.5 transition-colors hover:bg-raised', song.favorite ? 'text-amber-300' : 'text-faint hover:text-fg')}
          >
            <StarIcon size={20} filled={song.favorite} />
          </button>
        </div>
        <div className="flex items-center gap-1 text-[15px] text-muted">
          <InlineEdit value={song.artist ?? ''} label={m.song.artistLabel} placeholder={m.song.addArtist} onSave={(v) => patch.mutate({ artist: v || null })} inputClassName="h-7 text-[15px]" />
          <span className="text-faint">·</span>
          <InlineEdit value={song.album ?? ''} label={m.song.albumLabel} placeholder={m.song.addAlbum} onSave={(v) => patch.mutate({ album: v || null })} inputClassName="h-7 text-[15px]" className="text-faint" />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-0.5 text-xs text-faint tabular-nums">
          <span>{formatDuration(song.duration_s)}</span>
          {song.bpm != null && <span>{formatBpm(song.bpm)} BPM</span>}
          {song.key_label && <span>{displayKey(song.key_label, lang)}</span>}
          <span>{fmt(m.stemMode.short, { n: song.stem_mode })}</span>
          {song.source_url ? (
            <a href={song.source_url} target="_blank" rel="noreferrer" className="max-w-[320px] truncate hover:text-accent">
              {song.source_url}
            </a>
          ) : song.original_filename ? (
            <span className="max-w-[320px] truncate">{song.original_filename}</span>
          ) : null}
        </div>
        <div className="pt-1.5">
          <TagEditor tags={song.tags} suggestions={(tags.data ?? []).map((t) => t.name)} placeholder={m.song.addTag} onChange={(t) => patch.mutate({ tags: t })} />
        </div>
        {(patch.error || cover.error) && <ErrorBox error={patch.error ?? cover.error} compact className="mt-2" />}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-2">
        <Button variant="primary" onClick={() => onAction('export')} disabled={!ready}>
          <DownloadIcon size={14} />
          {m.export.button}
        </Button>
        <Button onClick={() => onAction('reprocess')} disabled={busy || (song.status !== 'ready' && song.status !== 'failed')}>
          <RefreshIcon size={13} />
          {m.song.reprocess}
        </Button>
        <Button variant="ghost" className="hover:text-danger" onClick={() => onAction('delete')}>
          <TrashIcon size={13} />
          {m.app.delete}
        </Button>
      </div>
    </header>
  )
}

function useJobAction(songId: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: qk.jobs })
    void qc.invalidateQueries({ queryKey: qk.song(songId) })
    void qc.invalidateQueries({ queryKey: ['songs', 'list'] })
  }
}

function ReprocessBanner({ job }: { job: Job }) {
  const m = useT()
  const refresh = useJobAction(job.song_id)
  const cancel = useMutation({ mutationFn: () => cancelJob(job.id), onSuccess: refresh })
  return (
    <div className="flex items-center gap-4 rounded-xl border border-sky-400/25 bg-sky-500/5 px-4 py-3">
      <Spinner size={14} className="text-sky-300" />
      <span className="text-[13px] font-medium text-sky-200">{m.song.reprocessing}</span>
      <JobProgress job={job} className="flex-1" />
      <Button size="sm" variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
        {m.app.cancel}
      </Button>
      {cancel.error ? <ErrorBox error={cancel.error} compact /> : null}
    </div>
  )
}

function ProcessingCard({ job }: { job: Job | null }) {
  const m = useT()
  const refresh = useJobAction(job?.song_id ?? '')
  const cancel = useMutation({ mutationFn: () => cancelJob(job!.id), onSuccess: refresh })
  return (
    <div className="rounded-xl border border-line bg-panel px-6 py-8">
      <div className="mx-auto max-w-lg text-center">
        <h2 className="text-[15px] font-semibold">{m.song.processing}</h2>
        <p className="mt-1 text-[13px] text-muted">{m.song.processingBody}</p>
        {job && <JobProgress job={job} className="mt-5 text-left" />}
        {job && (job.status === 'queued' || job.status === 'running') && (
          <Button className="mt-5" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            {m.app.cancel}
          </Button>
        )}
        {cancel.error ? <ErrorBox error={cancel.error} className="mt-3 text-left" /> : null}
      </div>
    </div>
  )
}

function FailedCard({ song, onDelete }: { song: Song; onDelete: () => void }) {
  const m = useT()
  const job = song.last_job
  const refresh = useJobAction(song.id)
  const retry = useMutation({ mutationFn: () => retryJob(job!.id), onSuccess: refresh })
  const canceled = job?.status === 'canceled'
  return (
    <div className="rounded-xl border border-danger/25 bg-danger/5 px-6 py-6">
      <div className="mx-auto max-w-lg">
        <h2 className="text-[15px] font-semibold">{canceled ? m.song.canceledTitle : m.song.failedTitle}</h2>
        {canceled ? (
          <p className="mt-1 text-[13px] text-muted">{m.song.canceledBody}</p>
        ) : (
          <ErrorText code={job?.error_code ?? 'INTERNAL_ERROR'} detail={job?.error_detail ?? null} m={m} className="mt-3" />
        )}
        <div className="mt-4 flex gap-2">
          {job && (
            <Button variant="primary" onClick={() => retry.mutate()} disabled={retry.isPending}>
              {retry.isPending ? <Spinner size={12} /> : <RefreshIcon size={13} />}
              {m.app.retry}
            </Button>
          )}
          <Button variant="danger" onClick={onDelete}>
            <TrashIcon size={13} />
            {m.app.delete}
          </Button>
        </div>
        {retry.error ? <ErrorBox error={retry.error} className="mt-3" /> : null}
      </div>
    </div>
  )
}

function NotesCard({ song }: { song: Song }) {
  const m = useT()
  const qc = useQueryClient()
  const [text, setText] = useState(song.notes)
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [error, setError] = useState<unknown>(null)
  const lastSaved = useRef(song.notes)
  const dirty = useRef(false)

  useEffect(() => {
    if (!dirty.current) {
      setText(song.notes)
      lastSaved.current = song.notes
    }
  }, [song.notes])

  useEffect(() => {
    if (text === lastSaved.current) return
    dirty.current = true
    const id = setTimeout(() => {
      setStatus('saving')
      const value = text
      patchSong(song.id, { notes: value })
        .then((s) => {
          lastSaved.current = value
          dirty.current = false
          setStatus('saved')
          setError(null)
          qc.setQueryData<Song>(qk.song(song.id), (old) => (old ? { ...old, notes: s.notes } : old))
        })
        .catch((err: unknown) => {
          setStatus('error')
          setError(err)
        })
    }, 800)
    return () => clearTimeout(id)
  }, [text, song.id, qc])

  return (
    <section className="rounded-xl border border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h3 className="text-[13px] font-semibold">{m.song.notes}</h3>
        <span className="text-[11px] text-faint">
          {status === 'saving' ? m.app.saving : status === 'saved' && text === lastSaved.current ? m.app.saved : ''}
        </span>
      </div>
      <textarea
        value={text}
        maxLength={20000}
        onChange={(e) => setText(e.target.value)}
        placeholder={m.song.notesPlaceholder}
        className="block min-h-28 w-full resize-y bg-transparent px-4 py-3 text-[13px] leading-relaxed outline-none placeholder:text-faint"
      />
      {error ? <ErrorBox error={error} compact className="m-3 mt-0" /> : null}
    </section>
  )
}

function ReprocessDialog({ song, onClose }: { song: Song; onClose: () => void }) {
  const m = useT()
  const qc = useQueryClient()
  const [mode, setMode] = useState<StemMode>(song.stem_mode)
  const run = useMutation({
    mutationFn: () => reprocessSong(song.id, mode),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.jobs })
      void qc.invalidateQueries({ queryKey: qk.song(song.id) })
      onClose()
    },
  })
  return (
    <Modal
      title={m.song.reprocessTitle}
      onClose={onClose}
      width={600}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {m.app.cancel}
          </Button>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending && <Spinner size={12} />}
            {m.song.reprocessStart}
          </Button>
        </>
      }
    >
      <p className="mb-4 text-[13px] text-muted">{m.song.reprocessBody}</p>
      <StemModeSelect value={mode} onChange={setMode} />
      {run.error ? <ErrorBox error={run.error} className="mt-3" /> : null}
    </Modal>
  )
}

function DeleteDialog({ song, onClose }: { song: Song; onClose: () => void }) {
  const m = useT()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const del = useMutation({
    mutationFn: () => deleteSong(song.id),
    onSuccess: () => {
      qc.removeQueries({ queryKey: qk.song(song.id) })
      void qc.invalidateQueries({ queryKey: qk.songs })
      void qc.invalidateQueries({ queryKey: qk.jobs })
      void qc.invalidateQueries({ queryKey: qk.tags })
      navigate('/')
    },
  })
  return (
    <ConfirmDialog
      title={m.song.deleteTitle}
      body={fmt(m.song.deleteBody, { title: song.title })}
      confirmLabel={m.app.delete}
      onConfirm={() => del.mutate()}
      onClose={onClose}
      busy={del.isPending}
      error={del.error}
    />
  )
}
