// Splits a text into plain and highlighted segments from the backend's evidence offsets.
// The backend already verified every span against the original text (evidence grounding);
// this only has to be robust to overlaps, duplicates and out-of-range offsets.

export interface SpanLike {
  start: number
  end: number
  type: string
}

export interface Segment {
  text: string
  start: number
  marked: boolean
  types: string[]
}

export function segment(text: string, spans: SpanLike[]): Segment[] {
  if (!text) return []
  const valid = spans
    .map((s) => ({ ...s, start: Math.max(0, s.start), end: Math.min(text.length, s.end) }))
    .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)

  const cuts = new Set<number>([0, text.length])
  for (const s of valid) {
    cuts.add(s.start)
    cuts.add(s.end)
  }
  const points = [...cuts].sort((a, b) => a - b)

  const out: Segment[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    const types = [...new Set(valid.filter((s) => s.start <= a && s.end >= b).map((s) => s.type))].sort()
    const prev = out[out.length - 1]
    if (prev && prev.marked === types.length > 0 && prev.types.join() === types.join()) {
      prev.text += text.slice(a, b)
    } else {
      out.push({ text: text.slice(a, b), start: a, marked: types.length > 0, types })
    }
  }
  return out
}
