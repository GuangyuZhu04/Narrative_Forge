import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ArrowLeft, ArrowRight, Bookmark, Check, List, Maximize2, Minimize2, Settings2, Trash2, X } from 'lucide-react'
import { chapterApi, projectApi } from '@/services/api'
import { contentToReadingText, writeLocal } from './highlights'
import { useHighlights } from './useHighlights'
import { HighlightedText } from './HighlightedText'
import { HighlightToolbar } from './HighlightToolbar'
import { clamp, historyKey, loadReadingHistory, loadReadingSettings, type ReadingSettings } from './readerState'
import './reading.css'

interface ReaderChapter { id: string; title: string; content: string | null; sort_order: number }
interface Props { projectId: string; initialChapterId?: string; draftContent?: string; onClose: () => void }
const themeNames = { paper: '纸张', white: '日间', green: '护眼', night: '夜间' } as const

export function ReadingMode({ projectId, initialChapterId, draftContent, onClose }: Props) {
  const [chapters, setChapters] = useState<ReaderChapter[]>([])
  const [title, setTitle] = useState('阅读模式')
  const [chapterId, setChapterId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [settings, setSettings] = useState(loadReadingSettings)
  const [history, setHistory] = useState(() => loadReadingHistory(projectId))
  const historyRef = useRef(history)
  const [panel, setPanel] = useState<'directory' | 'settings' | 'bookmarks' | null>(null)
  const [query, setQuery] = useState('')
  const [immersive, setImmersive] = useState(false)
  const [progress, setProgress] = useState(0)
  const [storageError, setStorageError] = useState(false)
  const [selection, setSelection] = useState({ start: 0, end: 0 })
  const dialog = useRef<HTMLDialogElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const jumpProgress = useRef<number | null>(null)
  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const index = chapters.findIndex((chapter) => chapter.id === chapterId)
  const chapter = chapters[index]
  const text = contentToReadingText(chapterId === initialChapterId && draftContent !== undefined ? draftContent : chapter?.content || '')
  const annotations = useHighlights(projectId, chapterId, text)
  const saveHistory = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = null
    setStorageError(!writeLocal(historyKey(projectId), historyRef.current))
  }, [projectId])

  useEffect(() => {
    let active = true
    void Promise.all([chapterApi.list(projectId), projectApi.get(projectId)]).then(([response, project]) => {
      if (!active) return
      const data = (response as unknown as { data: ReaderChapter[] }).data || []
      data.sort((a, b) => a.sort_order - b.sort_order)
      setChapters(data)
      setTitle((project as unknown as { name: string }).name || '阅读模式')
      const saved = historyRef.current.chapterId
      setChapterId([initialChapterId, saved, data[0]?.id].find((id) => data.some((item) => item.id === id)) || '')
    }).catch(() => { if (active) setError('章节加载失败，请重试。') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, initialChapterId, attempt])

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    dialog.current?.showModal()
    const visibility = () => { if (document.visibilityState === 'hidden') saveHistory() }
    window.addEventListener('pagehide', saveHistory)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      saveHistory()
      window.removeEventListener('pagehide', saveHistory)
      document.removeEventListener('visibilitychange', visibility)
      previousFocus?.focus({ preventScroll: true })
    }
  }, [saveHistory])

  useEffect(() => {
    const back = (event: Event) => {
      event.preventDefault()
      event.stopImmediatePropagation()
      if (panel) setPanel(null)
      else onClose()
    }
    window.addEventListener('mobile-back', back, true)
    return () => window.removeEventListener('mobile-back', back, true)
  }, [panel, onClose])

  useEffect(() => {
    const readSelection = () => {
      const selected = window.getSelection()
      if (!body.current || !selected?.rangeCount || selected.isCollapsed) { setSelection({ start: 0, end: 0 }); return }
      const range = selected.getRangeAt(0)
      if (!body.current.contains(range.startContainer) || !body.current.contains(range.endContainer)) return
      const prefix = range.cloneRange()
      prefix.selectNodeContents(body.current)
      prefix.setEnd(range.startContainer, range.startOffset)
      const start = prefix.toString().length
      setSelection({ start, end: start + range.toString().length })
    }
    document.addEventListener('selectionchange', readSelection)
    return () => document.removeEventListener('selectionchange', readSelection)
  }, [])

  useLayoutEffect(() => {
    const element = scroller.current
    if (!element || !chapterId) return
    const ratio = clamp(jumpProgress.current ?? historyRef.current.positions[chapterId] ?? 0, 0, 1)
    jumpProgress.current = null
    element.scrollTop = ratio * Math.max(0, element.scrollHeight - element.clientHeight)
    setProgress(ratio)
    setSelection({ start: 0, end: 0 })
    historyRef.current = { ...historyRef.current, chapterId }
    saveHistory()
  }, [chapterId, text, settings, saveHistory])

  const scrollToProgress = (ratio: number) => {
    const element = scroller.current
    if (element) element.scrollTop = clamp(ratio, 0, 1) * Math.max(0, element.scrollHeight - element.clientHeight)
  }
  const navigateChapter = (id: string, ratio?: number) => {
    saveHistory()
    setPanel(null)
    window.getSelection()?.removeAllRanges()
    if (id === chapterId) { scrollToProgress(ratio ?? 0); return }
    jumpProgress.current = ratio ?? 0
    setChapterId(id)
  }
  const turnPage = (direction: number) => {
    const element = scroller.current
    if (!element) return
    const limit = Math.max(0, element.scrollHeight - element.clientHeight)
    if (direction > 0 && element.scrollTop >= limit - 2 && index < chapters.length - 1) navigateChapter(chapters[index + 1].id)
    else if (direction < 0 && element.scrollTop <= 2 && index > 0) navigateChapter(chapters[index - 1].id, 1)
    else element.scrollBy({ top: direction * element.clientHeight * 0.85, behavior: 'auto' })
  }
  const updateSettings = (patch: Partial<ReadingSettings>) => {
    const next = { ...settings, ...patch }
    setSettings(next)
    setStorageError(!writeLocal('nforge:reading-settings', next))
  }
  const bookmark = history.bookmarks.find((item) => item.chapterId === chapterId && Math.abs(item.progress - progress) < 0.025)
  const toggleBookmark = () => {
    const offset = Math.floor(text.length * progress)
    const bookmarks = bookmark ? historyRef.current.bookmarks.filter((item) => item.id !== bookmark.id) : [...historyRef.current.bookmarks, {
      id: crypto.randomUUID(), chapterId, progress, excerpt: text.slice(offset, offset + 64).trim(), createdAt: Date.now(),
    }]
    historyRef.current = { ...historyRef.current, bookmarks }
    setHistory(historyRef.current)
    saveHistory()
  }
  const removeBookmark = (id: string) => {
    historyRef.current = { ...historyRef.current, bookmarks: historyRef.current.bookmarks.filter((item) => item.id !== id) }
    setHistory(historyRef.current)
    saveHistory()
  }
  const style = { '--reader-font-size': `${settings.fontSize}px`, '--reader-line-height': settings.lineHeight, '--reader-width': `${settings.width}px`, '--reader-font': settings.font === 'serif' ? "'Noto Serif CJK SC', 'Songti SC', SimSun, serif" : "'Microsoft YaHei', 'PingFang SC', sans-serif" } as CSSProperties
  return createPortal(<dialog ref={dialog} className="reading-mode" data-theme={settings.theme} data-immersive={immersive} style={style}
    aria-label="阅读模式" onCancel={(event) => { event.preventDefault(); onClose() }}
    onKeyDown={(event) => {
      if (event.target instanceof HTMLElement && event.target.closest('input,select,textarea,button')) return
      if (panel || selection.end > selection.start) return
      if (['ArrowRight', 'PageDown', ' '].includes(event.key)) { event.preventDefault(); turnPage(1) }
      if (['ArrowLeft', 'PageUp'].includes(event.key)) { event.preventDefault(); turnPage(-1) }
    }}>
    <header className="reader-header">
      <button type="button" onClick={onClose} aria-label="退出阅读模式"><ArrowLeft size={19} /><span>返回编辑</span></button>
      <div className="reader-book-title"><strong>{title}</strong><span>{chapter?.title || '沉浸阅读'}</span></div>
      <button type="button" aria-label="沉浸阅读" onClick={() => { setImmersive(true); setPanel(null) }}><Maximize2 size={19} /></button>
    </header>
    {immersive && <button type="button" className="reader-restore" aria-label="显示阅读工具栏" onClick={() => setImmersive(false)}><Minimize2 size={18} /></button>}
    <main ref={scroller} className="reader-scroller" tabIndex={0} aria-label="阅读正文"
      onScroll={() => {
        const element = scroller.current
        if (!element || !chapterId) return
        const distance = element.scrollHeight - element.clientHeight
        const ratio = distance > 0 ? clamp(element.scrollTop / distance, 0, 1) : 0
        setProgress(ratio)
        historyRef.current = { ...historyRef.current, chapterId, positions: { ...historyRef.current.positions, [chapterId]: ratio } }
        if (saveTimer.current) clearTimeout(saveTimer.current)
        saveTimer.current = setTimeout(saveHistory, 350)
      }}
      onTouchStart={(event) => { const touch = event.touches[0]; touchStart.current = { x: touch.clientX, y: touch.clientY } }}
      onTouchEnd={(event) => {
        if (settings.mode !== 'page' || !touchStart.current || window.getSelection()?.toString()) return
        const touch = event.changedTouches[0]
        const dx = touch.clientX - touchStart.current.x
        const dy = touch.clientY - touchStart.current.y
        if (Math.abs(dx) > 70 && Math.abs(dy) < 50) turnPage(dx < 0 ? 1 : -1)
        touchStart.current = null
      }}>
      {loading ? <p className="reader-empty" role="status">正在打开作品…</p> : error ? <div className="reader-empty" role="alert">{error}<button type="button" onClick={() => { setLoading(true); setError(''); setAttempt((value) => value + 1) }}>重新加载</button></div> : !chapter ? <p className="reader-empty">还没有章节，请返回编辑创建或导入正文。</p> : <article className="reader-page">
        <p className="reader-kicker">{String(index + 1).padStart(2, '0')} / {chapters.length} · {text.replace(/\s/g, '').length} 字</p>
        <h1>{chapter.title}</h1>
        <div ref={body} className="reader-text" data-testid="reader-text"><HighlightedText text={text} marks={annotations.marks} /></div>
        {!text && <p className="reader-empty">本章还没有正文。</p>}
        <nav className="reader-chapter-navigation" aria-label="章节翻页">
          <button type="button" disabled={index <= 0} onClick={() => navigateChapter(chapters[index - 1].id)}><ArrowLeft size={17} />上一章</button>
          <span>{index === chapters.length - 1 ? '已到全书末尾' : '本章完'}</span>
          <button type="button" disabled={index >= chapters.length - 1} onClick={() => navigateChapter(chapters[index + 1].id)}>下一章<ArrowRight size={17} /></button>
        </nav>
      </article>}
    </main>
    {(selection.end > selection.start || annotations.error) && <div className="reader-selection"><HighlightToolbar {...annotations} hasSelection={selection.end > selection.start}
      onPaint={(color) => { annotations.paint(selection.start, selection.end, color); window.getSelection()?.removeAllRanges() }} onRetry={annotations.retry} /></div>}
    <footer className="reader-footer">
      {storageError && <p role="alert" className="highlight-error">阅读偏好或进度保存失败，本机存储空间不足。</p>}
      <div className="reader-progress"><span>本章 {Math.round(progress * 100)}%</span><input aria-label="本章阅读进度" type="range" min="0" max="1000" value={Math.round(progress * 1000)} disabled={!chapter} onChange={(event) => scrollToProgress(Number(event.target.value) / 1000)} /><span>{Math.max(0, index + 1)}/{chapters.length} 章</span></div>
      <div className="reader-actions">
        <button type="button" aria-expanded={panel === 'directory'} onClick={() => setPanel(panel === 'directory' ? null : 'directory')}><List size={20} />目录</button>
        <button type="button" aria-label={bookmark ? '移除当前位置书签' : '添加当前位置书签'} disabled={!chapter} aria-pressed={!!bookmark} onClick={toggleBookmark}><Bookmark size={20} fill={bookmark ? 'currentColor' : 'none'} />{bookmark ? '已加书签' : '加书签'}</button>
        <button type="button" aria-expanded={panel === 'bookmarks'} onClick={() => setPanel(panel === 'bookmarks' ? null : 'bookmarks')}><Bookmark size={20} />书签</button>
        <button type="button" aria-expanded={panel === 'settings'} onClick={() => setPanel(panel === 'settings' ? null : 'settings')}><Settings2 size={20} />设置</button>
        {settings.mode === 'page' && <><button type="button" aria-label="上一页" onClick={() => turnPage(-1)}><ArrowLeft size={20} /></button><button type="button" aria-label="下一页" onClick={() => turnPage(1)}><ArrowRight size={20} /></button></>}
      </div>
    </footer>
    {panel && <div className="reader-panel-scrim" onClick={() => setPanel(null)}><section className="reader-panel" aria-label={panel === 'settings' ? '阅读设置' : panel === 'directory' ? '章节目录' : '阅读书签'} onClick={(event) => event.stopPropagation()}>
      <div className="reader-panel-heading"><h2>{panel === 'settings' ? '阅读设置' : panel === 'directory' ? '章节目录' : '我的书签'}</h2><button type="button" aria-label="关闭阅读面板" onClick={() => setPanel(null)}><X size={20} /></button></div>
      {panel === 'settings' ? <div className="reader-settings">
        <div className="reader-theme-options">{Object.entries(themeNames).map(([theme, name]) => <button type="button" key={theme} data-theme={theme} aria-pressed={settings.theme === theme} onClick={() => updateSettings({ theme: theme as ReadingSettings['theme'] })}>{settings.theme === theme && <Check size={15} />}{name}</button>)}</div>
        <label>字号 <output>{settings.fontSize}</output><input aria-label="阅读字号" type="range" min="14" max="32" step="1" value={settings.fontSize} onChange={(event) => updateSettings({ fontSize: Number(event.target.value) })} /></label>
        <label>行距 <output>{settings.lineHeight.toFixed(1)}</output><input aria-label="阅读行距" type="range" min="1.4" max="2.6" step="0.1" value={settings.lineHeight} onChange={(event) => updateSettings({ lineHeight: Number(event.target.value) })} /></label>
        <label>阅读宽度 <output>{settings.width}</output><input aria-label="阅读宽度" type="range" min="480" max="1100" step="20" value={settings.width} onChange={(event) => updateSettings({ width: Number(event.target.value) })} /></label>
        <label>字体<select aria-label="阅读字体" value={settings.font} onChange={(event) => updateSettings({ font: event.target.value as ReadingSettings['font'] })}><option value="serif">宋体</option><option value="sans">黑体</option></select></label>
        <label>翻页方式<select aria-label="翻页方式" value={settings.mode} onChange={(event) => updateSettings({ mode: event.target.value as ReadingSettings['mode'] })}><option value="scroll">上下滚动</option><option value="page">按屏翻页</option></select></label>
        <p>按屏翻页支持左右滑动、方向键和翻页按钮。阅读进度和偏好自动保存在本机。</p>
      </div> : panel === 'directory' ? <>
        <input className="reader-search" aria-label="搜索章节" placeholder="搜索章节名称" value={query} onChange={(event) => setQuery(event.target.value)} />
        {history.chapterId && history.chapterId !== chapterId && chapters.some((item) => item.id === history.chapterId) && <button type="button" className="reader-resume" onClick={() => navigateChapter(history.chapterId, history.positions[history.chapterId] ?? 0)}>继续上次阅读：{chapters.find((item) => item.id === history.chapterId)?.title}</button>}
        <div className="reader-directory">{chapters.filter((item) => item.title.toLowerCase().includes(query.toLowerCase())).map((item) => <button type="button" key={item.id} aria-current={item.id === chapterId ? 'true' : undefined} onClick={() => navigateChapter(item.id)}><span>{item.title}</span>{item.id === chapterId && <span>正在读</span>}</button>)}</div>
        {chapters.length > 0 && !chapters.some((item) => item.title.toLowerCase().includes(query.toLowerCase())) && <p className="reader-empty">没有匹配的章节。</p>}
      </> : <div className="reader-bookmarks">{history.bookmarks.filter((item) => chapters.some((row) => row.id === item.chapterId)).map((item) => <div key={item.id}>
        <button type="button" className="reader-bookmark-link" onClick={() => navigateChapter(item.chapterId, item.progress)}><strong>{chapters.find((row) => row.id === item.chapterId)?.title} · {Math.round(item.progress * 100)}%</strong><span>{item.excerpt || '章节开头'}</span></button>
        <button type="button" aria-label="删除书签" onClick={() => removeBookmark(item.id)}><Trash2 size={18} /></button>
      </div>)}{!history.bookmarks.some((item) => chapters.some((row) => row.id === item.chapterId)) && <p className="reader-empty">在喜欢的位置点「加书签」，下次可从这里继续阅读。</p>}</div>}
    </section></div>}
  </dialog>, document.body)
}
