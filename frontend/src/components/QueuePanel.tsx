import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { cancelJob, retryJob } from '../api/endpoints'
import { isActiveJob, qk } from '../api/queries'
import type { Job } from '../api/types'
import { useT } from '../i18n'
import { fmt } from '../i18n'
import { RefreshIcon, XIcon } from './icons'
import { Button, ErrorBox, ErrorText, JobProgress, JobStatusBadge, Spinner } from './ui'

export function QueuePanel({ jobs, loading, onClose }: { jobs: Job[] | undefined; loading: boolean; onClose: () => void }) {
  const m = useT()
  const active = (jobs ?? []).filter(isActiveJob)
  const finished = (jobs ?? []).filter((j) => !isActiveJob(j))
  return (
    <aside className="flex h-full w-[320px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex h-12 items-center justify-between border-b border-line px-4">
        <h2 className="text-[13px] font-semibold tracking-wide">{m.queue.title}</h2>
        <button className="text-muted hover:text-fg" onClick={onClose} aria-label={m.app.close}>
          <XIcon size={15} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading && !jobs ? (
          <div className="flex justify-center p-6 text-muted">
            <Spinner />
          </div>
        ) : !jobs?.length ? (
          <p className="p-5 text-[13px] leading-relaxed text-faint">{m.queue.empty}</p>
        ) : (
          <>
            {active.length > 0 && <Section title={m.queue.active} jobs={active} />}
            {finished.length > 0 && <Section title={m.queue.finished} jobs={finished} />}
          </>
        )}
      </div>
    </aside>
  )
}

function Section({ title, jobs }: { title: string; jobs: Job[] }) {
  return (
    <section>
      <h3 className="sticky top-0 z-10 bg-panel/95 px-4 pt-3 pb-1.5 text-[11px] font-semibold tracking-wider text-faint uppercase backdrop-blur">
        {title}
      </h3>
      <ul className="space-y-px px-2 pb-2">
        {jobs.map((j) => (
          <JobRow key={j.id} job={j} />
        ))}
      </ul>
    </section>
  )
}

function JobRow({ job }: { job: Job }) {
  const m = useT()
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.jobs })
    void qc.invalidateQueries({ queryKey: qk.songs })
  }
  const cancel = useMutation({ mutationFn: () => cancelJob(job.id), onSuccess: refresh })
  const retry = useMutation({ mutationFn: () => retryJob(job.id), onSuccess: refresh })
  const active = isActiveJob(job)
  const canRetry = job.status === 'failed' || job.status === 'canceled'
  return (
    <li className="group rounded-lg px-2 py-2.5 hover:bg-panel-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <Link to={`/songs/${job.song_id}`} className="block truncate text-[13px] font-medium hover:text-accent" title={job.song_title}>
            {job.song_title}
          </Link>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-faint">
            <JobStatusBadge status={job.status} />
            <span>{fmt(m.stemMode.short, { n: job.stem_mode })}</span>
            {job.attempts > 1 && <span>· {fmt(m.queue.attempt, { n: job.attempts })}</span>}
          </div>
        </div>
        {active && (
          <Button size="sm" variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            {m.queue.cancel}
          </Button>
        )}
        {canRetry && (
          <Button size="sm" variant="ghost" onClick={() => retry.mutate()} disabled={retry.isPending}>
            <RefreshIcon size={12} />
            {m.queue.retry}
          </Button>
        )}
      </div>
      {active && <JobProgress job={job} className="mt-2" />}
      {job.status === 'failed' && <ErrorText code={job.error_code} detail={job.error_detail} compact className="mt-2" m={m} />}
      {(cancel.error || retry.error) && <ErrorBox error={cancel.error ?? retry.error} compact className="mt-2" />}
    </li>
  )
}
