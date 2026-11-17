import { useState, type ReactNode } from 'react'
import type { Marker } from '../api/types'
import { FlagIcon, LoopIcon, PlusIcon, TrashIcon } from '../components/icons'
import { cx, ErrorBox, IconButton } from '../components/ui'
import { useT } from '../i18n'
import { formatTimePrecise } from '../lib/format'

export function MarkersPanel(p: {
  markers: Marker[]
  activeLoop: { a: number; b: number } | null
  error: unknown
  disabled: boolean
  onAdd: () => void
  onJump: (t: number) => void
  onActivateLoop: (mk: Marker) => void
  onRename: (mk: Marker, name: string) => void
  onDelete: (mk: Marker) => void
}) {
  const m = useT()
  const markers = p.markers.filter((x) => x.kind === 'marker')
  const loops = p.markers.filter((x) => x.kind === 'loop')
  return (
    <section className="flex flex-col rounded-xl border border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h3 className="text-[13px] font-semibold">{m.markers.title}</h3>
        <button
          type="button"
          onClick={p.onAdd}
          disabled={p.disabled}
          className="flex h-7 items-center gap-1 rounded-md px-2 text-xs text-muted hover:bg-raised hover:text-fg disabled:opacity-40"
        >
          <PlusIcon size={13} />
          {m.markers.add}
        </button>
      </div>
      {p.error ? <ErrorBox error={p.error} compact className="m-3 mb-0" /> : null}
      <div className="grid grid-cols-2 divide-x divide-line">
        <List title={m.markers.markers} empty={m.markers.empty}>
          {markers.map((mk) => (
            <Row
              key={mk.id}
              marker={mk}
              icon={<FlagIcon size={12} className="text-amber-300" />}
              time={formatTimePrecise(mk.start_s)}
              actionLabel={m.markers.jump}
              onAction={() => p.onJump(mk.start_s)}
              onRename={(n) => p.onRename(mk, n)}
              onDelete={() => p.onDelete(mk)}
            />
          ))}
        </List>
        <List title={m.markers.loops} empty={m.markers.emptyLoops}>
          {loops.map((mk) => (
            <Row
              key={mk.id}
              marker={mk}
              active={!!p.activeLoop && Math.abs(p.activeLoop.a - mk.start_s) < 1e-3 && Math.abs(p.activeLoop.b - (mk.end_s ?? 0)) < 1e-3}
              icon={<LoopIcon size={12} className="text-accent" />}
              time={`${formatTimePrecise(mk.start_s)} – ${formatTimePrecise(mk.end_s ?? mk.start_s)}`}
              actionLabel={m.markers.activate}
              onAction={() => p.onActivateLoop(mk)}
              onRename={(n) => p.onRename(mk, n)}
              onDelete={() => p.onDelete(mk)}
            />
          ))}
        </List>
      </div>
    </section>
  )
}

function List({ title, empty, children }: { title: string; empty: string; children: ReactNode[] }) {
  return (
    <div className="min-w-0 p-2">
      <h4 className="px-2 pt-1 pb-1.5 text-[11px] font-semibold tracking-wider text-faint uppercase">{title}</h4>
      {children.length ? <ul className="max-h-56 space-y-px overflow-y-auto">{children}</ul> : <p className="px-2 pb-2 text-xs leading-relaxed text-faint">{empty}</p>}
    </div>
  )
}

function Row(p: {
  marker: Marker
  icon: ReactNode
  time: string
  active?: boolean
  actionLabel: string
  onAction: () => void
  onRename: (name: string) => void
  onDelete: () => void
}) {
  const m = useT()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(p.marker.name)
  const commit = () => {
    setEditing(false)
    const n = name.trim().slice(0, 60)
    if (n && n !== p.marker.name) p.onRename(n)
    else setName(p.marker.name)
  }
  return (
    <li className={cx('group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-panel-2', p.active && 'bg-accent/10')}>
      {p.icon}
      {editing ? (
        <input
          autoFocus
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') {
              setName(p.marker.name)
              setEditing(false)
            }
          }}
          className="h-6 min-w-0 flex-1 rounded border border-accent bg-bg px-1.5 text-[13px] outline-none"
        />
      ) : (
        <button type="button" onClick={p.onAction} title={p.actionLabel} className="min-w-0 flex-1 truncate text-left text-[13px] hover:text-accent" onDoubleClick={() => setEditing(true)}>
          {p.marker.name}
        </button>
      )}
      <span className="shrink-0 font-mono text-[11px] text-faint tabular-nums">{p.time}</span>
      <div className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <IconButton label={m.app.rename} className="h-6 w-6" onClick={() => setEditing(true)}>
          <span className="text-[11px]">✎</span>
        </IconButton>
        <IconButton label={m.app.delete} className="h-6 w-6 hover:text-danger" onClick={p.onDelete}>
          <TrashIcon size={12} />
        </IconButton>
      </div>
    </li>
  )
}
