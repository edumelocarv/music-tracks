import type { StemMode } from '../api/types'
import { useT } from '../i18n'
import { STEM_COLORS, STEM_MODES, STEMS_BY_MODE } from '../lib/stems'
import { AlertIcon } from './icons'
import { cx } from './ui'

/** Radio-card selector for 2/4/6 stems with the §7.3 quality warning for 6. */
export function StemModeSelect({ value, onChange }: { value: StemMode; onChange: (v: StemMode) => void }) {
  const m = useT()
  const labels: Record<StemMode, string> = { 2: m.stemMode.option2, 4: m.stemMode.option4, 6: m.stemMode.option6 }
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium tracking-wide text-muted uppercase">{m.stemMode.label}</div>
      <div className="grid grid-cols-3 gap-2" role="radiogroup">
        {STEM_MODES.map((mode) => {
          const [title, rest] = labels[mode].split(' — ')
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={value === mode}
              onClick={() => onChange(mode)}
              className={cx(
                'rounded-lg border px-3 py-2.5 text-left transition-colors',
                value === mode ? 'border-accent bg-accent/10' : 'border-line-strong bg-bg hover:border-[#4a505a]',
              )}
            >
              <div className="text-[13px] font-semibold">{title}</div>
              <div className="mt-0.5 text-[11px] leading-snug text-muted">{rest}</div>
              <div className="mt-2 flex gap-1">
                {STEMS_BY_MODE[mode].map((s) => (
                  <span key={s} className="h-1.5 flex-1 rounded-full" style={{ background: STEM_COLORS[s] }} />
                ))}
              </div>
            </button>
          )
        })}
      </div>
      {value === 6 && (
        <div className="flex items-start gap-2 rounded-md border border-warn/25 bg-warn/10 px-3 py-2 text-xs text-warn">
          <AlertIcon size={14} className="mt-px shrink-0" />
          {m.stemMode.warning6}
        </div>
      )}
    </div>
  )
}
