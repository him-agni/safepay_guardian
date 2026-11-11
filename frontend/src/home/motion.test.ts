import { describe, expect, it } from 'vitest'
import { clamp, countAt, easeOutCubic, lookFromPointer, nextStage, typedCount } from './motion'

const box = { left: 100, top: 50, width: 400, height: 200 }

describe('lookFromPointer', () => {
  it('is 0,0 at the middle of the box', () => {
    expect(lookFromPointer(300, 150, box)).toEqual({ x: 0, y: 0 })
  })

  it('is -1 at the top left corner and 1 at the bottom right', () => {
    expect(lookFromPointer(100, 50, box)).toEqual({ x: -1, y: -1 })
    expect(lookFromPointer(500, 250, box)).toEqual({ x: 1, y: 1 })
  })

  it('stays within -1..1 when the pointer is far outside the box', () => {
    expect(lookFromPointer(-5000, 9000, box)).toEqual({ x: -1, y: 1 })
  })

  it('does not divide by zero for an empty box', () => {
    expect(lookFromPointer(10, 10, { left: 0, top: 0, width: 0, height: 0 })).toEqual({ x: 0, y: 0 })
  })
})

describe('count up', () => {
  it('starts at 0 and ends exactly on the target', () => {
    expect(countAt(46, 0)).toBe(0)
    expect(countAt(46, 1)).toBe(46)
  })

  it('never overshoots, even if the clock runs past the end', () => {
    expect(countAt(46, 1.7)).toBe(46)
    expect(countAt(46, -3)).toBe(0)
  })

  it('rises steadily and fastest at the start', () => {
    expect(easeOutCubic(0.25)).toBeGreaterThan(0.25)
    expect(countAt(100, 0.5)).toBeGreaterThan(countAt(100, 0.25))
  })
})

describe('story stages', () => {
  it('loops back to the first stage after the last', () => {
    expect(nextStage(0, 4)).toBe(1)
    expect(nextStage(3, 4)).toBe(0)
  })

  it('copes with an empty story', () => {
    expect(nextStage(0, 0)).toBe(0)
  })
})

describe('typedCount', () => {
  it('reveals one character per interval and stops at the end of the line', () => {
    expect(typedCount(10, 0, 25)).toBe(0)
    expect(typedCount(10, 100, 25)).toBe(4)
    expect(typedCount(10, 9999, 25)).toBe(10)
  })

  it('shows everything at once when the interval is 0', () => {
    expect(typedCount(10, 0, 0)).toBe(10)
  })
})

describe('clamp', () => {
  it('limits a number to the range', () => {
    expect(clamp(5, 0, 3)).toBe(3)
    expect(clamp(-5, 0, 3)).toBe(0)
    expect(clamp(2, 0, 3)).toBe(2)
  })
})
