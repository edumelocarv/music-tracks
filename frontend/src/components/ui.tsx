import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, toApiError } from '../api/client'
import type { Job, JobStatus, SongStatus } from '../api/types'
import { errorText, fmt, useT } from '../i18n'
import type { Messages } from '../i18n/en'
import { AlertIcon, ChevronRightIcon, XIcon } from './icons'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent-strong text-white hover:bg-accent shadow-sm shadow-black/30',
  secondary: 'bg-raised text-fg border border-line-strong hover:bg-[#2a2f36] hover:border-[#4a505a]',
  ghost: 'text-muted hover:text-fg hover:bg-raised',
  danger: 'bg-danger/15 text-danger border border-danger/30 hover:bg-danger/25',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' }) {
  return (
    <button
      type="button"
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors select-none',
        'disabled:opacity-40 disabled:pointer-events-none whitespace-nowrap',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  )
}

export function IconButton({
  label,
  active,
  className,
  activeColor,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean; activeColor?: string }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cx(
        'inline-flex items-center justify-center rounded-md transition-colors h-8 w-8 select-none',
        'disabled:opacity-35 disabled:pointer-events-none',
        active ? 'bg-accent/20 text-accent' : 'text-muted hover:text-fg hover:bg-raised',
        className,
      )}
      style={active && activeColor ? { color: activeColor, background: `${activeColor}26` } : undefined}
      {...rest}
    />
  )
}

export function Spinner({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cx('inline-block animate-spin rounded-full border-2 border-current border-r-transparent opacity-70', className)}
      style={{ width: size, height: size }}
      aria-hidden
    />
  )
}

export function ProgressBar({ value, color, className }: { value: number | null; color?: string; className?: string }) {
  return (
    <div className={cx('h-1.5 w-full overflow-hidden rounded-full bg-line', className)}>
      {value === null ? (
        <div className="h-full w-1/3 animate-pulse rounded-full bg-accent/60" />
      ) : (
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color }}
        />
      )}
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  width = 520,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  width?: number
}) {
  const m = useT()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-6 pt-[10vh] backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal
        className="w-full rounded-xl border border-line-strong bg-panel shadow-2xl shadow-black/60"
        style={{ maxWidth: width }}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <IconButton label={m.app.close} onClick={onClose}>
            <XIcon />
          </IconButton>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onClose,
  busy,
  error,
}: {
  title: string
  body: ReactNode
  confirmLabel: string
  onConfirm: () => void
  onClose: () => void
  busy?: boolean
  error?: unknown
}) {
  const m = useT()
  return (
    <Modal
      title={title}
      onClose={onClose}
      width={440}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {m.app.cancel}
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            {busy && <Spinner size={12} />}
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-muted">{body}</div>
      {error ? <ErrorBox error={error} className="mt-3" /> : null}
    </Modal>
  )
}

/** Translated error with the technical detail in a collapsible "Details". */
export function ErrorBox({ error, className, compact }: { error: unknown; className?: string; compact?: boolean }) {
  const m = useT()
  const e = error instanceof ApiError ? error : toApiError(error)
  return <ErrorText code={e.code} detail={e.detail} className={className} compact={compact} m={m} />
}

export function ErrorText({
  code,
  detail,
  className,
  compact,
  m,
}: {
  code: string | null
  detail: string | null
  className?: string
  compact?: boolean
  m: Messages
}) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className={cx(
        'rounded-md border border-danger/25 bg-danger/10 text-[13px] text-danger',
        compact ? 'px-2.5 py-1.5' : 'px-3 py-2',
        className,
      )}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertIcon size={14} className="mt-0.5 shrink-0" />
        <span className="flex-1">{errorText(m, code)}</span>
        {detail && (
          <button
            type="button"
            className="flex shrink-0 items-center gap-0.5 text-xs text-danger/70 hover:text-danger"
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronRightIcon size={12} className={cx('transition-transform', open && 'rotate-90')} />
            {m.app.details}
          </button>
        )}
      </div>
      {open && detail && (
        <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-black/30 p-2 font-mono text-[11px] text-danger/80">
          {detail}
        </pre>
      )}
    </div>
  )
}

const SONG_STATUS_STYLE: Record<SongStatus, string> = {
  pending: 'bg-slate-500/15 text-slate-300 border-slate-400/20',
  processing: 'bg-sky-500/15 text-sky-300 border-sky-400/25',
  ready: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/25',
  failed: 'bg-red-500/15 text-red-300 border-red-400/25',
}

const JOB_STATUS_STYLE: Record<JobStatus, string> = {
  queued: 'bg-slate-500/15 text-slate-300 border-slate-400/20',
  running: 'bg-sky-500/15 text-sky-300 border-sky-400/25',
  done: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/25',
  failed: 'bg-red-500/15 text-red-300 border-red-400/25',
  canceled: 'bg-zinc-500/15 text-zinc-400 border-zinc-400/20',
}

export function Badge({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span
      className={cx(
        'inline-flex h-5 items-center gap-1 rounded-full border px-2 text-[11px] font-medium leading-none whitespace-nowrap',
        className,
      )}
    >
      {children}
    </span>
  )
}

export function SongStatusBadge({ status }: { status: SongStatus }) {
  const m = useT()
  return <Badge className={SONG_STATUS_STYLE[status]}>{m.songStatus[status]}</Badge>
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const m = useT()
  return <Badge className={JOB_STATUS_STYLE[status]}>{m.jobStatus[status]}</Badge>
}

/** `"<step_index>/<step_count> <step name> <step_progress>%"` (§7.2), or the model download notice. */
export function jobProgressText(m: Messages, job: Job): string {
  if (job.status === 'queued' || !job.step) return m.steps.waiting
  const step = m.steps[job.step]
  const base = `${job.step_index}/${job.step_count} ${step} ${Math.round(job.step_progress)}%`
  return job.step_detail === 'downloading_model' ? `${base} · ${m.steps.downloadingModel}` : base
}

/** Overall progress estimate for the bar (0–100), null when indeterminate. */
export function jobProgressValue(job: Job): number | null {
  if (job.status === 'queued' || !job.step || job.step_count <= 0) return null
  return ((job.step_index - 1 + job.step_progress / 100) / job.step_count) * 100
}

export function JobProgress({ job, className }: { job: Job; className?: string }) {
  const m = useT()
  return (
    <div className={cx('space-y-1.5', className)}>
      <div className="flex items-center gap-2 text-xs text-muted">
        {job.status === 'running' && <Spinner size={10} />}
        <span className="truncate tabular-nums">{jobProgressText(m, job)}</span>
      </div>
      <ProgressBar value={jobProgressValue(job)} />
    </div>
  )
}

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium tracking-wide text-muted uppercase">{label}</span>
      {children}
      {hint && <span className="block text-xs text-faint">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'h-8 w-full rounded-md border border-line-strong bg-bg px-2.5 text-[13px] text-fg placeholder:text-faint outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/25 disabled:opacity-50'

export const selectClass =
  'h-8 rounded-md border border-line-strong bg-bg pl-2 pr-7 text-[13px] text-fg outline-none focus:border-accent focus:ring-2 focus:ring-accent/25'

/** Click-outside helper for popovers. */
export function useClickOutside<T extends HTMLElement>(onOutside: () => void, enabled = true) {
  const ref = useRef<T>(null)
  useEffect(() => {
    if (!enabled) return
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside()
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [onOutside, enabled])
  return ref
}

export function countLabel(m: Messages, n: number) {
  return n === 1 ? m.library.countOne : fmt(m.library.count, { n })
}
