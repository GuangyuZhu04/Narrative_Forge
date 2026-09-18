import { useEffect, useSyncExternalStore } from 'react'
import { chapterApi } from '@/services/api'
import { paintHighlight, readLocal, rebaseHighlights, resolveHighlights, writeLocal, type HighlightColor, type TextHighlight } from './highlights'

interface Snapshot { marks: TextHighlight[]; ready: boolean; saving: boolean; error: string }
interface Entry { snapshot: Snapshot; listeners: Set<() => void>; loading: boolean; revision: number; queue: Promise<unknown> }
const entries = new Map<string, Entry>()
const draftKey = (key: string) => `nforge:highlight-draft:${key}`
function getEntry(key: string): Entry {
  let entry = entries.get(key)
  if (!entry) {
    entry = { snapshot: { marks: [], ready: false, saving: false, error: '' }, listeners: new Set(), loading: false, revision: 0, queue: Promise.resolve() }
    entries.set(key, entry)
  }
  return entry
}
function publish(entry: Entry, patch: Partial<Snapshot>) {
  entry.snapshot = { ...entry.snapshot, ...patch }
  entry.listeners.forEach((listener) => listener())
}
function persist(projectId: string, chapterId: string, marks: TextHighlight[]) {
  const key = `${projectId}:${chapterId}`
  const entry = getEntry(key)
  const revision = ++entry.revision
  const backedUp = writeLocal(draftKey(key), marks)
  publish(entry, { marks, saving: true, error: backedUp ? '' : '本机标注备份空间不足，正在保存到章节。' })
  entry.queue = entry.queue.catch(() => {}).then(async () => {
    if (entry.revision !== revision) return
    try {
      await chapterApi.update(projectId, chapterId, { highlights: marks })
      if (entry.revision === revision) {
        try { localStorage.removeItem(draftKey(key)) } catch { /* Database save succeeded. */ }
        publish(entry, { saving: false, error: '' })
      }
    } catch {
      if (entry.revision === revision) publish(entry, { saving: false, error: backedUp ? '高亮保存失败，已保留本机草稿。' : '高亮尚未保存，请重试。' })
    }
  })
}

async function load(projectId: string, chapterId: string) {
  if (!projectId || !chapterId) return
  const key = `${projectId}:${chapterId}`
  const entry = getEntry(key)
  if (entry.loading || entry.snapshot.ready) return
  entry.loading = true
  try {
    const chapter = await chapterApi.get(projectId, chapterId) as unknown as { highlights?: TextHighlight[] }
    const draft = readLocal<TextHighlight[] | null>(draftKey(key), null)
    const marks = Array.isArray(draft) ? draft : chapter.highlights || []
    publish(entry, { marks, ready: true, error: '' })
    if (draft) persist(projectId, chapterId, marks)
  } catch { publish(entry, { error: '高亮加载失败，请重试。' }) }
  finally { entry.loading = false }
}

export function useHighlights(projectId: string, chapterId: string, text: string) {
  const key = `${projectId}:${chapterId}`
  const entry = getEntry(key)
  const snapshot = useSyncExternalStore(
    (listener) => { entry.listeners.add(listener); return () => entry.listeners.delete(listener) },
    () => entry.snapshot,
  )
  useEffect(() => { void load(projectId, chapterId) }, [projectId, chapterId])
  return {
    ...snapshot,
    marks: resolveHighlights(text, snapshot.marks),
    paint: (start: number, end: number, color: HighlightColor | null) => {
      if (snapshot.ready) persist(projectId, chapterId, paintHighlight(text, entry.snapshot.marks, start, end, color))
    },
    rebase: (next: string) => {
      if (snapshot.ready && entry.snapshot.marks.length && text !== next) persist(projectId, chapterId, rebaseHighlights(text, next, entry.snapshot.marks))
    },
    retry: () => snapshot.ready ? persist(projectId, chapterId, entry.snapshot.marks) : void load(projectId, chapterId),
  }
}
