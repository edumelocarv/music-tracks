import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Language } from '../api/types'
import { useSettings } from '../api/queries'
import en, { type Messages } from './en'
import ptBR from './pt-BR'

export const dictionaries: Record<Language, Messages> = { en, 'pt-BR': ptBR }

/** Replaces `{name}` placeholders. */
export function fmt(template: string, vars: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m))
}

export function detectLanguage(navLang: string | undefined): Language {
  return navLang?.toLowerCase().startsWith('pt') ? 'pt-BR' : 'en'
}

interface I18nCtx {
  lang: Language
  m: Messages
  /** Applies a language locally (persisting is the caller's job); null = saved/automatic. */
  setLang: (l: Language | null) => void
}

const Ctx = createContext<I18nCtx | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const settings = useSettings()
  const [override, setOverride] = useState<Language | null>(null)
  const saved = settings.data?.language ?? null
  const lang: Language = override ?? saved ?? detectLanguage(typeof navigator !== 'undefined' ? navigator.language : undefined)

  // When settings change (e.g. saved elsewhere), drop the local override.
  useEffect(() => {
    setOverride(null)
  }, [saved])

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((l: Language | null) => setOverride(l), [])
  const value = useMemo(() => ({ lang, m: dictionaries[lang], setLang }), [lang, setLang])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useI18n(): I18nCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useI18n outside I18nProvider')
  return v
}

/** The messages dictionary of the current language. */
export function useT(): Messages {
  return useI18n().m
}

/** Translates an API error code (`errors.<CODE>`). */
export function errorText(m: Messages, code: string | null | undefined): string {
  if (!code) return m.errors.UNKNOWN.replace('{code}', '?')
  const table = m.errors as Record<string, string>
  return table[code] ?? fmt(m.errors.UNKNOWN, { code })
}
