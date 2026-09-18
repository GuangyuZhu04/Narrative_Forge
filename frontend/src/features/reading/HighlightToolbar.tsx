import { Highlighter, Eraser } from 'lucide-react'
import { HIGHLIGHT_COLORS, type HighlightColor } from './highlights'
import './reading.css'

interface Props {
  hasSelection: boolean
  ready: boolean
  saving: boolean
  error: string
  onPaint: (color: HighlightColor | null) => void
  onRetry: () => void
}
export function HighlightToolbar({ hasSelection, ready, saving, error, onPaint, onRetry }: Props) {
  return <div className="highlight-toolbar" role="group" aria-label="文字高亮">
    <Highlighter size={17} aria-hidden="true" />
    <span>高亮</span>
    {Object.entries(HIGHLIGHT_COLORS).map(([color, option]) => <button
      key={color} type="button" aria-label={option.label} title={option.label}
      disabled={!hasSelection || !ready} onMouseDown={(event) => event.preventDefault()}
      onClick={() => onPaint(color as HighlightColor)}>
      <span className="highlight-swatch" style={{ background: option.value }} />
    </button>)}
    <button type="button" aria-label="清除所选高亮" title="清除所选高亮" disabled={!hasSelection || !ready}
      onMouseDown={(event) => event.preventDefault()} onClick={() => onPaint(null)}><Eraser size={17} /></button>
    <span className="highlight-hint" role="status">{saving ? '高亮保存中…' : !ready && !error ? '正在加载高亮…' : hasSelection ? '选择颜色，或清除高亮' : '选中文字后高亮'}</span>
    {error && <span className="highlight-error" role="alert">{error}<button type="button" onClick={onRetry}>重试</button></span>}
  </div>
}
