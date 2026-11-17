import { useState } from 'react'
import { NavLink, Outlet } from 'react-router'
import { isActiveJob, useJobsPolling } from '../api/queries'
import { useI18n } from '../i18n'
import { GlobeIcon, QueueIcon } from './icons'
import { QueuePanel } from './QueuePanel'
import { cx } from './ui'

const QUEUE_KEY = 'mt.queueOpen'

function readQueueOpen(): boolean {
  try {
    return localStorage.getItem(QUEUE_KEY) !== '0'
  } catch {
    return true
  }
}

export function AppShell() {
  const { m, lang } = useI18n()
  const jobs = useJobsPolling()
  const [queueOpen, setQueueOpen] = useState(readQueueOpen)
  const activeCount = (jobs.data ?? []).filter(isActiveJob).length

  const toggleQueue = () =>
    setQueueOpen((o) => {
      try {
        localStorage.setItem(QUEUE_KEY, o ? '0' : '1')
      } catch {
        // ignore
      }
      return !o
    })

  const navClass = ({ isActive }: { isActive: boolean }) =>
    cx(
      'relative flex h-12 items-center px-1 text-[13px] font-medium transition-colors',
      isActive ? 'text-fg after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent' : 'text-muted hover:text-fg',
    )

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-8 border-b border-line bg-panel px-5">
        <NavLink to="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">{m.app.name}</span>
        </NavLink>
        <nav className="flex items-center gap-6">
          <NavLink to="/" end className={navClass}>
            {m.nav.library}
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            {m.nav.settings}
          </NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <NavLink
            to="/settings"
            className="flex h-7 items-center gap-1.5 rounded-md border border-line px-2 text-xs text-muted hover:text-fg"
            title={m.app.language}
          >
            <GlobeIcon size={13} />
            {lang === 'pt-BR' ? 'PT-BR' : 'EN'}
          </NavLink>
          <button
            type="button"
            onClick={toggleQueue}
            aria-pressed={queueOpen}
            title={m.queue.toggle}
            className={cx(
              'flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors',
              queueOpen ? 'border-accent/40 bg-accent/10 text-accent' : 'border-line text-muted hover:text-fg',
            )}
          >
            <QueueIcon size={14} />
            {m.nav.queue}
            {activeCount > 0 && (
              <span className="ml-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-strong px-1 text-[10px] font-bold text-white">
                {activeCount}
              </span>
            )}
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {queueOpen && <QueuePanel jobs={jobs.data} loading={jobs.isLoading} onClose={toggleQueue} />}
      </div>
    </div>
  )
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#22262c" />
      <g strokeLinecap="round" strokeWidth="3">
        <path d="M8 12v8" stroke="#F472B6" />
        <path d="M13 8v16" stroke="#F59E0B" />
        <path d="M18 11v10" stroke="#22D3EE" />
        <path d="M23 14v4" stroke="#A78BFA" />
      </g>
    </svg>
  )
}
