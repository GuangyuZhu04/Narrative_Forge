export const HIGHLIGHT_COLORS = {
  yellow: { label: '黄色高亮', value: '#fde68a' },
  green: { label: '绿色高亮', value: '#bbf7d0' },
  blue: { label: '蓝色高亮', value: '#bae6fd' },
  pink: { label: '粉色高亮', value: '#fbcfe8' },
} as const

export type HighlightColor = keyof typeof HIGHLIGHT_COLORS
export interface TextHighlight {
  id: string
  start: number
  end: number
  text: string
  prefix: string
  suffix: string
  color: HighlightColor
}

export function anchorHighlight(text: string, start: number, end: number, color: HighlightColor, id: string = crypto.randomUUID()): TextHighlight {
  return { id, start, end, color, text: text.slice(start, end), prefix: Array.from(text.slice(0, start)).slice(-24).join(''), suffix: Array.from(text.slice(end)).slice(0, 24).join('') }
}

// Quotes and surrounding context also allow marks to survive switching between
// the legacy HTML editor and the plain-text manuscript, or external rewrites.
export function resolveHighlights(text: string, highlights: TextHighlight[]): TextHighlight[] {
  return highlights.flatMap((mark) => {
    if (!mark.text || !(mark.color in HIGHLIGHT_COLORS)) return []
    if (text.slice(mark.start, mark.end) === mark.text &&
        (!mark.prefix || text.slice(Math.max(0, mark.start - mark.prefix.length), mark.start) === mark.prefix) &&
        (!mark.suffix || text.slice(mark.end, mark.end + mark.suffix.length) === mark.suffix)) return [mark]
    let at = text.indexOf(mark.text)
    let best = -1
    let score = -Infinity
    while (at !== -1) {
      const before = text.slice(Math.max(0, at - mark.prefix.length), at)
      const after = text.slice(at + mark.text.length, at + mark.text.length + mark.suffix.length)
      const candidate = (mark.prefix && before === mark.prefix ? 1000000 : 0) +
        (mark.suffix && after === mark.suffix ? 1000000 : 0) - Math.abs(at - mark.start)
      if (candidate > score) { best = at; score = candidate }
      at = text.indexOf(mark.text, at + 1)
    }
    return best === -1 ? [] : [anchorHighlight(text, best, best + mark.text.length, mark.color, mark.id)]
  }).sort((a, b) => a.start - b.start || a.end - b.end)
}

export function paintHighlight(text: string, marks: TextHighlight[], start: number, end: number, color: HighlightColor | null): TextHighlight[] {
  start = Math.max(0, Math.min(start, text.length))
  end = Math.max(start, Math.min(end, text.length))
  if (start === end) return marks
  const next = resolveHighlights(text, marks).flatMap((mark) => {
    if (mark.end <= start || mark.start >= end) return [mark]
    const parts: TextHighlight[] = []
    if (mark.start < start) parts.push(anchorHighlight(text, mark.start, start, mark.color, mark.id))
    if (mark.end > end) parts.push(anchorHighlight(text, end, mark.end, mark.color))
    return parts
  })
  if (color) next.push(anchorHighlight(text, start, end, color))
  return next.sort((a, b) => a.start - b.start)
}

// Map a contiguous typing/paste/delete operation without searching for repeated
// quotes. Text inserted inside a mark inherits its color; deleted marks vanish.
export function rebaseHighlights(before: string, after: string, marks: TextHighlight[]): TextHighlight[] {
  if (before === after) return marks
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start++
  let oldEnd = before.length
  let newEnd = after.length
  while (oldEnd > start && newEnd > start && before[oldEnd - 1] === after[newEnd - 1]) { oldEnd--; newEnd-- }
  const delta = newEnd - oldEnd
  return resolveHighlights(before, marks).flatMap((mark) => {
    let from = mark.start
    let to = mark.end
    if (from >= oldEnd) { from += delta; to += delta }
    else if (to > start) { from = Math.min(from, start); to = to >= oldEnd ? to + delta : newEnd }
    return to > from ? [anchorHighlight(after, from, to, mark.color, mark.id)] : []
  })
}

export function readLocal<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback } catch { return fallback }
}

export function writeLocal(key: string, value: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); return true } catch { return false }
}

export function contentToReadingText(content: string): string {
  if (!/^\s*<(?:p|div|h[1-6]|blockquote|ul|ol|pre)(?:\s|>)/i.test(content)) return content
  const doc = new DOMParser().parseFromString(content, 'text/html')
  doc.querySelectorAll('script,style,iframe,object,template').forEach((node) => node.remove())
  doc.querySelectorAll('br').forEach((node) => node.replaceWith('\n'))
  doc.querySelectorAll('p,div,h1,h2,h3,h4,h5,h6,li,blockquote,pre').forEach((node) => node.append('\n\n'))
  return (doc.body.textContent || '').replace(/\n{3,}/g, '\n\n').replace(/\n+$/, '')
}
