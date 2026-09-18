import { Fragment, type ReactNode } from 'react'
import { HIGHLIGHT_COLORS, type TextHighlight } from './highlights'

export function HighlightedText({ text, marks }: { text: string; marks: TextHighlight[] }) {
  let offset = 0
  const parts: ReactNode[] = []
  for (const mark of marks) {
    const start = Math.max(offset, mark.start)
    if (start >= mark.end) continue
    const before = text.slice(offset, start)
    offset = mark.end
    parts.push(<Fragment key={mark.id}>{before}<mark data-highlight-id={mark.id} style={{ backgroundColor: HIGHLIGHT_COLORS[mark.color].value }}>{text.slice(start, mark.end)}</mark></Fragment>)
  }
  return <>{parts}{text.slice(offset)}</>
}
