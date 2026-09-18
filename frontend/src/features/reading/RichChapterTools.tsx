import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Editor } from '@tiptap/react'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { HIGHLIGHT_COLORS } from './highlights'
import { useHighlights } from './useHighlights'
import { HighlightToolbar } from './HighlightToolbar'
import { ReaderLauncher } from './ReaderLauncher'

function inspectEditor(editor: Editor) {
  let text = ''
  let firstBlock = true
  const spans: { offset: number; position: number; length: number }[] = []
  editor.state.doc.descendants((node, position) => {
    if (node.isTextblock) { if (!firstBlock) text += '\n\n'; firstBlock = false }
    if (node.isText || node.type.name === 'hardBreak') {
      const value = node.text || '\n'
      spans.push({ offset: text.length, position, length: value.length })
      text += value
    }
  })
  const offsetAt = (position: number) => {
    const span = spans.find((item) => position <= item.position + item.length)
    return span ? span.offset + Math.max(0, position - span.position) : text.length
  }
  return { text, spans, start: offsetAt(editor.state.selection.from), end: offsetAt(editor.state.selection.to) }
}

export function RichChapterTools({ editor, projectId, chapterId, ready }: { editor: Editor | null; projectId: string; chapterId: string; ready: boolean }) {
  const [revision, setRevision] = useState(0)
  const snapshot = editor ? inspectEditor(editor) : { text: '', spans: [], start: 0, end: 0 }
  const annotations = useHighlights(projectId, chapterId, snapshot.text)
  const latest = useRef({ annotations, snapshot })
  useLayoutEffect(() => { latest.current = { annotations, snapshot } })
  useEffect(() => {
    if (!editor) return
    const changed = () => {
      const next = inspectEditor(editor)
      latest.current.annotations.rebase(next.text)
      setRevision((value) => value + 1)
    }
    const selected = () => setRevision((value) => value + 1)
    editor.on('update', changed)
    editor.on('selectionUpdate', selected)
    // Loading a chapter uses emitUpdate: false, so observe every transaction.
    editor.on('transaction', selected)
    return () => { editor.off('update', changed); editor.off('selectionUpdate', selected); editor.off('transaction', selected) }
  }, [editor])
  const pluginKey = useRef(new PluginKey('chapter-highlights'))
  useEffect(() => {
    if (!editor) return
    const key = pluginKey.current
    const plugin = new Plugin({
      key,
      props: { decorations(state) {
        const { annotations: current } = latest.current
        const { spans } = inspectEditor(editor)
        const decorations = current.marks.flatMap((mark) => spans.flatMap((span) => {
          const start = Math.max(mark.start, span.offset)
          const end = Math.min(mark.end, span.offset + span.length)
          return end > start ? [Decoration.inline(span.position + start - span.offset, span.position + end - span.offset, {
            class: 'manuscript-highlight', 'data-highlight-id': mark.id, style: `background-color: ${HIGHLIGHT_COLORS[mark.color].value}`,
          })] : []
        }))
        return DecorationSet.create(state.doc, decorations)
      } },
    })
    editor.registerPlugin(plugin)
    return () => { if (!editor.isDestroyed) editor.unregisterPlugin(key) }
  }, [editor])
  const marksKey = JSON.stringify(annotations.marks)
  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.view.updateState(editor.state)
  }, [editor, marksKey, revision])
  return <div>
    <HighlightToolbar {...annotations} ready={ready && annotations.ready} hasSelection={snapshot.end > snapshot.start} onRetry={annotations.retry}
      onPaint={(color) => { annotations.paint(snapshot.start, snapshot.end, color); editor?.commands.focus() }} />
    <div className="px-4 py-2"><ReaderLauncher projectId={projectId} chapterId={chapterId} content={snapshot.text} disabled={!editor || !ready} /></div>
  </div>
}
