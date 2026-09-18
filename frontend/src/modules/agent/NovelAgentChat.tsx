import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  FileText,
  Loader2,
  Menu,
  RefreshCw,
  Send,
  Settings,
  Sparkles,
  User,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import {
  getActiveLLMConfigId,
  llmConfigApi,
  novelAgentApi,
  setActiveLLMConfigId,
} from '@/services/api'
import type {
  LLMConfig,
  NovelAgentChatAnswer,
  NovelAgentChatArtifact,
  NovelAgentChatExecution,
  NovelAgentChatMessage,
  NovelAgentChatQuestion,
  NovelAgentChatState,
  NovelAgentSession,
} from '@/types'
import { readJsonSse } from '@/utils/jsonSse'
import {
  notifyChapterContentUpdated,
  notifyChaptersChanged,
} from '@/events/chapterEvents'
import { refreshProjectOutlineData } from '@/stores/outlineStore'
import { AgentSessionBar } from './AgentSessionBar'

const CHAT_MODE = 'chat_generate' as const
const CUSTOM_OPTION_ID = '__custom__'
const CHAT_SUBMIT_SHORTCUT_KEY = 'nwa_agent_chat_submit_shortcut'
const CHAT_MESSAGE_DRAFT_PREFIX = 'nwa_agent_chat_message_draft:'

type ChatSubmitShortcut = 'enter' | 'ctrl-enter'

const readChatSubmitShortcut = (): ChatSubmitShortcut => {
  try {
    return localStorage.getItem(CHAT_SUBMIT_SHORTCUT_KEY) === 'ctrl-enter'
      ? 'ctrl-enter'
      : 'enter'
  } catch {
    return 'enter'
  }
}

const persistChatSubmitShortcut = (shortcut: ChatSubmitShortcut) => {
  try {
    localStorage.setItem(CHAT_SUBMIT_SHORTCUT_KEY, shortcut)
  } catch {
    // A blocked localStorage must not prevent the shortcut from working now.
  }
}

const chatMessageDraftKey = (projectId: string) =>
  `${CHAT_MESSAGE_DRAFT_PREFIX}${encodeURIComponent(projectId)}`

const readChatMessageDraft = (projectId?: string): string => {
  if (!projectId) return ''
  try {
    return localStorage.getItem(chatMessageDraftKey(projectId)) || ''
  } catch {
    return ''
  }
}

const persistChatMessageDraft = (projectId: string, draft: string) => {
  try {
    const key = chatMessageDraftKey(projectId)
    if (draft) localStorage.setItem(key, draft)
    else localStorage.removeItem(key)
  } catch {
    // Draft persistence is best-effort when browser storage is unavailable.
  }
}

const STAGES = [
  { key: 'intake', label: '构思', aliases: ['intake', 'idea', 'start'] },
  {
    key: 'outline',
    label: '大纲',
    aliases: ['outline', 'direction', 'foundation'],
  },
  { key: 'character', label: '人物', aliases: ['character', 'people'] },
  { key: 'scene', label: '场景', aliases: ['scene', 'setting'] },
  { key: 'chapter', label: '章节', aliases: ['chapter'] },
  {
    key: 'quality',
    label: '质量策略',
    aliases: ['quality', 'consistency', 'polish'],
  },
  {
    key: 'execution',
    label: '生成',
    aliases: [
      'plan',
      'confirm',
      'execut',
      'writing',
      'write_scope',
      'write',
      'structure',
      'create_',
      'update_',
    ],
  },
]

type QuestionSelection = {
  optionId: string
  customText: string
}

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null

const stringValue = (value: unknown): string =>
  typeof value === 'string' ? value : ''

const textValue = (value: unknown): string => stringValue(value).trim()

const STRUCTURED_PREVIEW_ROW_LIMIT = 5

const ARTIFACT_STAGE_LABELS: Record<string, string> = {
  foundation: '核心设定',
  outline_volume: '分卷大纲',
  outline: '大纲',
  characters: '人物',
  scenes: '场景',
  chapters: '章节',
  quality: '质量策略',
}

type StructuredContentRow = {
  key: string
  label: string
  value: string
}

const STRUCTURED_FIELD_LABELS: Record<string, string> = {
  'project.name': '项目名称',
  'project.description': '项目简介',
  'project.genre': '作品类型',
  'project.word_count_target': '目标字数',
  'project.settings.logline': '一句话梗概',
  'project.settings.core_promise': '核心承诺',
  'project.settings.theme': '故事主题',
  'project.settings.target_reader_experience': '阅读体验',
  'project.settings.central_conflict': '核心冲突',
  'outline.title': '大纲标题',
  'outline.description': '大纲说明',
  name: '名称',
  description: '简介',
  genre: '作品类型',
  word_count_target: '目标字数',
  logline: '一句话梗概',
  core_promise: '核心承诺',
  theme: '故事主题',
  target_reader_experience: '阅读体验',
  central_conflict: '核心冲突',
  world_rules: '世界规则',
  world_hard_rules: '世界规则',
  long_term_hooks: '长期伏笔',
  long_term_foreshadowing: '长期伏笔',
  ending_direction: '结局方向',
  narrative_rules: '叙事规则',
  continuity_rules: '连续性规则',
  forbidden_moves: '明确禁区',
  prohibited_areas: '明确禁区',
  style_guide: '创作规则手册',
  node_type: '内容类型',
  title: '标题',
  summary: '概要',
  role: '人物定位',
  aliases: '别名',
  age: '年龄',
  gender: '性别',
  appearance: '外貌',
  basic_info: '基础信息',
  personality: '性格',
  biography: '人物经历',
  desire: '核心欲望',
  fear: '核心恐惧',
  misbelief: '错误信念',
  motivation: '行动动机',
  action_logic: '行动逻辑',
  speech_style: '说话风格',
  relationship_tension: '关系张力',
  growth_arc: '成长弧',
  character_arc: '成长弧',
  setting_collection: '人物设定集',
  location: '地点',
  time: '时间',
  atmosphere: '氛围',
  details: '场景细节',
  notes: '备注',
  goal: '阶段目标',
  emotional_tone: '情绪基调',
  turning_point: '关键转折',
  promise: '叙事承诺',
  opening_state: '开场状态',
  closing_state: '结束状态',
  must_reveal: '必须揭示',
  must_not_reveal: '暂不揭示',
  target_chars: '目标字数',
  volume_index: '所属分卷',
  pov: '叙事视角',
  scene_focus: '核心场景',
  characters: '出场人物',
  hook: '章末钩子',
  ordered_beats: '情节节拍',
  expected_state_deltas: '预期状态变化',
  consistency_analysis: '一致性分析',
  automatic_polish: '自动打磨',
  application_scope: '应用范围',
  target_chapter_count: '目标章节数',
}

const isArrayIndex = (value: string): boolean => /^\d+$/.test(value)

const readableFieldName = (value: string): string =>
  STRUCTURED_FIELD_LABELS[value] || value.replaceAll('_', ' ')

const structuredRowLabel = (path: string[]): string => {
  const semanticPath = path.filter((part) => !isArrayIndex(part))
  const exactPath = semanticPath.join('.')
  const fieldName = semanticPath[semanticPath.length - 1] || '内容'
  const baseLabel =
    STRUCTURED_FIELD_LABELS[exactPath] || readableFieldName(fieldName)
  const itemIndex = [...path].reverse().find(isArrayIndex)
  return itemIndex === undefined
    ? baseLabel
    : `${baseLabel} ${Number(itemIndex) + 1}`
}

const parseEmbeddedJson = (value: string): unknown => {
  const trimmed = value.trim()
  if (
    !(
      (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))
    )
  ) {
    return value
  }

  try {
    const parsed: unknown = JSON.parse(trimmed)
    return parsed !== null && typeof parsed === 'object' ? parsed : value
  } catch {
    return value
  }
}

const structuredDisplayValue = (value: unknown): string | null => {
  if (typeof value === 'string') return textValue(value) || null
  if (typeof value === 'number') {
    return Number.isFinite(value)
      ? new Intl.NumberFormat('zh-CN').format(value)
      : null
  }
  if (typeof value === 'boolean') return value ? '是' : '否'
  return null
}

const buildStructuredContentRows = (detail: unknown): StructuredContentRow[] => {
  const rows: StructuredContentRow[] = []

  const visit = (value: unknown, path: string[], depth: number) => {
    if (value === null || value === undefined || depth > 12) return

    if (typeof value === 'string') {
      const parsed = parseEmbeddedJson(value)
      if (parsed !== value) {
        visit(parsed, path, depth + 1)
        return
      }
    }

    if (Array.isArray(value)) {
      value.forEach((item, index) =>
        visit(item, [...path, String(index)], depth + 1)
      )
      return
    }

    const record = asRecord(value)
    if (record) {
      Object.entries(record).forEach(([key, item]) =>
        visit(item, [...path, key], depth + 1)
      )
      return
    }

    const displayValue = structuredDisplayValue(value)
    if (!displayValue) return
    rows.push({
      key: path.join('.') || `content-${rows.length}`,
      label: structuredRowLabel(path),
      value: displayValue,
    })
  }

  visit(detail, [], 0)

  const seen = new Set<string>()
  return rows.filter((row) => {
    const signature = `${row.label}\u0000${row.value}`
    if (seen.has(signature)) return false
    seen.add(signature)
    return true
  })
}

const artifactStageValue = (artifact: NovelAgentChatArtifact): string =>
  (textValue(artifact.stage) || textValue(artifact.kind)).toLowerCase()

const artifactPreviewHeading = (stage: string): string =>
  `当前${ARTIFACT_STAGE_LABELS[stage] || '创作内容'}`

const chapterContractsFromArtifact = (
  detail: unknown
): Record<string, unknown>[] => {
  const chapters: Record<string, unknown>[] = []

  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    const record = asRecord(value)
    if (!record) return
    if (textValue(record.node_type).toUpperCase() === 'CHAPTER') {
      chapters.push(
        Object.fromEntries(
          Object.entries(record).filter(([key]) => key !== 'children')
        )
      )
      return
    }
    visit(record.children)
  }

  visit(detail)
  return chapters
}

const artifactPreviewDetail = (stage: string, detail: unknown): unknown => {
  const record = asRecord(detail)
  if (stage === 'foundation' && record) {
    const preview: Record<string, unknown> = {}
    if (record.project !== undefined) preview.project = record.project
    if (record.style_guide !== undefined) {
      preview.style_guide = record.style_guide
    }
    return Object.keys(preview).length > 0 ? preview : detail
  }
  if (stage === 'outline' && record?.outline !== undefined) {
    return record.outline
  }
  if (stage === 'chapters') {
    const chapters = chapterContractsFromArtifact(detail)
    return chapters.length > 0 ? chapters : detail
  }
  return detail
}

const numberValue = (value: unknown, fallback = 0): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback

const booleanValue = (value: unknown): boolean => value === true

const normalizeMessage = (
  value: unknown,
  fallbackId: string
): NovelAgentChatMessage | null => {
  if (typeof value === 'string') {
    return value.trim()
      ? { id: fallbackId, role: 'assistant', content: value }
      : null
  }

  const item = asRecord(value)
  if (!item) return null
  const rawRole = textValue(item.role)
  const role: NovelAgentChatMessage['role'] =
    rawRole === 'user' || rawRole === 'system' ? rawRole : 'assistant'
  const content = stringValue(item.content || item.text)
  if (!content.trim()) return null

  const metadata = asRecord(item.metadata)
  const payload = asRecord(item.payload)

  return {
    id: textValue(item.id) || fallbackId,
    role,
    content,
    kind: textValue(item.kind) || undefined,
    created_at: textValue(item.created_at) || undefined,
    metadata:
      metadata || payload
        ? { ...(metadata || {}), ...(payload || {}) }
        : null,
  }
}

const normalizeQuestion = (
  value: unknown,
  index: number,
  fallbackVersion = 0
): NovelAgentChatQuestion | null => {
  const item = asRecord(value)
  if (!item) return null

  const id = textValue(item.id) || `question-${fallbackVersion}-${index}`
  const question = textValue(item.question)
  if (!question) return null

  const rawOptions = Array.isArray(item.options) ? item.options : []
  const options = rawOptions.flatMap((rawOption, optionIndex) => {
    const option = asRecord(rawOption)
    if (!option) return []
    const optionId = textValue(option.id) || `${id}-option-${optionIndex}`
    const label = textValue(option.label)
    if (!label) return []
    return [
      {
        id: optionId,
        label,
        description: textValue(option.description),
        recommended: booleanValue(option.recommended),
        value: option.value,
      },
    ]
  })

  return {
    id,
    header: textValue(item.header) || '请确认创作方向',
    question,
    options,
    allow_custom: booleanValue(item.allow_custom),
    state_version: numberValue(item.state_version, fallbackVersion),
  }
}

const normalizeQuestions = (
  value: unknown,
  fallbackVersion = 0
): NovelAgentChatQuestion[] => {
  const values = Array.isArray(value) ? value : value ? [value] : []
  return values.flatMap((item, index) => {
    const question = normalizeQuestion(item, index, fallbackVersion)
    return question ? [question] : []
  })
}

const normalizeArtifacts = (value: unknown): NovelAgentChatArtifact[] => {
  const record = asRecord(value)
  const isStateArtifactMap =
    record &&
    !('data' in record) &&
    !('payload' in record) &&
    !('title' in record) &&
    !('kind' in record) &&
    !('stage' in record)
  const values = Array.isArray(value)
    ? value
    : isStateArtifactMap
      ? Object.entries(record).map(([stage, data]) => ({
          stage,
          kind: stage,
          title:
            stage === 'foundation'
              ? '核心设定与创作规则手册'
              : stage === 'outline'
                ? '完整分卷级大纲'
                : stage === 'characters'
                  ? '人物档案'
                  : stage === 'scenes'
                    ? '场景卡片'
                : stage === 'chapters'
                      ? '章节合同'
                      : stage === 'quality'
                        ? '质量策略'
                      : stage,
          data,
        }))
      : value
        ? [value]
        : []
  return values.flatMap((item) => {
    const artifact = asRecord(item)
    return artifact ? [artifact as NovelAgentChatArtifact] : []
  })
}

const emptyChatState = (): NovelAgentChatState => ({
  stage: 'intake',
  state_version: 0,
  messages: [],
  pending_questions: [],
  artifacts: [],
  execution: null,
})

const readSessionChatState = (session: NovelAgentSession): NovelAgentChatState => {
  const payload = asRecord(session.request_payload)
  const state = asRecord(payload?.chat_state)
  if (!state) return emptyChatState()

  const stateVersion = numberValue(state.state_version)
  const messages = Array.isArray(state.messages)
    ? state.messages.flatMap((item, index) => {
        const message = normalizeMessage(item, `restored-message-${index}`)
        return message ? [message] : []
      })
    : []
  const execution = asRecord(state.execution)
  const rawStage = textValue(state.stage) || 'intake'
  const inflightTurn = asRecord(state.inflight_turn)
  const resumeStage = textValue(inflightTurn?.resume_stage)
  let restoredArtifacts = normalizeArtifacts(state.artifacts)
  const qualityPolicy = asRecord(state.quality_policy)
  const hasQualityArtifact = restoredArtifacts.some(
    (artifact) => artifactStageValue(artifact) === 'quality'
  )
  if (
    qualityPolicy &&
    !hasQualityArtifact &&
    ['consistency', 'polish', 'approval_scope'].some(
      (key) => qualityPolicy[key] !== undefined
    )
  ) {
    const pendingChapterIds = Array.isArray(execution?.pending_chapter_ids)
      ? execution.pending_chapter_ids
      : []
    restoredArtifacts = mergeArtifacts(restoredArtifacts, [
      {
        stage: 'quality',
        kind: 'quality',
        title: '质量策略',
        data: {
          consistency_analysis: qualityPolicy.consistency ? '启用' : '关闭',
          automatic_polish: qualityPolicy.polish ? '启用' : '关闭',
          application_scope:
            qualityPolicy.approval_scope === 'each' ? '逐章确认' : '整批执行',
          target_chapter_count: numberValue(
            execution?.selected_count,
            pendingChapterIds.length
          ),
        },
      },
    ])
  }

  return {
    stage: rawStage === 'resume' && resumeStage ? resumeStage : rawStage,
    state_version: stateVersion,
    messages,
    pending_questions: normalizeQuestions(
      state.pending_questions,
      stateVersion
    ),
    artifacts: restoredArtifacts,
    execution: execution as NovelAgentChatExecution | null,
  }
}

const artifactKey = (artifact: NovelAgentChatArtifact): string => {
  const composite = [artifactStageValue(artifact), textValue(artifact.title)]
    .filter(Boolean)
    .join(':')
  return (
    textValue(artifact.id) ||
    textValue(artifact.artifact_id) ||
    composite ||
    JSON.stringify(artifact)
  )
}

const mergeArtifacts = (
  current: NovelAgentChatArtifact[],
  incoming: NovelAgentChatArtifact[]
): NovelAgentChatArtifact[] => {
  let merged = [...current]
  incoming.forEach((artifact) => {
    if (artifactStageValue(artifact) === 'outline') {
      merged = merged.filter(
        (item) => artifactStageValue(item) !== 'outline_volume'
      )
    }
    const key = artifactKey(artifact)
    const index = merged.findIndex((item) => artifactKey(item) === key)
    if (index === -1) merged.push(artifact)
    else merged[index] = { ...merged[index], ...artifact }
  })
  return merged
}

type ArtifactConversationPlacement = {
  afterMessage: Map<number, NovelAgentChatArtifact[]>
  fallback: NovelAgentChatArtifact[]
}

const placeArtifactsInConversation = (
  messages: NovelAgentChatMessage[],
  artifacts: NovelAgentChatArtifact[]
): ArtifactConversationPlacement => {
  const artifactByStage = new Map<string, NovelAgentChatArtifact>()
  artifacts.forEach((artifact) => {
    const stage = artifactStageValue(artifact)
    if (stage) artifactByStage.set(stage, artifact)
  })

  const lastPreviewIndexByStage = new Map<string, number>()
  messages.forEach((message, index) => {
    if (message.kind !== 'artifact_preview') return
    const stage = textValue(asRecord(message.metadata)?.artifact).toLowerCase()
    if (stage && artifactByStage.has(stage)) {
      lastPreviewIndexByStage.set(stage, index)
    }
  })

  const afterMessage = new Map<number, NovelAgentChatArtifact[]>()
  const anchoredKeys = new Set<string>()
  lastPreviewIndexByStage.forEach((messageIndex, stage) => {
    const artifact = artifactByStage.get(stage)
    if (!artifact) return
    const items = afterMessage.get(messageIndex) || []
    items.push(artifact)
    afterMessage.set(messageIndex, items)
    anchoredKeys.add(artifactKey(artifact))
  })

  return {
    afterMessage,
    fallback: artifacts.filter(
      (artifact) => !anchoredKeys.has(artifactKey(artifact))
    ),
  }
}

const appendMessage = (
  current: NovelAgentChatMessage[],
  incoming: NovelAgentChatMessage
): NovelAgentChatMessage[] => {
  if (incoming.id) {
    const index = current.findIndex((message) => message.id === incoming.id)
    if (index !== -1) {
      return current.map((message, messageIndex) =>
        messageIndex === index ? { ...message, ...incoming } : message
      )
    }
  }

  const last = current[current.length - 1]
  if (
    last &&
    last.role === incoming.role &&
    last.content === incoming.content
  ) {
    return current
  }
  return [...current, incoming]
}

const stageIndex = (stage: string, status?: string): number => {
  if (status === 'completed' || stage.toLowerCase().includes('complete')) {
    return STAGES.length
  }
  const normalized = stage.toLowerCase()
  const executionIndex = STAGES.findIndex((item) => item.key === 'execution')
  const executionStage = STAGES[executionIndex]
  if (executionStage.aliases.some((alias) => normalized.includes(alias))) {
    return executionIndex
  }
  const index = STAGES.findIndex((item) =>
    item.aliases.some((alias) => normalized.includes(alias))
  )
  return index === -1 ? 0 : index
}

const stageLabel = (stage: string): string => {
  if (stage.toLowerCase().includes('complete')) return '已完成'
  const index = stageIndex(stage)
  return STAGES[index]?.label || stage || '构思'
}

const displayTime = (value?: string): string => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const chatMessageAnchorId = (
  message: NovelAgentChatMessage,
  index: number
): string => `${message.id || 'chat-message'}:${index}`

const chatMessageRoleLabel = (role: NovelAgentChatMessage['role']): string => {
  if (role === 'user') return '我'
  if (role === 'system') return '系统'
  return 'AI'
}

const chatMessageRoleDotClass = (
  role: NovelAgentChatMessage['role']
): string => {
  if (role === 'user') return 'bg-blue-500'
  if (role === 'system') return 'bg-gray-400'
  return 'bg-emerald-500'
}

const chatMessageSnippet = (message: NovelAgentChatMessage): string => {
  const content = message.content.replace(/\s+/g, ' ').trim()
  const fallback = message.role === 'assistant' ? 'AI 正在回复...' : '空消息'
  return `${chatMessageRoleLabel(message.role)}：${content || fallback}`
}

const getLatestStepMessageTarget = (messages: NovelAgentChatMessage[]) => {
  let latestUserIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'user') {
      latestUserIndex = index
      break
    }
  }

  if (latestUserIndex >= 0) {
    const fallbackMessageId = chatMessageAnchorId(
      messages[latestUserIndex],
      latestUserIndex
    )
    for (
      let index = latestUserIndex + 1;
      index < messages.length;
      index += 1
    ) {
      if (messages[index].role !== 'user') {
        return {
          responseMessageId: chatMessageAnchorId(messages[index], index),
          fallbackMessageId,
        }
      }
    }
    return { responseMessageId: null, fallbackMessageId }
  }

  const fallbackIndex = messages.length - 1
  return {
    responseMessageId:
      fallbackIndex >= 0
        ? chatMessageAnchorId(messages[fallbackIndex], fallbackIndex)
        : null,
    fallbackMessageId: null,
  }
}

const errorDetail = (error: unknown, fallback: string): string => {
  const response = asRecord(asRecord(error)?.response)
  const data = asRecord(response?.data)
  const serverDetail = textValue(data?.detail)
  if (serverDetail) return serverDetail
  if (error instanceof Error && error.message) return error.message
  return fallback
}

const responseError = async (response: Response): Promise<string> => {
  const payload = (await response.json().catch(() => null)) as unknown
  return (
    textValue(asRecord(payload)?.detail) ||
    `对话创作请求失败（${response.status}）`
  )
}

const StageTracker: React.FC<{
  stage: string
  status?: string
}> = ({ stage, status }) => {
  const activeIndex = stageIndex(stage, status)
  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-[650px] items-center gap-1.5">
        {STAGES.map((item, index) => {
          const completed = index < activeIndex
          const active = index === activeIndex
          return (
            <React.Fragment key={item.key}>
              {index > 0 && (
                <div
                  className={`h-px min-w-3 flex-1 ${
                    completed || active ? 'bg-blue-300' : 'bg-gray-200'
                  }`}
                />
              )}
              <div
                className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                  completed
                    ? 'bg-blue-50 text-blue-700'
                    : active
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'bg-gray-100 text-gray-400'
                }`}
              >
                {completed ? (
                  <Check className="h-3.5 w-3.5" />
                ) : (
                  <Circle className="h-3 w-3" />
                )}
                {item.label}
              </div>
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}

const ChatBubble: React.FC<{ message: NovelAgentChatMessage }> = ({
  message,
}) => {
  if (message.role === 'system') {
    return (
      <div className="mx-auto max-w-2xl rounded-full bg-gray-100 px-4 py-1.5 text-center text-xs text-gray-500">
        {message.content}
      </div>
    )
  }

  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
          <Bot className="h-4 w-4" />
        </div>
      )}
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 shadow-sm ${
          isUser
            ? 'rounded-br-md bg-blue-600 text-white'
            : 'rounded-bl-md border border-gray-200 bg-white text-gray-800'
        }`}
      >
        {message.kind && !isUser && (
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-blue-500">
            {message.kind}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words text-sm leading-7">
          {message.content}
        </div>
        {displayTime(message.created_at) && (
          <div
            className={`mt-1 text-right text-[10px] ${
              isUser ? 'text-blue-100' : 'text-gray-400'
            }`}
          >
            {displayTime(message.created_at)}
          </div>
        )}
      </div>
      {isUser && (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-600">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  )
}

const ChatMessageIndexSidebar: React.FC<{
  messages: NovelAgentChatMessage[]
  activeMessageId: string | null
  onJump: (messageId: string) => void
}> = ({ messages, activeMessageId, onJump }) => {
  if (messages.length === 0) return null

  return (
    <nav
      aria-label="对话消息导航"
      className="group absolute bottom-3 right-3 top-3 z-20 flex w-12 max-w-[calc(100%_-_1.5rem)] justify-end overflow-visible transition-[width] duration-200 hover:w-96 focus-within:w-96"
    >
      <div className="flex h-full w-full overflow-hidden rounded-lg border border-gray-200 bg-white/95 shadow-lg backdrop-blur">
        <div className="flex w-12 shrink-0 flex-col items-center border-r border-gray-100 py-3">
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-md text-gray-600 transition-colors hover:bg-blue-50 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="展开对话消息导航"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="mt-3 flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
            {messages.slice(0, 18).map((message, index) => {
              const messageId = chatMessageAnchorId(message, index)
              return (
                <span
                  key={messageId}
                  aria-hidden="true"
                  className={`h-1.5 w-5 rounded-full ${
                    activeMessageId === messageId
                      ? 'ring-2 ring-blue-300 ring-offset-1'
                      : ''
                  } ${chatMessageRoleDotClass(message.role)}`}
                />
              )
            })}
          </div>
        </div>
        <div className="min-w-0 flex-1 overflow-hidden opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
          <div className="h-full overflow-auto p-2">
            {messages.map((message, index) => {
              const messageId = chatMessageAnchorId(message, index)
              const snippet = chatMessageSnippet(message)
              const active = activeMessageId === messageId
              return (
                <button
                  key={messageId}
                  type="button"
                  aria-current={active ? 'location' : undefined}
                  className={`flex h-9 w-full min-w-0 items-center rounded-md px-3 text-left text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                    active
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                  title={snippet}
                  onClick={() => onJump(messageId)}
                >
                  <span
                    aria-hidden="true"
                    className={`mr-2 h-2 w-2 shrink-0 rounded-full ${chatMessageRoleDotClass(
                      message.role
                    )}`}
                  />
                  <span className="truncate">{snippet}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </nav>
  )
}

const QuestionCard: React.FC<{
  question: NovelAgentChatQuestion
  selection?: QuestionSelection
  disabled: boolean
  onChange: (selection: QuestionSelection) => void
}> = ({ question, selection, disabled, onChange }) => (
  <fieldset
    disabled={disabled}
    className="rounded-xl border border-blue-200 bg-blue-50/60 p-4"
  >
    <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-blue-600">
      {question.header}
    </legend>
    <p className="mb-3 text-sm font-medium leading-6 text-gray-900">
      {question.question}
    </p>
    <div className="space-y-2">
      {question.options.map((option) => {
        const selected = selection?.optionId === option.id
        return (
          <label
            key={option.id}
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
              selected
                ? 'border-blue-500 bg-white ring-1 ring-blue-200'
                : 'border-gray-200 bg-white/80 hover:border-blue-300'
            }`}
          >
            <input
              type="radio"
              name={question.id}
              value={option.id}
              checked={selected}
              onChange={() =>
                onChange({ optionId: option.id, customText: '' })
              }
              className="mt-1 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-gray-800">
                {option.label}
                {option.recommended && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                    推荐
                  </span>
                )}
              </span>
              {option.description && (
                <span className="mt-1 block text-xs leading-5 text-gray-500">
                  {option.description}
                </span>
              )}
            </span>
          </label>
        )
      })}

      {question.allow_custom && (
        <label
          className={`block cursor-pointer rounded-lg border p-3 transition-colors ${
            selection?.optionId === CUSTOM_OPTION_ID
              ? 'border-blue-500 bg-white ring-1 ring-blue-200'
              : 'border-gray-200 bg-white/80 hover:border-blue-300'
          }`}
        >
          <span className="flex items-center gap-3 text-sm font-medium text-gray-800">
            <input
              type="radio"
              name={question.id}
              value={CUSTOM_OPTION_ID}
              checked={selection?.optionId === CUSTOM_OPTION_ID}
              onChange={() =>
                onChange({
                  optionId: CUSTOM_OPTION_ID,
                  customText: selection?.customText || '',
                })
              }
              className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            自定义回答
          </span>
          <textarea
            rows={2}
            maxLength={4000}
            value={selection?.customText || ''}
            onFocus={() =>
              onChange({
                optionId: CUSTOM_OPTION_ID,
                customText: selection?.customText || '',
              })
            }
            onChange={(event) =>
              onChange({
                optionId: CUSTOM_OPTION_ID,
                customText: event.target.value,
              })
            }
            placeholder="写下你的选择或补充要求……"
            className="mt-2 w-full resize-y rounded-md border border-gray-200 bg-white px-3 py-2 text-sm leading-6 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </label>
      )}
    </div>
  </fieldset>
)

const ProgressCard: React.FC<{
  progress: NovelAgentChatExecution | null
}> = ({ progress }) => {
  if (!progress) return null

  const current = numberValue(progress?.current)
  const total = numberValue(progress?.total)
  const explicitPercent = numberValue(progress?.percent, -1)
  const percent =
    explicitPercent >= 0
      ? Math.min(100, Math.max(0, explicitPercent))
      : total > 0
        ? Math.min(100, Math.max(0, Math.round((current / total) * 100)))
        : null
  const status = textValue(progress?.status)
  const completed =
    status === 'completed' || (percent !== null && percent >= 100)
  const label =
    textValue(progress?.label) ||
    textValue(progress?.message) ||
    (completed ? '本阶段生成完成' : 'Agent 正在处理下一步……')

  return (
    <div
      className="rounded-xl border border-violet-200 bg-violet-50 p-4"
      aria-live="polite"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-violet-800">
        {completed ? (
          <CheckCircle2 className="h-4 w-4" />
        ) : (
          <Loader2 className="h-4 w-4 animate-spin" />
        )}
        <span className="min-w-0 flex-1">{label}</span>
        {percent !== null && <span className="text-xs">{percent}%</span>}
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        {...(percent !== null ? { 'aria-valuenow': percent } : {})}
        className="mt-3 h-2 overflow-hidden rounded-full bg-violet-100"
      >
        {percent !== null ? (
          <div
            className="h-full rounded-full bg-violet-500 transition-[width] duration-300"
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="h-full w-1/3 rounded-full bg-violet-500 motion-safe:animate-pulse" />
        )}
      </div>
      {total > 0 && (
        <div className="mt-1.5 text-right text-[11px] text-violet-500">
          {Math.min(current, total)} / {total}
        </div>
      )}
    </div>
  )
}

const StructuredArtifactPreview: React.FC<{
  detail: unknown
  heading: string
}> = ({ detail, heading }) => {
  const [expanded, setExpanded] = useState(false)
  const contentId = React.useId()
  const rows = useMemo(() => buildStructuredContentRows(detail), [detail])
  const visibleRows = expanded
    ? rows
    : rows.slice(0, STRUCTURED_PREVIEW_ROW_LIMIT)
  const hasTruncatedValues = rows.some(
    (row) => row.value.length > 80 || row.value.includes('\n')
  )
  const canExpand =
    rows.length > STRUCTURED_PREVIEW_ROW_LIMIT || hasTruncatedValues
  const showFullValues = expanded || !canExpand

  if (rows.length === 0) return null

  return (
    <div className="mt-3 text-xs text-gray-600">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate font-medium text-gray-700">
          {heading}
        </span>
        <span className="shrink-0 whitespace-nowrap text-[11px] text-gray-400">
          已展示 {visibleRows.length}/{rows.length} 行
        </span>
      </div>
      <dl
        id={contentId}
        className="divide-y divide-gray-100 overflow-hidden rounded-md border border-gray-100 bg-gray-50/70"
      >
        {visibleRows.map((row) => (
          <div key={row.key} className="flex min-w-0 gap-2 px-2.5 py-1.5 leading-5">
            <dt
              className="w-24 shrink-0 truncate font-medium text-gray-500"
              title={row.label}
            >
              {row.label}
            </dt>
            <dd
              className={`min-w-0 flex-1 ${
                showFullValues
                  ? 'whitespace-pre-wrap break-words text-gray-700'
                  : 'truncate text-gray-600'
              }`}
              title={showFullValues ? undefined : row.value}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      {canExpand && (
        <div
          className={
            expanded
              ? 'sticky bottom-0 z-10 -mx-1 mt-2 flex bg-white px-1 py-2'
              : 'mt-2 flex'
          }
        >
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-blue-600 hover:bg-blue-50"
            aria-expanded={expanded}
            aria-controls={contentId}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? (
              <ChevronUp className="mr-1 h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="mr-1 h-3.5 w-3.5" />
            )}
            {expanded ? '收起' : '展开'}
          </Button>
        </div>
      )}
    </div>
  )
}

const ArtifactCard: React.FC<{ artifact: NovelAgentChatArtifact }> = ({
  artifact,
}) => {
  const title =
    textValue(artifact.title) ||
    textValue(artifact.name) ||
    textValue(artifact.kind) ||
    '创作产物'
  const content =
    textValue(artifact.summary) ||
    textValue(artifact.description) ||
    textValue(artifact.content)
  const detail = artifact.data ?? artifact.payload
  const artifactStage = artifactStageValue(artifact)
  const stageLabel =
    ARTIFACT_STAGE_LABELS[artifactStage] || textValue(artifact.kind)
  const previewSource = detail !== undefined ? detail : content
  const previewDetail = artifactPreviewDetail(artifactStage, previewSource)

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <div className="flex items-start gap-2">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-gray-800" title={title}>
            {title}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {stageLabel && (
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600">
                {stageLabel}
              </span>
            )}
            {textValue(artifact.status) && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                {textValue(artifact.status)}
              </span>
            )}
          </div>
          {previewSource !== undefined && (
            <StructuredArtifactPreview
              detail={previewDetail}
              heading={artifactPreviewHeading(artifactStage)}
            />
          )}
        </div>
      </div>
    </div>
  )
}

const ConversationArtifactCards: React.FC<{
  artifacts: NovelAgentChatArtifact[]
  onArtifactRef?: (key: string, element: HTMLDivElement | null) => void
}> = ({ artifacts, onArtifactRef }) => {
  if (artifacts.length === 0) return null

  return (
    <div className="flex items-start gap-3">
      <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 max-w-3xl flex-1 space-y-3">
        {artifacts.map((artifact) => {
          const key = artifactKey(artifact)
          return (
            <div
              key={key}
              ref={(element) => onArtifactRef?.(key, element)}
              className="scroll-mt-5"
            >
              <ArtifactCard artifact={artifact} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

export const NovelAgentChat: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<NovelAgentSession[]>([])
  const [activeSession, setActiveSession] = useState<NovelAgentSession | null>(
    null
  )
  const [llmConfigs, setLlmConfigs] = useState<LLMConfig[]>([])
  const [llmConfigId, setLlmConfigId] = useState('')
  const [stage, setStage] = useState('intake')
  const [stateVersion, setStateVersion] = useState(0)
  const [messages, setMessages] = useState<NovelAgentChatMessage[]>([])
  const [pendingQuestions, setPendingQuestions] = useState<
    NovelAgentChatQuestion[]
  >([])
  const [artifacts, setArtifacts] = useState<NovelAgentChatArtifact[]>([])
  const [execution, setExecution] = useState<NovelAgentChatExecution | null>(
    null
  )
  const [progress, setProgress] = useState<NovelAgentChatExecution | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [messageDraft, setMessageDraft] = useState(() =>
    readChatMessageDraft(projectId)
  )
  const [submitShortcut, setSubmitShortcut] =
    useState<ChatSubmitShortcut>(readChatSubmitShortcut)
  const [questionSelections, setQuestionSelections] = useState<
    Record<string, QuestionSelection>
  >({})
  const [loadingSession, setLoadingSession] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const [highlightedMessageId, setHighlightedMessageId] = useState<
    string | null
  >(null)
  const abortRef = useRef<AbortController | null>(null)
  const eventSequenceRef = useRef(0)
  const chatScrollRef = useRef<HTMLDivElement | null>(null)
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const artifactRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const latestStepQuestionsRef = useRef<HTMLDivElement | null>(null)
  const latestStepResultRef = useRef<HTMLDivElement | null>(null)
  const progressCardRef = useRef<HTMLDivElement | null>(null)
  const latestStepTailSpacerRef = useRef<HTMLDivElement | null>(null)
  const highlightTimeoutRef = useRef<number | null>(null)
  const pendingLatestStepFocusRef = useRef(true)
  const pendingLatestArtifactKeyRef = useRef<string | null>(null)
  const currentProjectIdRef = useRef(projectId)

  const setArtifactRef = useCallback(
    (key: string, element: HTMLDivElement | null) => {
      artifactRefs.current[key] = element
    },
    []
  )

  const clearLatestStepTailSpace = useCallback(() => {
    if (latestStepTailSpacerRef.current) {
      latestStepTailSpacerRef.current.style.height = '0px'
    }
  }, [])

  const cancelPendingLatestStepFocus = useCallback(() => {
    pendingLatestStepFocusRef.current = false
  }, [])

  const jumpToMessage = useCallback((messageId: string) => {
    const target = messageRefs.current[messageId]
    if (!target) return
    pendingLatestStepFocusRef.current = false
    if (highlightTimeoutRef.current !== null) {
      window.clearTimeout(highlightTimeoutRef.current)
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedMessageId(messageId)
    highlightTimeoutRef.current = window.setTimeout(() => {
      setHighlightedMessageId((current) =>
        current === messageId ? null : current
      )
      highlightTimeoutRef.current = null
    }, 1400)
  }, [])

  const resetChat = useCallback(() => {
    const empty = emptyChatState()
    setStage(empty.stage)
    setStateVersion(empty.state_version)
    setMessages(empty.messages)
    setPendingQuestions(empty.pending_questions)
    setArtifacts(empty.artifacts)
    setExecution(empty.execution)
    setProgress(null)
    setResult(null)
    setQuestionSelections({})
    artifactRefs.current = {}
    pendingLatestStepFocusRef.current = false
    pendingLatestArtifactKeyRef.current = null
    clearLatestStepTailSpace()
  }, [clearLatestStepTailSpace])

  const applySession = useCallback(
    (
      session: NovelAgentSession | null,
      options: { focusLatest?: boolean } = {}
    ) => {
      if (highlightTimeoutRef.current !== null) {
        window.clearTimeout(highlightTimeoutRef.current)
        highlightTimeoutRef.current = null
      }
      if (options.focusLatest !== false) {
        pendingLatestStepFocusRef.current = true
        pendingLatestArtifactKeyRef.current = null
        clearLatestStepTailSpace()
      }
      messageRefs.current = {}
      artifactRefs.current = {}
      setHighlightedMessageId(null)
      setActiveSession(session)
      setQuestionSelections({})
      setProgress(null)
      if (!session) {
        const empty = emptyChatState()
        setStage(empty.stage)
        setStateVersion(empty.state_version)
        setMessages(empty.messages)
        setPendingQuestions(empty.pending_questions)
        setArtifacts(empty.artifacts)
        setExecution(empty.execution)
        setResult(null)
        setError('')
        return
      }

      const chatState = readSessionChatState(session)
      setStage(chatState.stage)
      setStateVersion(chatState.state_version)
      setMessages(chatState.messages)
      setPendingQuestions(chatState.pending_questions)
      setArtifacts(chatState.artifacts)
      setExecution(chatState.execution)
      setResult(asRecord(session.result))
      setError(
        session.status === 'failed' ? textValue(session.error_message) : ''
      )
    },
    [clearLatestStepTailSpace]
  )

  const upsertSession = useCallback((session: NovelAgentSession) => {
    setSessions((current) => {
      const exists = current.some((item) => item.id === session.id)
      return exists
        ? current.map((item) => (item.id === session.id ? session : item))
        : [session, ...current]
    })
  }, [])

  const loadSession = useCallback(
    async (sessionId: string) => {
      if (!projectId) return
      setLoadingSession(true)
      try {
        const session = (await novelAgentApi.syncConfirmedArtifacts(
          projectId,
          sessionId
        )) as unknown as NovelAgentSession
        upsertSession(session)
        applySession(session)
      } catch (caught) {
        setError(errorDetail(caught, 'Agent 会话恢复失败'))
      } finally {
        setLoadingSession(false)
      }
    },
    [applySession, projectId, upsertSession]
  )

  const loadSessions = useCallback(
    async (preferredSessionId?: string) => {
      if (!projectId) return
      setLoadingSession(true)
      try {
        const response = (await novelAgentApi.listSessions(
          projectId,
          CHAT_MODE
        )) as unknown as { data: NovelAgentSession[] }
        const items = response.data || []
        setSessions(items)
        const selected = preferredSessionId
          ? items.find((session) => session.id === preferredSessionId)
          : items[0]
        const candidate = selected || items[0]
        if (!candidate) {
          applySession(null)
          return
        }
        const synced = (await novelAgentApi.syncConfirmedArtifacts(
          projectId,
          candidate.id
        )) as unknown as NovelAgentSession
        setSessions(
          items.map((session) =>
            session.id === synced.id ? synced : session
          )
        )
        applySession(synced)
      } catch (caught) {
        applySession(null)
        setError(errorDetail(caught, '对话创作会话加载失败'))
      } finally {
        setLoadingSession(false)
      }
    },
    [applySession, projectId]
  )

  const loadLlmConfigs = useCallback(async () => {
    try {
      const response = (await llmConfigApi.list()) as unknown as {
        data: LLMConfig[]
      }
      const configs = response.data || []
      setLlmConfigs(configs)
      const activeId = await getActiveLLMConfigId()
      const selected =
        configs.find((config) => config.id === activeId) ||
        configs.find((config) => config.is_active) ||
        configs[0]
      setLlmConfigId(selected?.id || '')
      if (selected) setActiveLLMConfigId(selected.id)
    } catch (caught) {
      setError(errorDetail(caught, 'LLM 配置加载失败'))
    }
  }, [])

  useEffect(() => {
    currentProjectIdRef.current = projectId
    const frame = window.requestAnimationFrame(() => {
      setMessageDraft(readChatMessageDraft(projectId))
    })
    return () => window.cancelAnimationFrame(frame)
  }, [projectId])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      resetChat()
      setSessions([])
      setActiveSession(null)
      setError('')
      void Promise.all([loadSessions(), loadLlmConfigs()])
    })
    return () => {
      window.cancelAnimationFrame(frame)
      abortRef.current?.abort()
      if (highlightTimeoutRef.current !== null) {
        window.clearTimeout(highlightTimeoutRef.current)
        highlightTimeoutRef.current = null
      }
    }
  }, [loadLlmConfigs, loadSessions, projectId, resetChat])

  const {
    responseMessageId: latestStepResponseMessageId,
    fallbackMessageId: latestStepFallbackMessageId,
  } = getLatestStepMessageTarget(messages)

  useEffect(() => {
    if (
      streaming ||
      loadingSession ||
      !pendingLatestStepFocusRef.current
    )
      return
    const frame = window.requestAnimationFrame(() => {
      if (!pendingLatestStepFocusRef.current) return
      const artifactTarget = pendingLatestArtifactKeyRef.current
        ? artifactRefs.current[pendingLatestArtifactKeyRef.current]
        : null
      const target =
        artifactTarget ||
        (latestStepResponseMessageId
          ? messageRefs.current[latestStepResponseMessageId]
          : pendingQuestions.length > 0
            ? latestStepQuestionsRef.current
            : result
              ? latestStepResultRef.current
              : latestStepFallbackMessageId
                ? messageRefs.current[latestStepFallbackMessageId]
                : null)
      if (!target) return
      if (
        artifactTarget &&
        chatScrollRef.current &&
        latestStepTailSpacerRef.current
      ) {
        latestStepTailSpacerRef.current.style.height = `${chatScrollRef.current.clientHeight}px`
      }
      pendingLatestStepFocusRef.current = false
      pendingLatestArtifactKeyRef.current = null
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [
    latestStepFallbackMessageId,
    latestStepResponseMessageId,
    loadingSession,
    pendingQuestions.length,
    result,
    streaming,
  ])

  const artifactPlacement = useMemo(
    () => placeArtifactsInConversation(messages, artifacts),
    [artifacts, messages]
  )

  useEffect(() => {
    if (!progress || !pendingLatestStepFocusRef.current) return
    const frame = window.requestAnimationFrame(() => {
      if (!pendingLatestStepFocusRef.current) return
      progressCardRef.current?.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [progress])

  const answersReady = useMemo(
    () =>
      pendingQuestions.length > 0 &&
      pendingQuestions.every((question) => {
        const selection = questionSelections[question.id]
        if (!selection?.optionId) return false
        return (
          selection.optionId !== CUSTOM_OPTION_ID ||
          Boolean(selection.customText.trim())
        )
      }),
    [pendingQuestions, questionSelections]
  )

  const submitTurn = async (payload: {
    message?: string
    answers?: NovelAgentChatAnswer[]
  }): Promise<boolean> => {
    if (!projectId || !llmConfigId || streaming) return false
    pendingLatestStepFocusRef.current = true
    pendingLatestArtifactKeyRef.current = null
    clearLatestStepTailSpace()
    setProgress(null)
    setStreaming(true)
    setError('')
    const controller = new AbortController()
    abortRef.current = controller
    let runSessionId = activeSession?.id || ''
    let streamDone = false

    try {
      const response = await novelAgentApi.chatTurnStream(
        projectId,
        {
          session_id: activeSession?.id || undefined,
          llm_config_id: llmConfigId,
          message: payload.message,
          answers: payload.answers,
        },
        controller.signal
      )
      if (!response.ok) throw new Error(await responseError(response))

      await readJsonSse(response, async (event) => {
        const eventType = textValue(event.type || event.event)
        const sessionRecord = asRecord(event.session)
        if (sessionRecord && textValue(sessionRecord.id)) {
          const session = sessionRecord as unknown as NovelAgentSession
          runSessionId = session.id
          setActiveSession(session)
          upsertSession(session)
        }

        if (eventType === 'message') {
          eventSequenceRef.current += 1
          const message = normalizeMessage(
            event.message,
            `stream-message-${eventSequenceRef.current}`
          )
          if (message) setMessages((current) => appendMessage(current, message))
        }

        if (eventType === 'question') {
          const hasQuestionList = Array.isArray(event.questions)
          const incoming = normalizeQuestions(
            hasQuestionList ? event.questions : event.question,
            stateVersion
          )
          if (incoming.length > 0) {
            const incomingVersion = Math.max(
              ...incoming.map((question) => question.state_version)
            )
            setStateVersion((current) => Math.max(current, incomingVersion))
            setPendingQuestions((current) => {
              if (hasQuestionList) return incoming
              const currentVersion = Math.max(
                0,
                ...current.map((question) => question.state_version)
              )
              if (incomingVersion > currentVersion) return incoming
              const merged = [...current]
              incoming.forEach((question) => {
                const index = merged.findIndex((item) => item.id === question.id)
                if (index === -1) merged.push(question)
                else merged[index] = question
              })
              return merged
            })
            setQuestionSelections({})
            setProgress(null)
          }
        }

        if (eventType === 'artifact') {
          const incoming = normalizeArtifacts(
            event.artifacts ?? event.artifact
          )
          if (incoming.length > 0) {
            pendingLatestArtifactKeyRef.current = artifactKey(
              incoming[incoming.length - 1]
            )
            setArtifacts((current) => mergeArtifacts(current, incoming))
          }
        }

        if (eventType === 'progress') {
          const progressRecord =
            asRecord(event.progress) ||
            ({
              status: event.status,
              stage: event.stage,
              label: event.label,
              message: event.message,
              current: event.current,
              total: event.total,
              percent: event.percent,
            } as Record<string, unknown>)
          const progress = progressRecord as NovelAgentChatExecution
          setProgress((current) => ({ ...(current || {}), ...progress }))
          const nextStage = textValue(progress.stage) || textValue(progress.step)
          if (nextStage) setStage(nextStage)
        }

        if (eventType === 'result') {
          const nextResult =
            asRecord(event.result) || { content: event.result ?? '' }
          setResult(nextResult)
          const resultKind = textValue(nextResult.kind)
          if (resultKind === 'structure') {
            notifyChaptersChanged({ projectId })
            void refreshProjectOutlineData(projectId).catch((caught: unknown) => {
              console.error('Failed to refresh chat-generated outline', caught)
            })
          } else if (resultKind === 'chapter') {
            const chapterId = textValue(nextResult.chapter_id)
            if (chapterId) {
              notifyChapterContentUpdated({
                projectId,
                chapterId,
                content:
                  typeof nextResult.content === 'string'
                    ? nextResult.content
                    : null,
                wordCount: numberValue(nextResult.word_count),
              })
            }
          }
        }

        if (eventType === 'error') {
          setProgress(null)
          throw new Error(
            textValue(event.error) ||
              textValue(event.message) ||
              '对话创作执行失败'
          )
        }

        if (eventType === 'done') streamDone = true
      })

      if (!streamDone) {
        throw new Error('对话创作流未正常结束，请重新同步会话后重试')
      }

      if (runSessionId) {
        const refreshed = (await novelAgentApi.getSession(
          projectId,
          runSessionId
        )) as unknown as NovelAgentSession
        upsertSession(refreshed)
        applySession(refreshed, { focusLatest: false })
      } else {
        await loadSessions()
      }
      setQuestionSelections({})
      return true
    } catch (caught) {
      pendingLatestStepFocusRef.current = false
      pendingLatestArtifactKeyRef.current = null
      setProgress(null)
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        return false
      }
      if (runSessionId) {
        try {
          const refreshed = (await novelAgentApi.getSession(
            projectId,
            runSessionId
          )) as unknown as NovelAgentSession
          upsertSession(refreshed)
          applySession(refreshed, { focusLatest: false })
        } catch {
          // Keep the original generation error when recovery refresh also fails.
        }
      }
      setError(errorDetail(caught, '对话创作失败，已尝试同步最近恢复检查点'))
      return false
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setStreaming(false)
    }
  }

  const handleSendMessage = async () => {
    const originalDraft = messageDraft
    const message = originalDraft.trim()
    if (!message || pendingQuestions.length > 0) return
    setMessageDraft('')
    const succeeded = await submitTurn({ message })
    if (succeeded && projectId) {
      persistChatMessageDraft(projectId, '')
    } else if (currentProjectIdRef.current === projectId) {
      setMessageDraft(originalDraft)
    }
  }

  const handleSubmitAnswers = async () => {
    if (!answersReady) return
    const answers = pendingQuestions.map((question) => {
      const selection = questionSelections[question.id]
      return selection.optionId === CUSTOM_OPTION_ID
        ? {
            question_id: question.id,
            custom_text: selection.customText.trim(),
          }
        : {
            question_id: question.id,
            option_id: selection.optionId,
          }
    })
    await submitTurn({ answers })
  }

  const handleCreateSession = async () => {
    if (!projectId || streaming) return
    setLoadingSession(true)
    try {
      const session = (await novelAgentApi.createSession(
        projectId,
        CHAT_MODE
      )) as unknown as NovelAgentSession
      upsertSession(session)
      applySession(session)
      setError('')
    } catch (caught) {
      setError(errorDetail(caught, '新建对话创作会话失败'))
    } finally {
      setLoadingSession(false)
    }
  }

  const handleRenameSession = async (name: string) => {
    if (!projectId || !activeSession) return
    const session = (await novelAgentApi.renameSession(
      projectId,
      activeSession.id,
      name
    )) as unknown as NovelAgentSession
    upsertSession(session)
    setActiveSession(session)
  }

  const handleDeleteSession = async () => {
    if (!projectId || !activeSession) return
    if (!window.confirm('删除该对话记录？已经写入项目的内容不会回滚。')) return
    setLoadingSession(true)
    try {
      await novelAgentApi.deleteSession(projectId, activeSession.id)
      const remaining = sessions.filter((session) => session.id !== activeSession.id)
      setSessions(remaining)
      if (remaining[0]) await loadSession(remaining[0].id)
      else applySession(null)
      setError('')
    } catch (caught) {
      setError(errorDetail(caught, '删除对话创作会话失败'))
    } finally {
      setLoadingSession(false)
    }
  }

  const handleRecover = async () => {
    if (activeSession) await loadSession(activeSession.id)
    else await loadSessions()
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }

  const busy = streaming || loadingSession
  const isInitialIdeaInput =
    !streaming &&
    (!activeSession || activeSession.status === 'idle') &&
    stage === 'intake' &&
    messages.length === 0 &&
    pendingQuestions.length === 0 &&
    artifacts.length === 0 &&
    !execution &&
    !result
  const chatCompleted =
    activeSession?.status === 'completed' ||
    stage.toLowerCase().includes('complete')
  const finalResultSummary =
    textValue(result?.summary) ||
    textValue(result?.message) ||
    textValue(result?.content) ||
    (numberValue(result?.completed_count) > 0
      ? `已完成 ${numberValue(result?.completed_count)} 章正文生成。`
      : '')
  const intermediateResultKind = textValue(result?.kind)
  const intermediateResultTitle =
    intermediateResultKind === 'structure'
      ? '项目结构已写入'
      : intermediateResultKind === 'chapter'
        ? `章节《${textValue(result?.chapter_title) || '未命名章节'}》已生成`
        : '阶段结果已更新'
  const intermediateResultSummary =
    intermediateResultKind === 'structure'
      ? `已创建 ${numberValue(result?.chapter_count)} 个章节、${numberValue(result?.character_count)} 个人物和 ${numberValue(result?.scene_count)} 个场景。`
      : intermediateResultKind === 'chapter'
        ? [
            numberValue(result?.word_count) > 0
              ? `${numberValue(result?.word_count)} 字`
              : '',
            result?.consistency_analyzed === true ? '已完成一致性分析' : '',
            result?.auto_polished === true ? '已自动打磨' : '',
          ]
            .filter(Boolean)
            .join(' · ')
        : textValue(result?.summary) || textValue(result?.message)

  return (
    <div className="app-wallpaper-canvas flex h-full min-h-0 flex-col bg-gray-50">
      <header className="app-wallpaper-surface border-b bg-white px-4 py-3 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-blue-600" />
              <h1 className="text-lg font-semibold text-gray-900">对话创作</h1>
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-600">
                {stageLabel(stage)} · v{stateVersion}
              </span>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              通过问答依次确定大纲、人物、场景、章节与一致性打磨策略。
            </p>
          </div>
          <div className="flex min-w-[280px] items-center gap-2">
            <select
              aria-label="创作模型"
              value={llmConfigId}
              disabled={busy || llmConfigs.length === 0}
              onChange={(event) => {
                setLlmConfigId(event.target.value)
                setActiveLLMConfigId(event.target.value || null)
              }}
              className="min-w-0 flex-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {llmConfigs.length === 0 && <option value="">暂无可用模型</option>}
              {llmConfigs.map((config) => (
                <option key={config.id} value={config.id}>
                  {config.provider} · {config.model_name}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              size="icon"
              title="配置模型"
              aria-label="配置模型"
              disabled={busy}
              onClick={() => navigate('/settings')}
            >
              <Settings className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="mt-3">
          <StageTracker stage={stage} status={activeSession?.status} />
        </div>
      </header>

      <div className="px-4 py-3">
        <AgentSessionBar
          className="app-wallpaper-surface"
          sessions={sessions}
          activeSession={activeSession}
          busy={busy}
          onSelect={(sessionId) => void loadSession(sessionId)}
          onCreate={() => void handleCreateSession()}
          onRename={handleRenameSession}
          onDelete={handleDeleteSession}
        />
      </div>

      {error && (
        <div className="mx-4 mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">{error}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void handleRecover()}
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            重新同步
          </Button>
          <button
            type="button"
            className="px-1 text-red-400 hover:text-red-700"
            onClick={() => setError('')}
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden px-4 pb-4">
        <section className="app-wallpaper-surface flex min-h-0 flex-col overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg shadow-gray-900/10">
          <div className="relative min-h-0 flex-1">
            {messages.length > 0 && !loadingSession && (
              <ChatMessageIndexSidebar
                messages={messages}
                activeMessageId={highlightedMessageId}
                onJump={jumpToMessage}
              />
            )}
            <div
              ref={chatScrollRef}
              className="h-full overflow-y-auto px-4 py-5 pr-20 sm:px-6 sm:pr-20"
              onKeyDown={cancelPendingLatestStepFocus}
              onPointerDown={cancelPendingLatestStepFocus}
              onTouchMove={cancelPendingLatestStepFocus}
              onWheel={cancelPendingLatestStepFocus}
            >
              <div className="mx-auto max-w-4xl space-y-5">
              {messages.length === 0 && !loadingSession && (
                <div className="rounded-2xl border border-dashed border-blue-200 bg-blue-50/40 px-6 py-10 text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                    <Bot className="h-6 w-6" />
                  </div>
                  <h2 className="mt-4 text-base font-semibold text-gray-900">
                    从一句灵感开始写长篇小说
                  </h2>
                  <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-gray-500">
                    告诉我题材、核心冲突或你已经有的设定。我会先和你确定大纲，再逐步确认人物、场景与章节范围，正式生成前还会询问一致性分析和自动打磨策略。
                  </p>
                </div>
              )}

              {messages.map((message, index) => {
                const messageId = chatMessageAnchorId(message, index)
                const messageArtifacts =
                  artifactPlacement.afterMessage.get(index) || []
                return (
                  <React.Fragment key={messageId}>
                    <div
                      ref={(element) => {
                        messageRefs.current[messageId] = element
                      }}
                      className={`scroll-mt-5 rounded-2xl transition-shadow duration-300 ${
                        highlightedMessageId === messageId
                          ? 'shadow-[0_0_0_3px_rgba(37,99,235,0.28)]'
                          : ''
                      }`}
                    >
                      <ChatBubble message={message} />
                    </div>
                    <ConversationArtifactCards
                      artifacts={messageArtifacts}
                      onArtifactRef={setArtifactRef}
                    />
                  </React.Fragment>
                )
              })}

              <ConversationArtifactCards
                artifacts={artifactPlacement.fallback}
                onArtifactRef={setArtifactRef}
              />

              {pendingQuestions.length > 0 && (
                <div
                  ref={latestStepQuestionsRef}
                  className="scroll-mt-5 space-y-4"
                >
                  {pendingQuestions.map((question) => (
                    <QuestionCard
                      key={`${question.id}:${question.state_version}`}
                      question={question}
                      selection={questionSelections[question.id]}
                      disabled={busy}
                      onChange={(selection) =>
                        setQuestionSelections((current) => ({
                          ...current,
                          [question.id]: selection,
                        }))
                      }
                    />
                  ))}
                  <div className="flex justify-end">
                    <Button
                      disabled={!answersReady || busy || !llmConfigId}
                      onClick={() => void handleSubmitAnswers()}
                    >
                      {streaming ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : (
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                      )}
                      提交{pendingQuestions.length > 1 ? `${pendingQuestions.length} 个` : ''}回答
                    </Button>
                  </div>
                </div>
              )}

              {progress && (
                <div ref={progressCardRef} className="scroll-mt-5">
                  <ProgressCard progress={progress} />
                </div>
              )}

              {result && !chatCompleted && (
                <div
                  ref={latestStepResultRef}
                  className="scroll-mt-5 rounded-xl border border-blue-200 bg-blue-50 p-4"
                >
                  <div className="flex items-center gap-2 font-medium text-blue-800">
                    <CheckCircle2 className="h-5 w-5" />
                    {intermediateResultTitle}
                  </div>
                  {intermediateResultSummary && (
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-blue-900">
                      {intermediateResultSummary}
                    </p>
                  )}
                </div>
              )}

              {chatCompleted && (
                <div
                  ref={latestStepResultRef}
                  className="scroll-mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4"
                >
                  <div className="flex items-center gap-2 font-medium text-emerald-800">
                    <CheckCircle2 className="h-5 w-5" />
                    本次创作已完成
                  </div>
                  {finalResultSummary && (
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-emerald-900">
                      {finalResultSummary}
                    </p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      onClick={() => navigate(`/projects/${projectId}/novel`)}
                    >
                      查看小说内容
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => navigate(`/projects/${projectId}/outline`)}
                    >
                      查看大纲
                    </Button>
                  </div>
                </div>
              )}
              <div
                ref={latestStepTailSpacerRef}
                aria-hidden="true"
                className="!mt-0 h-0"
              />
              </div>
            </div>
          </div>

          <div className="border-t border-white/60 bg-white/40 p-3 sm:p-4">
            {pendingQuestions.length > 0 && (
              <p className="mb-2 text-center text-xs text-blue-600">
                请先完成上方选项；需要自定义时可直接填写问题卡中的文本框。
              </p>
            )}
            <div className="mx-auto flex max-w-4xl items-end gap-2">
              <textarea
                rows={isInitialIdeaInput ? 6 : 1}
                maxLength={20000}
                value={messageDraft}
                disabled={busy || pendingQuestions.length > 0 || !llmConfigId}
                onChange={(event) => {
                  const draft = event.target.value
                  setMessageDraft(draft)
                  persistChatMessageDraft(projectId, draft)
                }}
                onKeyDown={(event) => {
                  if (
                    event.key !== 'Enter' ||
                    event.shiftKey ||
                    event.repeat ||
                    event.nativeEvent.isComposing
                  )
                    return
                  const hasSubmitModifier = event.ctrlKey || event.metaKey
                  const shouldSubmit =
                    submitShortcut === 'enter'
                      ? !hasSubmitModifier && !event.altKey
                      : hasSubmitModifier && !event.altKey
                  if (!shouldSubmit) return
                  event.preventDefault()
                  event.stopPropagation()
                  void handleSendMessage()
                }}
                placeholder={
                  pendingQuestions.length > 0
                    ? '请先回答上方问题'
                    : !llmConfigId
                      ? '请先配置创作模型'
                    : submitShortcut === 'enter'
                      ? '输入小说灵感或补充要求；回车发送，Shift + 回车换行'
                      : '输入小说灵感或补充要求；Ctrl/⌘ + 回车发送，Shift + 回车换行'
                }
                style={{ height: isInitialIdeaInput ? '168px' : '50px' }}
                className="min-h-[50px] min-w-0 flex-1 resize-y rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm leading-6 shadow-sm transition-[height] duration-200 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100 motion-reduce:transition-none"
              />
              <Button
                size="icon"
                className="h-11 w-11 shrink-0 rounded-xl"
                title="发送"
                aria-label="发送消息"
                disabled={
                  busy ||
                  pendingQuestions.length > 0 ||
                  !llmConfigId ||
                  !messageDraft.trim()
                }
                onClick={() => void handleSendMessage()}
              >
                {streaming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
            <div className="mx-auto mt-2 flex max-w-4xl flex-wrap items-center justify-end gap-2 text-xs text-gray-500">
              <span className="mr-auto">未发送内容自动暂存</span>
              <label htmlFor="agent-chat-submit-shortcut">发送快捷键</label>
              <select
                id="agent-chat-submit-shortcut"
                aria-label="发送快捷键"
                value={submitShortcut}
                disabled={busy}
                onChange={(event) => {
                  const shortcut = event.target.value as ChatSubmitShortcut
                  setSubmitShortcut(shortcut)
                  persistChatSubmitShortcut(shortcut)
                }}
                className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:bg-gray-100"
              >
                <option value="enter">回车</option>
                <option value="ctrl-enter">Ctrl/⌘ + 回车</option>
              </select>
              <span>Shift + 回车始终换行</span>
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
