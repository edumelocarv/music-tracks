import { useEffect, useId, useState, type KeyboardEvent } from 'react'
import { XIcon } from './icons'
import { cx } from './ui'

/** Click-to-edit text. Commits on Enter/blur, cancels on Escape. */
export function InlineEdit({
  value,
  placeholder,
  onSave,
  className,
  inputClassName,
  maxLength = 200,
  required,
  label,
}: {
  value: string
  placeholder: string
  onSave: (v: string) => void
  className?: string
  inputClassName?: string
  maxLength?: number
  required?: boolean
  label: string
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value)
  useEffect(() => {
    if (!editing) setText(value)
  }, [value, editing])
  const commit = () => {
    setEditing(false)
    const v = text.trim()
    if (required && !v) return setText(value)
    if (v !== value) onSave(v)
  }
  if (editing) {
    return (
      <input
        autoFocus
        aria-label={label}
        value={text}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setText(value)
            setEditing(false)
          }
        }}
        className={cx('w-full rounded-md border border-accent bg-bg px-1.5 outline-none focus:ring-2 focus:ring-accent/25', inputClassName)}
      />
    )
  }
  return (
    <button
      type="button"
      title={label}
      onClick={() => setEditing(true)}
      className={cx('-mx-1.5 max-w-full truncate rounded-md px-1.5 text-left transition-colors hover:bg-raised', !value && 'text-faint italic', className)}
    >
      {value || placeholder}
    </button>
  )
}

/** Tag chips with an input that adds on Enter/comma and suggests existing tags. */
export function TagEditor({
  tags,
  suggestions,
  placeholder,
  onChange,
}: {
  tags: string[]
  suggestions: string[]
  placeholder: string
  onChange: (tags: string[]) => void
}) {
  const [text, setText] = useState('')
  const listId = useId()
  const add = (raw: string) => {
    const t = raw.trim().slice(0, 40)
    setText('')
    if (!t || tags.some((x) => x.toLowerCase() === t.toLowerCase())) return
    onChange([...tags, t])
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      add(text)
    } else if (e.key === 'Backspace' && !text && tags.length) {
      onChange(tags.slice(0, -1))
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((t) => (
        <span key={t} className="inline-flex h-6 items-center gap-1 rounded-full border border-line-strong bg-raised pr-1 pl-2.5 text-xs">
          {t}
          <button type="button" className="rounded-full p-0.5 text-faint hover:bg-line-strong hover:text-fg" onClick={() => onChange(tags.filter((x) => x !== t))} aria-label={`× ${t}`}>
            <XIcon size={10} />
          </button>
        </span>
      ))}
      <input
        list={listId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        onBlur={() => text.trim() && add(text)}
        placeholder={placeholder}
        maxLength={40}
        className="h-6 w-28 rounded-full border border-dashed border-line-strong bg-transparent px-2.5 text-xs outline-none placeholder:text-faint focus:w-40 focus:border-accent"
      />
      <datalist id={listId}>
        {suggestions
          .filter((s) => !tags.includes(s))
          .map((s) => (
            <option key={s} value={s} />
          ))}
      </datalist>
    </div>
  )
}
