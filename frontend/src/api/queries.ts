import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import * as api from './endpoints'
import type { Job, SongFilters } from './types'

export const qk = {
  health: ['health'] as const,
  settings: ['settings'] as const,
  tags: ['tags'] as const,
  jobs: ['jobs'] as const,
  songs: ['songs'] as const,
  songList: (f: SongFilters) => ['songs', 'list', f] as const,
  song: (id: string) => ['songs', 'detail', id] as const,
  peaks: (id: string, v: number) => ['peaks', id, v] as const,
  analysis: (id: string, v: number) => ['analysis', id, v] as const,
  markers: (id: string) => ['markers', id] as const,
}

export const isActiveJob = (j: Pick<Job, 'status'> | null | undefined) => !!j && (j.status === 'queued' || j.status === 'running')

export function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: api.getSettings, staleTime: 60_000, retry: 1 })
}

export function useHealth() {
  return useQuery({ queryKey: qk.health, queryFn: api.getHealth, staleTime: 30_000, retry: 1 })
}

export function useTags() {
  return useQuery({ queryKey: qk.tags, queryFn: api.getTags, staleTime: 10_000 })
}

/**
 * Polls `GET /jobs` (1 s while any job is queued/running, else 10 s) and invalidates
 * song queries whenever a job appears, disappears or changes status.
 * Mount once (app shell); other components read the cache via `useJobsData`.
 */
export function useJobsPolling() {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: qk.jobs,
    queryFn: () => api.listJobs(20),
    refetchInterval: (q) => ((q.state.data ?? []).some(isActiveJob) ? 1000 : 10_000),
    refetchIntervalInBackground: true,
  })
  const prev = useRef<Map<string, string> | null>(null)
  useEffect(() => {
    const jobs = query.data
    if (!jobs) return
    const now = new Map(jobs.map((j) => [j.id, j.status]))
    const before = prev.current
    prev.current = now
    if (!before) return
    let changed = false
    for (const [id, status] of now) if (before.get(id) !== status) changed = true
    for (const id of before.keys()) if (!now.has(id)) changed = true
    if (changed) {
      void qc.invalidateQueries({ queryKey: qk.songs })
      void qc.invalidateQueries({ queryKey: qk.tags })
    }
  }, [query.data, qc])
  return query
}

/** Reads the jobs list kept fresh by `useJobsPolling` (no extra polling). */
export function useJobsData() {
  return useQuery({ queryKey: qk.jobs, queryFn: () => api.listJobs(20), staleTime: Infinity })
}

/** Live version of a job (from the polled list) falling back to the given snapshot. */
export function useLiveJob(job: Job | null | undefined): Job | null {
  const { data } = useJobsData()
  if (!job) return null
  return data?.find((j) => j.id === job.id) ?? job
}

/** Active job for a song from the polled list (falls back to the song's snapshot). */
export function useActiveJobForSong(songId: string, snapshot: Job | null): Job | null {
  const { data } = useJobsData()
  const live = data?.find((j) => j.song_id === songId && isActiveJob(j))
  if (live) return live
  if (snapshot && data) {
    const fresh = data.find((j) => j.id === snapshot.id)
    if (fresh && !isActiveJob(fresh)) return null
  }
  return snapshot && isActiveJob(snapshot) ? snapshot : null
}
