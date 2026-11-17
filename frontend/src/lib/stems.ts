import type { StemMode, StemName } from '../api/types'

/** Display order (§2). */
export const STEM_ORDER: readonly StemName[] = ['vocals', 'instrumental', 'drums', 'bass', 'guitar', 'piano', 'other']

export const STEMS_BY_MODE: Record<StemMode, readonly StemName[]> = {
  2: ['vocals', 'instrumental'],
  4: ['vocals', 'drums', 'bass', 'other'],
  6: ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'],
}

/** Fixed stem colors (§5.2). */
export const STEM_COLORS: Record<StemName, string> = {
  vocals: '#F472B6',
  instrumental: '#A78BFA',
  drums: '#F59E0B',
  bass: '#22D3EE',
  guitar: '#F97316',
  piano: '#34D399',
  other: '#94A3B8',
}

export const STEM_MODES: readonly StemMode[] = [2, 4, 6]
