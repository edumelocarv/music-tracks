import { describe, expect, it } from 'vitest'
import { ERROR_CODES } from '../api/types'
import en from './en'
import ptBR from './pt-BR'

function keys(obj: unknown, prefix = ''): string[] {
  if (!obj || typeof obj !== 'object') return [prefix]
  return Object.entries(obj as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k))
}

function placeholders(obj: unknown, prefix = ''): Record<string, string> {
  if (typeof obj === 'string') return { [prefix]: (obj.match(/\{\w+\}/g) ?? []).sort().join(',') }
  return Object.assign({}, ...Object.entries(obj as Record<string, unknown>).map(([k, v]) => placeholders(v, prefix ? `${prefix}.${k}` : k)))
}

describe('i18n', () => {
  it('en and pt-BR have exactly the same keys', () => {
    expect(keys(ptBR).sort()).toEqual(keys(en).sort())
  })
  it('every string is non-empty', () => {
    for (const dict of [en, ptBR]) {
      for (const k of keys(dict)) {
        const v = k.split('.').reduce<unknown>((o, p) => (o as Record<string, unknown>)[p], dict)
        expect(typeof v === 'string' && v.length > 0, k).toBe(true)
      }
    }
  })
  it('placeholders match between languages', () => {
    expect(placeholders(ptBR)).toEqual(placeholders(en))
  })
  it('every API error code is translated', () => {
    for (const code of ERROR_CODES) {
      expect(en.errors[code], code).toBeTruthy()
      expect(ptBR.errors[code], code).toBeTruthy()
    }
  })
})
