import { useEffect, useRef, useState } from 'react'
import { useHighlights } from './useHighlights'
import { HighlightToolbar } from './HighlightToolbar'
import { HighlightedText } from './HighlightedText'
import type { HighlightColor } from './highlights'

interface Props { projectId: string; chapterId: string; value: string; onChange: (value: string) => void }
export function HighlightedTextarea({ projectId, chapterId, value, onChange }: Props) {
  const annotations = useHighlights(projectId, chapterId, value)
  const input = useRef<HTMLTextAreaElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  const [selection, setSelection] = useState({ start: 0, end: 0 })
  useEffect(() => {
    const element = input.current
    if (!element) return
    const changed = () => {
      if (document.activeElement === element) setSelection({ start: element.selectionStart, end: element.selectionEnd })
    }
    element.addEventListener('select', changed)
    element.addEventListener('selectionchange', changed)
    document.addEventListener('selectionchange', changed)
    return () => {
      element.removeEventListener('select', changed)
      element.removeEventListener('selectionchange', changed)
      document.removeEventListener('selectionchange', changed)
    }
  }, [])
  const select = () => {
    if (input.current) setSelection({ start: input.current.selectionStart, end: input.current.selectionEnd })
  }
  const paint = (color: HighlightColor | null) => {
    annotations.paint(selection.start, selection.end, color)
    input.current?.focus({ preventScroll: true })
    input.current?.setSelectionRange(selection.start, selection.end)
  }
  return <div className="highlight-editor">
    <HighlightToolbar {...annotations} hasSelection={selection.end > selection.start} onPaint={paint} onRetry={annotations.retry} />
    <div className="highlight-input-wrap">
      <div ref={backdrop} className="highlight-backdrop" aria-hidden="true"><HighlightedText text={value} marks={annotations.marks} />{'\n'}</div>
      <textarea ref={input} className="highlight-input" aria-label="章节正文" spellCheck={false}
        value={value} placeholder="点击「AI 编写」生成章节内容，或直接在此输入…"
        onSelect={select} onKeyUp={select} onPointerUp={select}
        onChange={(event) => { annotations.rebase(event.target.value); onChange(event.target.value); select() }}
        onScroll={() => { if (backdrop.current && input.current) { backdrop.current.scrollTop = input.current.scrollTop; backdrop.current.scrollLeft = input.current.scrollLeft } }} />
    </div>
  </div>
}
