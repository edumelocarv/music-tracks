import type { Language } from '../api/types'

/** Pitch classes, sharps only (§5.3). */
export const NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'] as const

const LETTER_PC: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }

const SOLFEGE: Record<string, string> = { C: 'Dó', D: 'Ré', E: 'Mi', F: 'Fá', G: 'Sol', A: 'Lá', B: 'Si' }

const mod12 = (n: number) => ((n % 12) + 12) % 12

/** Parses a note name at the start of `s` (e.g. `F#`, `Bb`, `C`). Returns pitch class and length consumed. */
export function parseNote(s: string): { pc: number; len: number } | null {
  const letter = s.charAt(0).toUpperCase()
  if (!(letter in LETTER_PC)) return null
  let pc = LETTER_PC[letter]
  let len = 1
  while (len < s.length) {
    const c = s.charAt(len)
    if (c === '#' || c === '♯') pc += 1
    else if (c === 'b' || c === '♭') pc -= 1
    else break
    len++
  }
  return { pc: mod12(pc), len }
}

export function transposeNote(note: string, semitones: number): string {
  const p = parseNote(note)
  if (!p || p.len !== note.length) return note
  return NOTES[mod12(p.pc + semitones)]
}

const isNoChord = (label: string) => {
  const l = label.trim()
  return l === '' || l === 'N' || l === 'N.C.' || l === 'X'
}

/** Transposes a chord label (`Am` +2 → `Bm`, `F#m7`, slash chords `C/G`). `N` stays `N`. Output uses sharps. */
export function transposeChord(label: string, semitones: number): string {
  if (isNoChord(label)) return label
  const [main, bass] = label.split('/', 2)
  const root = parseNote(main)
  if (!root) return label
  let out = NOTES[mod12(root.pc + semitones)] + main.slice(root.len)
  if (bass !== undefined) {
    const b = parseNote(bass)
    out += '/' + (b ? NOTES[mod12(b.pc + semitones)] + bass.slice(b.len) : bass)
  }
  return out
}

/** Chord shown to the user: transposed, `N` as "—". */
export function displayChord(label: string, semitones = 0): string {
  if (isNoChord(label)) return '—'
  return transposeChord(label, semitones)
}

/** Parses `"A minor"` / `"F# major"`. */
export function parseKey(label: string): { pc: number; scale: string } | null {
  const parts = label.trim().split(/\s+/)
  if (parts.length < 2) return null
  const p = parseNote(parts[0])
  if (!p || p.len !== parts[0].length) return null
  return { pc: p.pc, scale: parts.slice(1).join(' ').toLowerCase() }
}

/** `A minor` −3 → `F# minor` (always sharps). Unparseable labels are returned unchanged. */
export function transposeKey(label: string, semitones: number): string {
  const k = parseKey(label)
  if (!k) return label
  return `${NOTES[mod12(k.pc + semitones)]} ${k.scale}`
}

/** Key label for display: en → `A minor`; pt-BR → `Lá menor`, `Fá# maior`. */
export function displayKey(label: string, lang: Language, semitones = 0): string {
  const k = parseKey(label)
  if (!k) return label
  const note = NOTES[mod12(k.pc + semitones)]
  if (lang === 'en') return `${note} ${k.scale}`
  const solfege = SOLFEGE[note.charAt(0)] + note.slice(1)
  const scale = k.scale === 'major' ? 'maior' : k.scale === 'minor' ? 'menor' : k.scale
  return `${solfege} ${scale}`
}
