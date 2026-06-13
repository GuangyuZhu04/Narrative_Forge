import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useParams } from 'react-router-dom'
import {
  characterApi,
  chapterApi,
  discussionApi,
  getActiveLLMConfigId,
  outlineApi,
} from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  FilePlus2,
  FileText,
  Import,
  Layers,
  ListTree,
  Loader2,
  MessageSquare,
  PencilLine,
  Plus,
  Send,
  Trash2,
  Users,
} from 'lucide-react'
import type {
  Character,
  Chapter,
  DiscussionMessage,
  DiscussionSession,
  DiscussionSessionDetail,
  Outline,
  OutlineNode,
} from '@/types'

type ToastType = 'success' | 'error'
type ImportTarget = 'chapter_content' | 'characters' | 'outline_volume' | 'outline_chapter'
type ContextSource =
  | 'novel_content'
  | 'characters'
  | 'outline'
  | 'outline_volume'
  | 'outline_chapter'
type ChapterImportMode = 'append' | 'replace'

interface Toast {
  id: number
  type: ToastType
  message: string
}

let toastId = 0

const defaultSystemPrompt =
  '你是一位专业的中文长篇小说创作顾问。你需要和作者进行多轮讨论，帮助作者梳理故事设定、人物动机、情节推进、章节安排、冲突升级和伏笔回收。回答应当具体、可落地，尽量给出可直接导入小说项目的内容。'

const getApiErrorDetail = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response
    ?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

const getMessageRoleLabel = (role: string) => (role === 'user' ? '我' : 'AI')

const makeDefaultTitle = (text: string) => {
  const firstLine = text
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean)
  if (!firstLine) return '来自小说讨论'
  return firstLine.replace(/^#+\s*/, '').slice(0, 40)
}

const countChineseChars = (text: string) =>
  (text.match(/[\u4e00-\u9fff]/g) || []).length

const COLLAPSED_MESSAGE_MAX_HEIGHT_PX = 456
const COLLAPSED_THINKING_MAX_HEIGHT_PX = 200

const flattenVolumes = (nodes: OutlineNode[]): OutlineNode[] => {
  const volumes: OutlineNode[] = []
  const visit = (items: OutlineNode[]) => {
    items.forEach((item) => {
      if (item.node_type === 'VOLUME') volumes.push(item)
      if (item.children?.length) visit(item.children)
    })
  }
  visit(nodes)
  return volumes
}

const flattenOutlineNodes = (nodes: OutlineNode[]): OutlineNode[] => {
  const flattened: OutlineNode[] = []
  const visit = (items: OutlineNode[]) => {
    items.forEach((item) => {
      flattened.push(item)
      if (item.children?.length) visit(item.children)
    })
  }
  visit(nodes)
  return flattened
}

const outlineTypeLabels: Record<OutlineNode['node_type'], string> = {
  VOLUME: '卷',
  CHAPTER: '章',
  SCENE: '场景',
  PLOT_POINT: '情节点',
  KEY_EVENT: '关键事件',
}

const formatOutlineNode = (node: OutlineNode, depth = 0): string => {
  const indent = '  '.repeat(depth)
  const lines = [`${indent}【${outlineTypeLabels[node.node_type]}】${node.title}`]
  if (node.summary?.trim()) {
    lines.push(`${indent}${node.summary.trim()}`)
  }
  node.children?.forEach((child) => {
    lines.push(formatOutlineNode(child, depth + 1))
  })
  return lines.join('\n')
}

const formatRecord = (record: Record<string, unknown> | null): string => {
  if (!record) return ''
  return Object.entries(record)
    .map(([key, value]) => {
      const text =
        typeof value === 'string'
          ? value
          : JSON.stringify(value, null, 2)
      return `${key}：${text}`
    })
    .join('\n')
}

const formatCharacter = (character: Character) => {
  const lines = [`【人物】${character.name}`]
  if (character.aliases?.length) lines.push(`别名：${character.aliases.join('、')}`)
  const basicInfo = formatRecord(character.basic_info)
  if (basicInfo) lines.push(`基本信息：\n${basicInfo}`)
  const personality = formatRecord(character.personality)
  if (personality) lines.push(`性格：\n${personality}`)
  const growthArc = formatRecord(character.growth_arc)
  if (growthArc) lines.push(`成长弧线：\n${growthArc}`)
  if (character.biography?.trim()) lines.push(`人物小传：\n${character.biography}`)
  if (character.setting_collection?.trim()) {
    lines.push(`人物设定集：\n${character.setting_collection}`)
  }
  if (character.notes?.trim()) lines.push(`备注：\n${character.notes}`)
  return lines.join('\n')
}

interface DiscussionMessageBubbleProps {
  message: DiscussionMessage
  onExport: (text: string) => void
}

const DiscussionMessageBubble: React.FC<DiscussionMessageBubbleProps> = ({
  message,
  onExport,
}) => {
  const isUser = message.role === 'user'
  const canCollapse = isUser
  const [expanded, setExpanded] = useState(false)
  const [isOverflowing, setIsOverflowing] = useState(false)
  const [thinkingExpanded, setThinkingExpanded] = useState(false)
  const [thinkingOverflowing, setThinkingOverflowing] = useState(false)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const thinkingRef = useRef<HTMLDivElement | null>(null)
  const thinkingContent = !isUser ? message.thinking_content?.trim() || '' : ''

  useEffect(() => {
    if (!canCollapse) {
      setExpanded(false)
      setIsOverflowing(false)
      return
    }

    const element = contentRef.current
    if (!element) return

    const updateOverflow = () => {
      const nextIsOverflowing =
        element.scrollHeight > COLLAPSED_MESSAGE_MAX_HEIGHT_PX + 1
      setIsOverflowing(nextIsOverflowing)
      if (!nextIsOverflowing) setExpanded(false)
    }

    updateOverflow()
    const resizeObserver = new ResizeObserver(updateOverflow)
    resizeObserver.observe(element)

    return () => resizeObserver.disconnect()
  }, [canCollapse, message.content])

  useEffect(() => {
    if (!thinkingContent) {
      setThinkingExpanded(false)
      setThinkingOverflowing(false)
      return
    }

    const element = thinkingRef.current
    if (!element) return

    const updateOverflow = () => {
      const nextIsOverflowing =
        element.scrollHeight > COLLAPSED_THINKING_MAX_HEIGHT_PX + 1
      setThinkingOverflowing(nextIsOverflowing)
      if (!nextIsOverflowing) setThinkingExpanded(false)
    }

    updateOverflow()
    const resizeObserver = new ResizeObserver(updateOverflow)
    resizeObserver.observe(element)

    return () => resizeObserver.disconnect()
  }, [thinkingContent])

  const actionButtonClass = isUser
    ? 'text-white hover:bg-blue-500'
    : 'text-gray-500 hover:bg-gray-100'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[78%] rounded-lg border px-4 py-3 text-sm leading-relaxed shadow-sm ${
          isUser
            ? 'border-blue-100 bg-blue-600 text-white'
            : 'border-gray-200 bg-white text-gray-800'
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-3">
          <span
            className={`text-xs font-medium ${
              isUser ? 'text-blue-100' : 'text-gray-400'
            }`}
          >
            {getMessageRoleLabel(message.role)}
          </span>
        </div>

        {thinkingContent && (
          <div className="mb-3 rounded-md border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-medium text-amber-700">思考过程</span>
              {thinkingOverflowing && (
                <button
                  type="button"
                  className="rounded px-1.5 py-0.5 text-amber-700 hover:bg-amber-100"
                  onClick={() => setThinkingExpanded((prev) => !prev)}
                >
                  {thinkingExpanded ? '收起' : '展开'}
                </button>
              )}
            </div>
            <div className="relative">
              <div
                ref={thinkingRef}
                className={`whitespace-pre-wrap leading-relaxed transition-[max-height] duration-200 ${
                  thinkingOverflowing && !thinkingExpanded
                    ? 'overflow-hidden'
                    : ''
                }`}
                style={{
                  maxHeight:
                    thinkingOverflowing && !thinkingExpanded
                      ? COLLAPSED_THINKING_MAX_HEIGHT_PX
                      : undefined,
                }}
              >
                {thinkingContent}
              </div>
              {thinkingOverflowing && !thinkingExpanded && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-amber-50 to-transparent" />
              )}
            </div>
          </div>
        )}

        <div className="relative">
          <div
            ref={contentRef}
            className={`whitespace-pre-wrap transition-[max-height] duration-200 ${
              canCollapse && isOverflowing && !expanded ? 'overflow-hidden' : ''
            }`}
            style={{
              maxHeight:
                canCollapse && isOverflowing && !expanded
                  ? COLLAPSED_MESSAGE_MAX_HEIGHT_PX
                  : undefined,
            }}
          >
            {message.content}
          </div>
          {canCollapse && isOverflowing && !expanded && (
            <div
              className={`pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t ${
                isUser ? 'from-blue-600' : 'from-white'
              } to-transparent`}
            />
          )}
        </div>

        <div
          className={`mt-3 flex items-center gap-2 ${
            canCollapse && isOverflowing ? 'justify-between' : 'justify-end'
          }`}
        >
          {canCollapse && isOverflowing && (
            <Button
              variant="ghost"
              size="sm"
              className={`h-7 px-2 ${actionButtonClass}`}
              onClick={() => setExpanded((prev) => !prev)}
            >
              {expanded ? (
                <ChevronUp className="mr-1 h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="mr-1 h-3.5 w-3.5" />
              )}
              {expanded ? '收起对话' : '对话展开'}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className={`h-7 px-2 ${actionButtonClass}`}
            onClick={() => onExport(message.content)}
            disabled={!message.content.trim()}
          >
            <Import className="mr-1 h-3.5 w-3.5" />
            导出讨论
          </Button>
        </div>
      </div>
    </div>
  )
}

export const NovelDiscussion: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [sessions, setSessions] = useState<DiscussionSession[]>([])
  const [activeSession, setActiveSession] =
    useState<DiscussionSessionDetail | null>(null)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [sending, setSending] = useState(false)
  const [messageDraft, setMessageDraft] = useState('')
  const [systemPromptDraft, setSystemPromptDraft] = useState(defaultSystemPrompt)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [renameSession, setRenameSession] = useState<DiscussionSession | null>(
    null
  )
  const [renameTitleDraft, setRenameTitleDraft] = useState('')
  const [renamingSession, setRenamingSession] = useState(false)

  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importText, setImportText] = useState('')
  const [importTarget, setImportTarget] = useState<ImportTarget>('chapter_content')
  const [importTitle, setImportTitle] = useState('')
  const [chapterImportMode, setChapterImportMode] =
    useState<ChapterImportMode>('append')
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapterId, setSelectedChapterId] = useState('')
  const [outlines, setOutlines] = useState<Outline[]>([])
  const [selectedOutlineId, setSelectedOutlineId] = useState('')
  const [outlineTree, setOutlineTree] = useState<OutlineNode[]>([])
  const [selectedVolumeId, setSelectedVolumeId] = useState('')
  const [loadingImportTargets, setLoadingImportTargets] = useState(false)
  const [importing, setImporting] = useState(false)
  const [showContextDialog, setShowContextDialog] = useState(false)
  const [contextSource, setContextSource] =
    useState<ContextSource>('novel_content')
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedOutlineChapterId, setSelectedOutlineChapterId] = useState('')
  const [loadingContextSources, setLoadingContextSources] = useState(false)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const activeSessionIdRef = useRef<string | null>(null)
  const scrollPositionsRef = useRef<Record<string, number>>({})

  const showToast = useCallback((type: ToastType, message: string) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id))
    }, 3000)
  }, [])

  const volumes = useMemo(() => flattenVolumes(outlineTree), [outlineTree])
  const outlineChapters = useMemo(
    () =>
      flattenOutlineNodes(outlineTree).filter(
        (node) => node.node_type === 'CHAPTER'
      ),
    [outlineTree]
  )
  const latestMessageContent =
    activeSession?.messages[activeSession.messages.length - 1]?.content || ''

  useEffect(() => {
    activeSessionIdRef.current = activeSession?.id || null
  }, [activeSession?.id])

  const saveCurrentScrollPosition = useCallback(() => {
    const sessionId = activeSessionIdRef.current
    const element = scrollRef.current
    if (!sessionId || !element) return
    scrollPositionsRef.current[sessionId] = element.scrollTop
  }, [])

  const loadSessions = useCallback(async () => {
    if (!projectId) return
    setLoadingSessions(true)
    try {
      const result = (await discussionApi.list(projectId)) as unknown as {
        data: DiscussionSession[]
      }
      setSessions(result.data || [])
      if (!activeSession && result.data?.length > 0) {
        await loadSessionDetail(result.data[0].id)
      }
    } catch {
      showToast('error', '加载小说讨论失败')
    } finally {
      setLoadingSessions(false)
    }
  }, [projectId, activeSession, showToast])

  const loadSessionDetail = useCallback(
    async (sessionId: string) => {
      if (!projectId) return
      if (activeSessionIdRef.current !== sessionId) {
        saveCurrentScrollPosition()
      }
      setLoadingDetail(true)
      try {
        const detail = (await discussionApi.get(
          projectId,
          sessionId
        )) as unknown as DiscussionSessionDetail
        setActiveSession(detail)
        setSystemPromptDraft(detail.system_prompt || defaultSystemPrompt)
      } catch {
        showToast('error', '加载讨论记录失败')
      } finally {
        setLoadingDetail(false)
      }
    },
    [projectId, saveCurrentScrollPosition, showToast]
  )

  useEffect(() => {
    void loadSessions()
  }, [loadSessions])

  useLayoutEffect(() => {
    const sessionId = activeSession?.id
    const element = scrollRef.current
    if (!sessionId || !element || sending) return

    const savedTop = scrollPositionsRef.current[sessionId]
    requestAnimationFrame(() => {
      const currentElement = scrollRef.current
      if (!currentElement) return
      currentElement.scrollTop =
        typeof savedTop === 'number'
          ? Math.min(savedTop, currentElement.scrollHeight)
          : currentElement.scrollHeight
    })
  }, [activeSession?.id, loadingDetail, sending])

  useEffect(() => {
    if (!sending) return
    const element = scrollRef.current
    if (!element) return
    element.scrollTo({
      top: element.scrollHeight,
      behavior: 'smooth',
    })
  }, [activeSession?.messages.length, latestMessageContent, sending])

  const createSession = async () => {
    if (!projectId) return null
    setCreatingSession(true)
    try {
      const session = (await discussionApi.create(projectId, {
        title: '新的小说讨论',
        system_prompt: systemPromptDraft || defaultSystemPrompt,
      })) as unknown as DiscussionSession
      setSessions((prev) => [session, ...prev])
      await loadSessionDetail(session.id)
      return session
    } catch {
      showToast('error', '创建讨论失败')
      return null
    } finally {
      setCreatingSession(false)
    }
  }

  const updateSessionPrompt = async () => {
    if (!projectId || !activeSession) return
    try {
      const updated = (await discussionApi.update(projectId, activeSession.id, {
        system_prompt: systemPromptDraft || defaultSystemPrompt,
      })) as unknown as DiscussionSession
      setActiveSession((prev) =>
        prev ? { ...prev, system_prompt: updated.system_prompt } : prev
      )
      setSessions((prev) =>
        prev.map((session) => (session.id === updated.id ? updated : session))
      )
      showToast('success', '系统提示词已保存')
    } catch {
      showToast('error', '保存系统提示词失败')
    }
  }

  const openRenameDialog = (session: DiscussionSession) => {
    setRenameSession(session)
    setRenameTitleDraft(session.title)
  }

  const closeRenameDialog = () => {
    if (renamingSession) return
    setRenameSession(null)
    setRenameTitleDraft('')
  }

  const renameDiscussion = async () => {
    if (!projectId || !renameSession) return
    const nextTitle = renameTitleDraft.trim()
    if (!nextTitle) {
      showToast('error', '讨论名称不能为空')
      return
    }

    setRenamingSession(true)
    try {
      const updated = (await discussionApi.update(projectId, renameSession.id, {
        title: nextTitle,
      })) as unknown as DiscussionSession
      setSessions((prev) =>
        prev.map((session) => (session.id === updated.id ? updated : session))
      )
      setActiveSession((prev) =>
        prev?.id === updated.id ? { ...prev, ...updated } : prev
      )
      setRenameSession(null)
      setRenameTitleDraft('')
      showToast('success', '讨论名称已更新')
    } catch {
      showToast('error', '更新讨论名称失败')
    } finally {
      setRenamingSession(false)
    }
  }

  const deleteSession = async (session: DiscussionSession) => {
    if (!projectId) return
    try {
      await discussionApi.delete(projectId, session.id)
      setSessions((prev) => prev.filter((item) => item.id !== session.id))
      if (activeSession?.id === session.id) {
        saveCurrentScrollPosition()
        setActiveSession(null)
      }
      if (renameSession?.id === session.id) {
        setRenameSession(null)
        setRenameTitleDraft('')
      }
      showToast('success', '讨论已删除')
    } catch {
      showToast('error', '删除讨论失败')
    }
  }

  const sendMessage = async () => {
    if (!projectId || sending || !messageDraft.trim()) return
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId) {
      showToast('error', '请先配置 LLM')
      return
    }

    let session = activeSession
    if (!session) {
      const created = await createSession()
      if (!created) return
      session = {
        ...created,
        messages: [],
      }
    }

    const content = messageDraft.trim()
    setMessageDraft('')
    setSending(true)
    try {
      const pendingId = Date.now()
      const optimisticUser: DiscussionMessage = {
        id: `pending-user-${pendingId}`,
        session_id: session.id,
        role: 'user',
        content,
        sort_order: session.messages.length,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      const optimisticAssistant: DiscussionMessage = {
        id: `pending-assistant-${pendingId}`,
        session_id: session.id,
        role: 'assistant',
        content: '',
        sort_order: session.messages.length + 1,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      setActiveSession((prev) =>
        prev?.id === session.id
          ? {
              ...prev,
              messages: [...prev.messages, optimisticUser, optimisticAssistant],
            }
          : prev
      )

      const resp = await fetch(
        `/api/v1/projects/${projectId}/discussions/${session.id}/messages/stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            llm_config_id: cfgId,
            content,
          }),
        }
      )
      if (!resp.ok) {
        throw new Error(`AI 回复请求失败（${resp.status}）`)
      }
      const reader = resp.body?.getReader()
      if (!reader) throw new Error('AI 回复响应不可读取')

      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false
      let assistantContent = ''
      let thinkingContent = ''

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return
        const data = line.slice(6)
        if (!data || data === '{}') return

        const parsed = JSON.parse(data) as {
          type?: string
          content?: string
          error?: string
          session?: DiscussionSession
          user_message?: DiscussionMessage
          assistant_message?: DiscussionMessage
        }
        if (parsed.type === 'error') {
          throw new Error(parsed.error || 'AI 回复失败')
        }
        if (parsed.type === 'chunk' && parsed.content) {
          assistantContent += parsed.content
          setActiveSession((prev) =>
            prev?.id === session.id
              ? {
                  ...prev,
                  messages: prev.messages.map((message) =>
                    message.id === optimisticAssistant.id
                      ? {
                          ...message,
                          content: message.content + parsed.content,
                        }
                      : message
                  ),
                }
              : prev
          )
        }
        if (parsed.type === 'thinking' && parsed.content) {
          thinkingContent += parsed.content
          setActiveSession((prev) =>
            prev?.id === session.id
              ? {
                  ...prev,
                  messages: prev.messages.map((message) =>
                    message.id === optimisticAssistant.id
                      ? {
                          ...message,
                          thinking_content:
                            (message.thinking_content || '') + parsed.content,
                        }
                      : message
                  ),
                }
              : prev
          )
        }
        if (
          parsed.type === 'done' &&
          parsed.session &&
          parsed.user_message &&
          parsed.assistant_message
        ) {
          streamDone = true
          const finalSession = parsed.session
          const finalUserMessage = {
            ...optimisticUser,
            ...parsed.user_message,
            content: parsed.user_message.content ?? optimisticUser.content,
          }
          const finalAssistantMessage = {
            ...optimisticAssistant,
            ...parsed.assistant_message,
            content: parsed.assistant_message.content ?? assistantContent,
            thinking_content: thinkingContent,
          }
          setActiveSession((prev) =>
            prev?.id === session.id
              ? {
                  ...prev,
                  ...finalSession,
                  messages: [
                    ...prev.messages.filter(
                      (message) =>
                        message.id !== optimisticUser.id &&
                        message.id !== optimisticAssistant.id
                    ),
                    finalUserMessage,
                    finalAssistantMessage,
                  ].sort((a, b) => a.sort_order - b.sort_order),
                }
              : prev
          )
          setSessions((prev) =>
            prev.map((item) =>
              item.id === finalSession.id ? finalSession : item
            )
          )
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          handleSseLine(line)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleSseLine(buffer)
      }
      if (!streamDone) {
        throw new Error('AI 回复未正常结束，请稍后重试')
      }
    } catch (error) {
      setMessageDraft(content)
      await loadSessionDetail(session.id)
      showToast(
        'error',
        error instanceof Error
          ? error.message
          : getApiErrorDetail(error, 'AI 回复失败，请检查 LLM 配置后重试')
      )
    } finally {
      setSending(false)
    }
  }

  const loadImportTargets = async () => {
    if (!projectId) return
    setLoadingImportTargets(true)
    try {
      const [chapterResult, outlineResult] = await Promise.all([
        chapterApi.list(projectId) as Promise<unknown>,
        outlineApi.list(projectId) as Promise<unknown>,
      ])
      const nextChapters =
        ((chapterResult as { data?: Chapter[] }).data || []) as Chapter[]
      const nextOutlines =
        ((outlineResult as { data?: Outline[] }).data || []) as Outline[]
      setChapters(nextChapters)
      setOutlines(nextOutlines)
      if (!selectedChapterId && nextChapters.length > 0) {
        setSelectedChapterId(nextChapters[0].id)
      }
      const outlineId = selectedOutlineId || nextOutlines[0]?.id || ''
      setSelectedOutlineId(outlineId)
      if (outlineId) {
        const treeResult = (await outlineApi.getTree(
          projectId,
          outlineId
        )) as unknown as { tree: OutlineNode[] }
        setOutlineTree(treeResult.tree || [])
        const nextVolumes = flattenVolumes(treeResult.tree || [])
        if (!selectedVolumeId && nextVolumes.length > 0) {
          setSelectedVolumeId(nextVolumes[0].id)
        }
      } else {
        setOutlineTree([])
        setSelectedVolumeId('')
      }
    } catch {
      showToast('error', '加载导入目标失败')
    } finally {
      setLoadingImportTargets(false)
    }
  }

  const handleOutlineChange = async (outlineId: string) => {
    if (!projectId) return
    setSelectedOutlineId(outlineId)
    setSelectedVolumeId('')
    setSelectedOutlineChapterId('')
    if (!outlineId) {
      setOutlineTree([])
      return
    }
    try {
      const treeResult = (await outlineApi.getTree(
        projectId,
        outlineId
      )) as unknown as { tree: OutlineNode[] }
      setOutlineTree(treeResult.tree || [])
      const nextVolumes = flattenVolumes(treeResult.tree || [])
      if (nextVolumes.length > 0) setSelectedVolumeId(nextVolumes[0].id)
      const nextChapters = flattenOutlineNodes(treeResult.tree || []).filter(
        (node) => node.node_type === 'CHAPTER'
      )
      if (nextChapters.length > 0) setSelectedOutlineChapterId(nextChapters[0].id)
    } catch {
      showToast('error', '加载大纲失败')
    }
  }

  const loadContextSources = async () => {
    if (!projectId) return
    setLoadingContextSources(true)
    try {
      const [chapterResult, characterResult, outlineResult] = await Promise.all([
        chapterApi.list(projectId) as Promise<unknown>,
        characterApi.list(projectId) as Promise<unknown>,
        outlineApi.list(projectId) as Promise<unknown>,
      ])
      const nextChapters =
        ((chapterResult as { data?: Chapter[] }).data || []) as Chapter[]
      const nextCharacters =
        ((characterResult as { data?: Character[] }).data || []) as Character[]
      const nextOutlines =
        ((outlineResult as { data?: Outline[] }).data || []) as Outline[]
      setChapters(nextChapters)
      setCharacters(nextCharacters)
      setOutlines(nextOutlines)
      if (!selectedChapterId && nextChapters.length > 0) {
        setSelectedChapterId(nextChapters[0].id)
      }
      const outlineId = selectedOutlineId || nextOutlines[0]?.id || ''
      setSelectedOutlineId(outlineId)
      if (outlineId) {
        const treeResult = (await outlineApi.getTree(
          projectId,
          outlineId
        )) as unknown as { tree: OutlineNode[] }
        const tree = treeResult.tree || []
        setOutlineTree(tree)
        const nextVolumes = flattenVolumes(tree)
        if (!selectedVolumeId && nextVolumes.length > 0) {
          setSelectedVolumeId(nextVolumes[0].id)
        }
        const nextOutlineChapters = flattenOutlineNodes(tree).filter(
          (node) => node.node_type === 'CHAPTER'
        )
        if (!selectedOutlineChapterId && nextOutlineChapters.length > 0) {
          setSelectedOutlineChapterId(nextOutlineChapters[0].id)
        }
      } else {
        setOutlineTree([])
        setSelectedVolumeId('')
        setSelectedOutlineChapterId('')
      }
    } catch {
      showToast('error', '加载项目上下文失败')
    } finally {
      setLoadingContextSources(false)
    }
  }

  const openContextDialog = () => {
    setShowContextDialog(true)
    void loadContextSources()
  }

  const appendToMessageDraft = (text: string) => {
    setMessageDraft((prev) =>
      prev.trim() ? `${prev.trim()}\n\n${text}` : text
    )
  }

  const importContextToDraft = async () => {
    if (!projectId) return
    try {
      let text = ''
      if (contextSource === 'novel_content') {
        if (!selectedChapterId) {
          showToast('error', '请选择章节')
          return
        }
        const chapter = (await chapterApi.get(
          projectId,
          selectedChapterId
        )) as unknown as Chapter
        text = `【小说内容：${chapter.title}】\n${chapter.content || chapter.summary || '暂无内容'}`
      } else if (contextSource === 'characters') {
        if (characters.length === 0) {
          showToast('error', '当前项目暂无人物')
          return
        }
        text = `【人物信息】\n${characters.map(formatCharacter).join('\n\n')}`
      } else if (contextSource === 'outline') {
        const outline = outlines.find((item) => item.id === selectedOutlineId)
        if (!outline) {
          showToast('error', '请选择大纲')
          return
        }
        const treeText = outlineTree.map((node) => formatOutlineNode(node)).join('\n')
        text = `【大纲：${outline.title}】\n${outline.description || ''}\n${treeText}`.trim()
      } else if (contextSource === 'outline_volume') {
        const volume = volumes.find((item) => item.id === selectedVolumeId)
        if (!volume) {
          showToast('error', '请选择卷')
          return
        }
        text = `【大纲卷】\n${formatOutlineNode(volume)}`
      } else if (contextSource === 'outline_chapter') {
        const chapterNode = outlineChapters.find(
          (item) => item.id === selectedOutlineChapterId
        )
        if (!chapterNode) {
          showToast('error', '请选择大纲章节')
          return
        }
        text = `【大纲章节】\n${formatOutlineNode(chapterNode)}`
      }

      if (!text.trim()) {
        showToast('error', '暂无可导入内容')
        return
      }
      appendToMessageDraft(text.trim())
      setShowContextDialog(false)
      showToast('success', '已导入到当前输入框')
    } catch {
      showToast('error', '导入上下文失败')
    }
  }

  const openImportDialog = (text: string) => {
    const nextText = text.trim()
    if (!nextText) {
      showToast('error', '暂无可导入内容')
      return
    }
    setImportText(nextText)
    setImportTitle(makeDefaultTitle(nextText))
    setShowImportDialog(true)
    void loadImportTargets()
  }

  const runImport = async () => {
    if (!projectId || !importText.trim()) return
    setImporting(true)
    try {
      if (importTarget === 'chapter_content') {
        if (!selectedChapterId) {
          showToast('error', '请选择章节')
          return
        }
        const chapter = (await chapterApi.get(
          projectId,
          selectedChapterId
        )) as unknown as Chapter
        const nextContent =
          chapterImportMode === 'replace'
            ? importText
            : [chapter.content, importText].filter(Boolean).join('\n\n')
        await chapterApi.update(projectId, selectedChapterId, {
          content: nextContent,
          word_count: countChineseChars(nextContent),
        })
        showToast('success', '已导出到小说情节')
      } else if (importTarget === 'characters') {
        const cfgId = await getActiveLLMConfigId()
        if (!cfgId) {
          showToast('error', '请先配置 LLM')
          return
        }
        const result = (await characterApi.importFromText(
          projectId,
          cfgId,
          importText
        )) as unknown as { count: number }
        showToast('success', `已导出 ${result.count || 0} 个人物`)
      } else if (importTarget === 'outline_volume') {
        if (!selectedOutlineId) {
          showToast('error', '请选择大纲')
          return
        }
        await outlineApi.addNode(projectId, {
          outline_id: selectedOutlineId,
          parent_id: null,
          node_type: 'VOLUME',
          title: importTitle.trim() || '来自小说讨论的卷',
          summary: importText,
        })
        showToast('success', '已导出为大纲卷')
      } else if (importTarget === 'outline_chapter') {
        if (!selectedOutlineId || !selectedVolumeId) {
          showToast('error', '请选择大纲和卷')
          return
        }
        await outlineApi.addNode(projectId, {
          outline_id: selectedOutlineId,
          parent_id: selectedVolumeId,
          node_type: 'CHAPTER',
          title: importTitle.trim() || '来自小说讨论的章节',
          summary: importText,
        })
        showToast('success', '已导出为大纲章节')
      }
      setShowImportDialog(false)
    } catch (error) {
      showToast('error', getApiErrorDetail(error, '导出失败，请稍后重试'))
    } finally {
      setImporting(false)
    }
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }

  return (
    <div className="flex h-full bg-gray-50">
      <div className="flex w-72 flex-col border-r bg-white">
        <div className="flex items-center justify-between border-b p-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <MessageSquare className="h-5 w-5 text-blue-500" />
            小说讨论
          </h2>
          <Button
            size="icon"
            variant="ghost"
            onClick={createSession}
            disabled={creatingSession}
            title="新讨论"
          >
            {creatingSession ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
          </Button>
        </div>
        <div className="flex-1 overflow-auto p-2">
          {loadingSessions ? (
            <div className="flex items-center gap-2 p-3 text-sm text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中...
            </div>
          ) : sessions.length === 0 ? (
            <div className="p-3 text-sm text-gray-400">暂无讨论</div>
          ) : (
            <div className="space-y-1">
              {sessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => loadSessionDetail(session.id)}
                  className={`group flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                    activeSession?.id === session.id
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  <MessageSquare className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{session.title}</span>
                  <span
                    role="button"
                    tabIndex={0}
                    className="rounded p-1 text-gray-300 opacity-0 hover:bg-blue-50 hover:text-blue-500 group-hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation()
                      openRenameDialog(session)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        e.stopPropagation()
                        openRenameDialog(session)
                      }
                    }}
                    title="修改讨论名称"
                  >
                    <PencilLine className="h-3.5 w-3.5" />
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    className="rounded p-1 text-gray-300 opacity-0 hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation()
                      void deleteSession(session)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        e.stopPropagation()
                        void deleteSession(session)
                      }
                    }}
                    title="删除讨论"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {activeSession ? (
          <>
            <div className="border-b bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <h3 className="truncate text-lg font-semibold text-gray-800">
                      {activeSession.title}
                    </h3>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7 shrink-0 text-gray-400 hover:text-blue-600"
                      onClick={() => openRenameDialog(activeSession)}
                      title="修改讨论名称"
                    >
                      <PencilLine className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="text-xs text-gray-400">
                    {activeSession.messages.length} 条消息
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <textarea
                  className="min-h-[52px] flex-1 resize-y rounded-md border p-2 text-xs leading-relaxed text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={systemPromptDraft}
                  onChange={(e) => setSystemPromptDraft(e.target.value)}
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={updateSessionPrompt}
                  disabled={loadingDetail || sending}
                >
                  保存提示词
                </Button>
              </div>
            </div>

            <div
              ref={scrollRef}
              className="flex-1 overflow-auto p-6"
              onScroll={saveCurrentScrollPosition}
            >
              {loadingDetail ? (
                <div className="flex h-full items-center justify-center text-gray-400">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  加载讨论中...
                </div>
              ) : activeSession.messages.length === 0 ? (
                <div className="flex h-full items-center justify-center">
                  <div className="text-center text-gray-400">
                    <MessageSquare className="mx-auto mb-3 h-12 w-12" />
                    <p>开始和 AI 讨论你的小说构思</p>
                  </div>
                </div>
              ) : (
                <div className="mx-auto max-w-4xl space-y-4">
                  {activeSession.messages.map((message) => (
                    <DiscussionMessageBubble
                      key={message.id}
                      message={message}
                      onExport={openImportDialog}
                    />
                  ))}
                  {sending && (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      AI 正在回复...
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="border-t bg-white p-4">
              <div className="mx-auto flex max-w-4xl gap-2">
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={openContextDialog}
                      disabled={sending}
                    >
                      <FilePlus2 className="mr-1 h-4 w-4" />
                      导入上下文
                    </Button>
                  </div>
                  <textarea
                    className="min-h-[76px] resize-none rounded-md border p-3 text-sm leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    value={messageDraft}
                    onChange={(e) => setMessageDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                        e.preventDefault()
                        void sendMessage()
                      }
                    }}
                    placeholder="输入你想讨论的设定、剧情问题或人物动机..."
                  />
                </div>
                <Button
                  className="self-end"
                  onClick={sendMessage}
                  disabled={sending || !messageDraft.trim()}
                >
                  {sending ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="mr-1 h-4 w-4" />
                  )}
                  发送
                </Button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <MessageSquare className="mx-auto mb-4 h-16 w-16 text-gray-300" />
              <p className="mb-4 text-gray-500">创建一个小说讨论开始多轮对话</p>
              <Button onClick={createSession} disabled={creatingSession}>
                {creatingSession ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-1 h-4 w-4" />
                )}
                新讨论
              </Button>
            </div>
          </div>
        )}
      </div>

      <Modal
        open={Boolean(renameSession)}
        onClose={closeRenameDialog}
        title="修改讨论名称"
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            void renameDiscussion()
          }}
        >
          <Input
            label="讨论名称"
            value={renameTitleDraft}
            onChange={(e) => setRenameTitleDraft(e.target.value)}
            maxLength={200}
            autoFocus
            disabled={renamingSession}
            placeholder="输入新的讨论名称"
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={closeRenameDialog}
              disabled={renamingSession}
            >
              取消
            </Button>
            <Button
              type="submit"
              disabled={renamingSession || !renameTitleDraft.trim()}
            >
              {renamingSession && (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              )}
              保存
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={showImportDialog}
        onClose={() => setShowImportDialog(false)}
        title="导出讨论内容"
      >
        <div className="max-h-[72vh] space-y-4 overflow-auto pr-1">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setImportTarget('chapter_content')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                importTarget === 'chapter_content'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <BookOpen className="mb-2 h-4 w-4" />
              小说情节
            </button>
            <button
              type="button"
              onClick={() => setImportTarget('characters')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                importTarget === 'characters'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Users className="mb-2 h-4 w-4" />
              人物导入
            </button>
            <button
              type="button"
              onClick={() => setImportTarget('outline_volume')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                importTarget === 'outline_volume'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Layers className="mb-2 h-4 w-4" />
              大纲卷
            </button>
            <button
              type="button"
              onClick={() => setImportTarget('outline_chapter')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                importTarget === 'outline_chapter'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <ListTree className="mb-2 h-4 w-4" />
              大纲章节
            </button>
          </div>

          {loadingImportTargets ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载导入目标...
            </div>
          ) : (
            <>
              {importTarget === 'chapter_content' && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">
                      章节
                    </label>
                    <select
                      className="w-full rounded-md border px-3 py-2 text-sm"
                      value={selectedChapterId}
                      onChange={(e) => setSelectedChapterId(e.target.value)}
                    >
                      {chapters.map((chapter) => (
                        <option key={chapter.id} value={chapter.id}>
                          {chapter.title}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant={chapterImportMode === 'append' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setChapterImportMode('append')}
                    >
                      追加
                    </Button>
                    <Button
                      variant={chapterImportMode === 'replace' ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setChapterImportMode('replace')}
                    >
                      覆盖
                    </Button>
                  </div>
                </div>
              )}

              {(importTarget === 'outline_volume' ||
                importTarget === 'outline_chapter') && (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-sm font-medium text-gray-700">
                      大纲
                    </label>
                    <select
                      className="w-full rounded-md border px-3 py-2 text-sm"
                      value={selectedOutlineId}
                      onChange={(e) => void handleOutlineChange(e.target.value)}
                    >
                      {outlines.map((outline) => (
                        <option key={outline.id} value={outline.id}>
                          {outline.title}
                        </option>
                      ))}
                    </select>
                  </div>
                  {importTarget === 'outline_chapter' && (
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        所属卷
                      </label>
                      <select
                        className="w-full rounded-md border px-3 py-2 text-sm"
                        value={selectedVolumeId}
                        onChange={(e) => setSelectedVolumeId(e.target.value)}
                      >
                        {volumes.map((volume) => (
                          <option key={volume.id} value={volume.id}>
                            {volume.title}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  <Input
                    label="标题"
                    value={importTitle}
                    onChange={(e) => setImportTitle(e.target.value)}
                  />
                </div>
              )}
            </>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              导出内容
            </label>
            <textarea
              className="min-h-[220px] w-full resize-y rounded-md border p-3 text-sm leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowImportDialog(false)}
              disabled={importing}
            >
              取消
            </Button>
            <Button
              onClick={runImport}
              disabled={importing || loadingImportTargets || !importText.trim()}
            >
              {importing ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <FileText className="mr-1 h-4 w-4" />
              )}
              导出
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showContextDialog}
        onClose={() => setShowContextDialog(false)}
        title="导入项目上下文"
      >
        <div className="max-h-[72vh] space-y-4 overflow-auto pr-1">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setContextSource('novel_content')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                contextSource === 'novel_content'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <BookOpen className="mb-2 h-4 w-4" />
              小说内容
            </button>
            <button
              type="button"
              onClick={() => setContextSource('characters')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                contextSource === 'characters'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Users className="mb-2 h-4 w-4" />
              人物信息
            </button>
            <button
              type="button"
              onClick={() => setContextSource('outline')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                contextSource === 'outline'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <FileText className="mb-2 h-4 w-4" />
              大纲
            </button>
            <button
              type="button"
              onClick={() => setContextSource('outline_volume')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                contextSource === 'outline_volume'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <Layers className="mb-2 h-4 w-4" />
              卷
            </button>
            <button
              type="button"
              onClick={() => setContextSource('outline_chapter')}
              className={`rounded-md border p-3 text-left text-sm transition-colors ${
                contextSource === 'outline_chapter'
                  ? 'border-blue-300 bg-blue-50 text-blue-700'
                  : 'border-gray-200 hover:bg-gray-50'
              }`}
            >
              <ListTree className="mb-2 h-4 w-4" />
              章节
            </button>
          </div>

          {loadingContextSources ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载项目上下文...
            </div>
          ) : (
            <div className="space-y-3">
              {contextSource === 'novel_content' && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    章节
                  </label>
                  <select
                    className="w-full rounded-md border px-3 py-2 text-sm"
                    value={selectedChapterId}
                    onChange={(e) => setSelectedChapterId(e.target.value)}
                  >
                    {chapters.map((chapter) => (
                      <option key={chapter.id} value={chapter.id}>
                        {chapter.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {(contextSource === 'outline' ||
                contextSource === 'outline_volume' ||
                contextSource === 'outline_chapter') && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    大纲
                  </label>
                  <select
                    className="w-full rounded-md border px-3 py-2 text-sm"
                    value={selectedOutlineId}
                    onChange={(e) => void handleOutlineChange(e.target.value)}
                  >
                    {outlines.map((outline) => (
                      <option key={outline.id} value={outline.id}>
                        {outline.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {contextSource === 'outline_volume' && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    卷
                  </label>
                  <select
                    className="w-full rounded-md border px-3 py-2 text-sm"
                    value={selectedVolumeId}
                    onChange={(e) => setSelectedVolumeId(e.target.value)}
                  >
                    {volumes.map((volume) => (
                      <option key={volume.id} value={volume.id}>
                        {volume.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {contextSource === 'outline_chapter' && (
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    章节
                  </label>
                  <select
                    className="w-full rounded-md border px-3 py-2 text-sm"
                    value={selectedOutlineChapterId}
                    onChange={(e) => setSelectedOutlineChapterId(e.target.value)}
                  >
                    {outlineChapters.map((chapter) => (
                      <option key={chapter.id} value={chapter.id}>
                        {chapter.title}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {contextSource === 'characters' && (
                <div className="rounded-md border bg-gray-50 px-3 py-2 text-sm text-gray-600">
                  将导入当前项目的全部人物信息，共 {characters.length} 人。
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowContextDialog(false)}
              disabled={loadingContextSources}
            >
              取消
            </Button>
            <Button
              onClick={importContextToDraft}
              disabled={loadingContextSources}
            >
              <FilePlus2 className="mr-1 h-4 w-4" />
              加入输入框
            </Button>
          </div>
        </div>
      </Modal>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto rounded-lg border px-4 py-2 text-sm shadow-lg ${
              toast.type === 'success'
                ? 'border-green-200 bg-green-50 text-green-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  )
}
