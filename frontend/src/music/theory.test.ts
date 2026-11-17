import { describe, expect, it } from 'vitest'
import { displayChord, displayKey, transposeChord, transposeKey } from './theory'

describe('chord transposition', () => {
  it('Am +2 → Bm', () => expect(transposeChord('Am', 2)).toBe('Bm'))
  it('B +1 → C', () => expect(transposeChord('B', 1)).toBe('C'))
  it('keeps the quality and uses sharps', () => {
    expect(transposeChord('F#m7', 1)).toBe('Gm7')
    expect(transposeChord('Cmaj7', 1)).toBe('C#maj7')
    expect(transposeChord('Bb', 0)).toBe('A#')
    expect(transposeChord('C', -1)).toBe('B')
    expect(transposeChord('C/G', 2)).toBe('D/A')
  })
  it('N is shown as —', () => {
    expect(transposeChord('N', 3)).toBe('N')
    expect(displayChord('N', 3)).toBe('—')
    expect(displayChord('Am', 2)).toBe('Bm')
  })
})

describe('key transposition and display', () => {
  it('A minor −3 → F# minor', () => expect(transposeKey('A minor', -3)).toBe('F# minor'))
  it('A minor +2 → B minor', () => expect(transposeKey('A minor', 2)).toBe('B minor'))
  it('wraps around the octave', () => expect(transposeKey('B major', 1)).toBe('C major'))
  it('en uses letters', () => {
    expect(displayKey('A minor', 'en')).toBe('A minor')
    expect(displayKey('F# major', 'en')).toBe('F# major')
  })
  it('pt-BR uses solfège', () => {
    expect(displayKey('A minor', 'pt-BR')).toBe('Lá menor')
    expect(displayKey('F# major', 'pt-BR')).toBe('Fá# maior')
    expect(displayKey('C major', 'pt-BR', -1)).toBe('Si maior')
    expect(displayKey('A minor', 'pt-BR', -3)).toBe('Fá# menor')
  })
})
