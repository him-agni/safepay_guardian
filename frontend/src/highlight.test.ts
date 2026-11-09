import { describe, expect, it } from 'vitest'
import { segment } from './highlight'

const join = (segs: ReturnType<typeof segment>) => segs.map((s) => s.text).join('')

describe('segment', () => {
  it('returns the whole text unmarked when there are no spans', () => {
    expect(segment('hello there', [])).toEqual([{ text: 'hello there', start: 0, marked: false, types: [] }])
  })

  it('marks exactly the span offsets', () => {
    const text = 'Pay in gift cards within 30 minutes'
    const segs = segment(text, [{ start: 7, end: 17, type: 'gift_card' }])
    expect(segs.map((s) => [s.text, s.marked])).toEqual([
      ['Pay in ', false],
      ['gift cards', true],
      [' within 30 minutes', false],
    ])
    expect(join(segs)).toBe(text)
  })

  it('handles overlapping spans without losing or duplicating text', () => {
    const text = 'send now ASAP please'
    const segs = segment(text, [
      { start: 0, end: 13, type: 'urgency' },
      { start: 5, end: 20, type: 'other' },
    ])
    expect(join(segs)).toBe(text)
    expect(segs.map((s) => [s.text, s.types.join('+')])).toEqual([
      ['send ', 'urgency'],
      ['now ASAP', 'other+urgency'],
      [' please', 'other'],
    ])
  })

  it('merges duplicate and adjacent spans of the same type', () => {
    const segs = segment('abcdef', [
      { start: 0, end: 3, type: 'x' },
      { start: 0, end: 3, type: 'x' },
      { start: 3, end: 6, type: 'x' },
    ])
    expect(segs).toEqual([{ text: 'abcdef', start: 0, marked: true, types: ['x'] }])
  })

  it('ignores empty and out-of-range spans', () => {
    const text = 'short'
    const segs = segment(text, [
      { start: 3, end: 3, type: 'empty' },
      { start: 2, end: 99, type: 'clipped' },
      { start: 50, end: 60, type: 'outside' },
    ])
    expect(join(segs)).toBe(text)
    expect(segs.map((s) => [s.text, s.marked])).toEqual([
      ['sh', false],
      ['ort', true],
    ])
  })

  it('returns nothing for empty text', () => {
    expect(segment('', [{ start: 0, end: 2, type: 'x' }])).toEqual([])
  })
})
