import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { listSongs, patchSong } from '../api/endpoints'
import { qk, useActiveJobForSong, useHealth, useTags } from '../api/queries'
import type { Song, SongFilters, SongSort, SongStatus } from '../api/types'
import { AddMusicDialog } from '../components/AddMusicDialog'
import { FolderIcon, LinkIcon, MusicIcon, PlusIcon, SearchIcon, SortIcon, StarIcon, UploadIcon, XIcon } from '../components/icons'
import { Button, countLabel, cx, ErrorBox, JobProgress, selectClass, SongStatusBadge, Spinner } from '../components/ui'
import { fmt, useI18n } from '../i18n'
import { formatBpm, formatDuration } from '../lib/format'
import { useDebounced } from '../lib/hooks'
import { STEM_COLORS, STEMS_BY_MODE } from '../lib/stems'
import { displayKey } from '../music/theory'

const SORTS: SongSort[] = ['created_at', 'title', 'artist', 'bpm', 'duration_s']
const STATUSES: SongStatus[] = ['pending', 'processing', 'ready', 'failed']

export function LibraryPage() {
  const { m } = useI18n()
  const [params, setParams] = useSearchParams()
  const [addOpen, setAddOpen] = useState(false)
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebounced(search, 300)

  const filters: SongFilters = {
    q: q.trim() || undefined,
    tag: params.get('tag') || undefined,
    favorite: params.get('favorite') === 'true' || undefined,
    status: (params.get('status') as SongStatus | null) || undefined,
    sort: (params.get('sort') as SongSort | null) || 'created_at',
    order: (params.get('order') as 'asc' | 'desc' | null) || 'desc',
  }

  const setParam = (key: string, value: string | null) => {
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (value === null || value === '') next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )
  }

  useEffect(() => {
    if ((params.get('q') ?? '') !== q) setParam('q', q || null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const songs = useQuery({ queryKey: qk.songList(filters), queryFn: () => listSongs(filters), placeholderData: keepPreviousData })
  const tags = useTags()
  const anyFilter = !!(filters.q || filters.tag || filters.favorite || filters.status)

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{m.library.title}</h1>
          {songs.data && <p className="mt-0.5 text-[13px] text-faint">{countLabel(m, songs.data.length)}</p>}
        </div>
        <Button variant="primary" onClick={() => setAddOpen(true)}>
          <PlusIcon size={15} />
          {m.library.add}
        </Button>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel p-2">
        <div className="relative min-w-[260px] flex-1">
          <SearchIcon size={14} className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-faint" />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={m.library.search}
            className="h-8 w-full rounded-md border border-transparent bg-bg pr-7 pl-8 text-[13px] outline-none placeholder:text-faint focus:border-accent"
          />
          {search && (
            <button className="absolute top-1/2 right-2 -translate-y-1/2 text-faint hover:text-fg" onClick={() => setSearch('')} aria-label={m.app.close}>
              <XIcon size={13} />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => setParam('favorite', filters.favorite ? null : 'true')}
          aria-pressed={!!filters.favorite}
          className={cx(
            'flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[13px] transition-colors',
            filters.favorite ? 'border-amber-400/40 bg-amber-400/10 text-amber-300' : 'border-line-strong text-muted hover:text-fg',
          )}
        >
          <StarIcon size={14} filled={!!filters.favorite} />
          {m.library.favorites}
        </button>
        <select className={selectClass} value={filters.tag ?? ''} onChange={(e) => setParam('tag', e.target.value || null)}>
          <option value="">{m.library.allTags}</option>
          {tags.data?.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name} ({t.count})
            </option>
          ))}
        </select>
        <select className={selectClass} value={filters.status ?? ''} onChange={(e) => setParam('status', e.target.value || null)}>
          <option value="">{m.library.allStatuses}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {m.songStatus[s]}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-xs text-faint">{m.library.sortBy}</span>
          <select className={selectClass} value={filters.sort} onChange={(e) => setParam('sort', e.target.value)}>
            {SORTS.map((s) => (
              <option key={s} value={s}>
                {m.library.sort[s]}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-line-strong text-muted hover:text-fg"
            onClick={() => setParam('order', filters.order === 'desc' ? 'asc' : 'desc')}
            title={filters.order === 'desc' ? m.library.descending : m.library.ascending}
            aria-label={filters.order === 'desc' ? m.library.descending : m.library.ascending}
          >
            <SortIcon size={15} desc={filters.order === 'desc'} />
          </button>
        </div>
      </div>

      {songs.isLoading ? (
        <div className="flex justify-center py-20 text-muted">
          <Spinner size={22} />
        </div>
      ) : songs.error ? (
        <ErrorBox error={songs.error} />
      ) : !songs.data?.length ? (
        anyFilter ? (
          <div className="py-20 text-center text-muted">
            <p>{m.library.noResults}</p>
            <Button
              className="mt-3"
              variant="ghost"
              onClick={() => {
                setSearch('')
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              {m.library.clearFilters}
            </Button>
          </div>
        ) : (
          <EmptyLibrary onAdd={() => setAddOpen(true)} />
        )
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-4">
          {songs.data.map((s) => (
            <SongCard key={s.id} song={s} />
          ))}
        </div>
      )}

      {addOpen && <AddMusicDialog onClose={() => setAddOpen(false)} />}
    </div>
  )
}

function EmptyLibrary({ onAdd }: { onAdd: () => void }) {
  const { m } = useI18n()
  const health = useHealth()
  const inbox = health.data ? `${health.data.data_dir.replace(/\/$/, '')}/inbox` : '<data_dir>/inbox'
  const items = [
    { icon: <UploadIcon size={18} />, text: m.library.emptyUpload },
    { icon: <LinkIcon size={18} />, text: m.library.emptyUrl },
    { icon: <FolderIcon size={18} />, text: m.library.emptyWatch, code: inbox },
  ]
  return (
    <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-dashed border-line-strong bg-panel/50 px-8 py-10 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-raised text-accent">
        <MusicIcon size={22} />
      </div>
      <h2 className="text-lg font-semibold">{m.library.emptyTitle}</h2>
      <p className="mt-1.5 text-[13px] text-muted">{m.library.emptyBody}</p>
      <ul className="mt-6 space-y-3 text-left">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-3 rounded-lg border border-line bg-panel px-4 py-3">
            <span className="mt-0.5 text-muted">{it.icon}</span>
            <div className="min-w-0 text-[13px]">
              <p>{it.text}</p>
              {it.code && <code className="mt-1.5 block truncate rounded bg-bg px-2 py-1 font-mono text-xs text-accent">{it.code}</code>}
            </div>
          </li>
        ))}
      </ul>
      <Button variant="primary" className="mt-6" onClick={onAdd}>
        <PlusIcon size={15} />
        {m.library.add}
      </Button>
    </div>
  )
}

function SongCard({ song }: { song: Song }) {
  const { m, lang } = useI18n()
  const qc = useQueryClient()
  const job = useActiveJobForSong(song.id, song.active_job)
  const [favorite, setFavorite] = useState(song.favorite)
  useEffect(() => setFavorite(song.favorite), [song.favorite])
  const fav = useMutation({
    mutationFn: (v: boolean) => patchSong(song.id, { favorite: v }),
    onMutate: (v) => setFavorite(v),
    onError: () => setFavorite(song.favorite),
    onSettled: () => qc.invalidateQueries({ queryKey: qk.songs }),
  })
  const stems = STEMS_BY_MODE[song.stem_mode] ?? []
  const lastFailed = song.status === 'failed' && song.last_job?.status === 'canceled'

  return (
    <Link
      to={`/songs/${song.id}`}
      className="group relative flex flex-col overflow-hidden rounded-xl border border-line bg-panel transition-all hover:-translate-y-px hover:border-line-strong hover:bg-panel-2 hover:shadow-lg hover:shadow-black/30"
    >
      <div className="relative aspect-[16/10] overflow-hidden bg-raised">
        {song.cover_url ? (
          <img src={song.cover_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <CoverPlaceholder seed={song.title} />
        )}
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            fav.mutate(!favorite)
          }}
          title={favorite ? m.library.unfavorite : m.library.favorite}
          aria-label={favorite ? m.library.unfavorite : m.library.favorite}
          aria-pressed={favorite}
          className={cx(
            'absolute top-2 right-2 flex h-8 w-8 items-center justify-center rounded-full bg-black/50 backdrop-blur transition',
            favorite ? 'text-amber-300' : 'text-white/70 opacity-0 group-hover:opacity-100 hover:text-white focus-visible:opacity-100',
          )}
        >
          <StarIcon size={16} filled={favorite} />
        </button>
        <div className="absolute bottom-2 left-2">
          {song.status !== 'ready' && <SongStatusBadge status={song.status} />}
        </div>
        <div className="absolute inset-x-0 bottom-0 flex h-1">
          {stems.map((s) => (
            <span key={s} className="flex-1" style={{ background: STEM_COLORS[s], opacity: song.status === 'ready' ? 0.9 : 0.25 }} />
          ))}
        </div>
      </div>
      <div className="flex flex-1 flex-col px-3.5 pt-3 pb-3">
        <h3 className="truncate text-[14px] font-semibold" title={song.title}>
          {song.title}
        </h3>
        <p className="truncate text-[12px] text-muted">{song.artist || m.library.unknownArtist}</p>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint tabular-nums">
          <span>{formatDuration(song.duration_s)}</span>
          {song.bpm != null && <span>{formatBpm(song.bpm)} BPM</span>}
          {song.key_label && <span>{displayKey(song.key_label, lang)}</span>}
          <span>{fmt(m.stemMode.short, { n: song.stem_mode })}</span>
        </div>
        {song.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {song.tags.slice(0, 4).map((t) => (
              <span key={t} className="rounded bg-raised px-1.5 py-0.5 text-[10px] text-muted">
                {t}
              </span>
            ))}
            {song.tags.length > 4 && <span className="px-1 text-[10px] text-faint">+{song.tags.length - 4}</span>}
          </div>
        )}
        {job && <JobProgress job={job} className="mt-3" />}
        {song.status === 'failed' && (
          <p className="mt-2 truncate text-[11px] text-danger">
            {lastFailed ? m.jobStatus.canceled : song.last_job?.error_code ? (m.errors as Record<string, string>)[song.last_job.error_code] ?? song.last_job.error_code : m.songStatus.failed}
          </p>
        )}
      </div>
    </Link>
  )
}

function CoverPlaceholder({ seed }: { seed: string }) {
  const hue = useMemo(() => {
    let h = 0
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0
    return h % 360
  }, [seed])
  return (
    <div
      className="flex h-full w-full items-center justify-center"
      style={{ background: `linear-gradient(135deg, hsl(${hue} 30% 20%), hsl(${(hue + 50) % 360} 25% 12%))` }}
    >
      <MusicIcon size={34} className="text-white/25" />
    </div>
  )
}
