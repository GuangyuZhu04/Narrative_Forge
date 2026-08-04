import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { useParams } from 'react-router-dom'
import { audiobookApi, characterApi, llmConfigApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Select } from '@/components/ui/Select'
import type {
  AudiobookConfig,
  AudiobookArtifact,
  AudiobookJob,
  AudiobookProvider,
  AudiobookScopes,
  AudiobookScopeType,
  AudiobookApiSuggestion,
  AudiobookVoice,
  AudiobookVoiceDesignResult,
  AudiobookVoiceQueryResult,
  AudiobookVoiceType,
  Character,
  LLMConfig,
} from '@/types'
import {
  Download,
  Headphones,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Square,
  Trash2,
  Volume2,
  WandSparkles,
} from 'lucide-react'

type Notice = { type: 'success' | 'error'; text: string }
type VoiceQueryType = AudiobookVoiceType | 'all'
const MINIMAX_ASYNC_MAX_TEXT_CHARS = 50_000
const DEFAULT_WEBSOCKET_REQUESTS_PER_MINUTE = 20
const MAX_WEBSOCKET_REQUESTS_PER_MINUTE = 120

interface AudiobookPanelProps {
  projectIdOverride?: string
  settingsOnly?: boolean
  embedded?: boolean
}

interface ConfigForm {
  provider: AudiobookProvider
  base_url: string
  api_key: string
  api_key_configured: boolean
  model_name: string
  narrator_voice: string
  character_voices: Record<string, string>
  speed: number
  use_ffmpeg: boolean
  max_chars_per_segment: number
  request_timeout_seconds: number
  requests_per_minute: number
  comfyui_workflow: string
  custom_request: string
}

const jobStatusLabel: Record<AudiobookJob['status'], string> = {
  queued: '等待中',
  processing: '生成中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function errorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.detail || error.message || fallback
  }
  return error instanceof Error ? error.message : fallback
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const voiceTypeLabel: Record<AudiobookVoiceType, string> = {
  system: '系统音色',
  voice_cloning: '快速复刻',
  voice_generation: '设计音色',
}

function voiceDisplayName(voice: AudiobookVoice) {
  return voice.voice_name ? `${voice.voice_name} · ${voice.voice_id}` : voice.voice_id
}

function isMiniMaxUrl(value: string) {
  try {
    const hostname = new URL(value).hostname.toLowerCase()
    return hostname.endsWith('minimaxi.com') || hostname.endsWith('minimax.io')
  } catch {
    return false
  }
}

function audioBlobFromBase64(value: string, contentType: string) {
  const binary = window.atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return new Blob([bytes], { type: contentType })
}

function toForm(config: AudiobookConfig): ConfigForm {
  return {
    provider: config.provider,
    base_url: config.base_url,
    api_key: '',
    api_key_configured: config.api_key_configured,
    model_name: config.model_name,
    narrator_voice: config.narrator_voice,
    character_voices: config.character_voices || {},
    speed: config.speed,
    use_ffmpeg: config.use_ffmpeg ?? true,
    max_chars_per_segment: config.max_chars_per_segment,
    request_timeout_seconds: config.request_timeout_seconds,
    requests_per_minute:
      config.requests_per_minute ?? DEFAULT_WEBSOCKET_REQUESTS_PER_MINUTE,
    comfyui_workflow: config.comfyui_workflow
      ? JSON.stringify(config.comfyui_workflow, null, 2)
      : '',
    custom_request: config.custom_request
      ? JSON.stringify(config.custom_request, null, 2)
      : '',
  }
}

export const AudiobookPanel: React.FC<AudiobookPanelProps> = ({
  projectIdOverride,
  settingsOnly = false,
  embedded = false,
}) => {
  const { projectId: routeProjectId } = useParams<{ projectId: string }>()
  const projectId = projectIdOverride || routeProjectId
  const [configId, setConfigId] = useState<string | null>(null)
  const [form, setForm] = useState<ConfigForm | null>(null)
  const [characters, setCharacters] = useState<Character[]>([])
  const [scopes, setScopes] = useState<AudiobookScopes | null>(null)
  const [jobs, setJobs] = useState<AudiobookJob[]>([])
  const [scopeType, setScopeType] = useState<AudiobookScopeType>('book')
  const [scopeId, setScopeId] = useState('')
  const [notice, setNotice] = useState<Notice | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savingCharacterVoices, setSavingCharacterVoices] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [llmConfigs, setLlmConfigs] = useState<LLMConfig[]>([])
  const [selectedLlmConfigId, setSelectedLlmConfigId] = useState('')
  const [apiDocumentation, setApiDocumentation] = useState('')
  const [parsingDocs, setParsingDocs] = useState(false)
  const [parseWarnings, setParseWarnings] = useState<string[]>([])
  const [voices, setVoices] = useState<AudiobookVoice[]>([])
  const [voiceQueryType, setVoiceQueryType] = useState<VoiceQueryType>('all')
  const [voiceSearch, setVoiceSearch] = useState('')
  const [loadingVoices, setLoadingVoices] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [hasQueriedVoices, setHasQueriedVoices] = useState(false)
  const [designPrompt, setDesignPrompt] = useState('')
  const [designPreviewText, setDesignPreviewText] = useState(
    '欢迎试听为这部小说设计的全新音色。'
  )
  const [designVoiceId, setDesignVoiceId] = useState('')
  const [designWatermark, setDesignWatermark] = useState(false)
  const [designingVoice, setDesigningVoice] = useState(false)
  const [designedTrialUrl, setDesignedTrialUrl] = useState<string | null>(null)
  const [deleteVoiceId, setDeleteVoiceId] = useState('')
  const [deleteVoiceType, setDeleteVoiceType] = useState<
    Exclude<AudiobookVoiceType, 'system'>
  >('voice_generation')
  const [deletingVoiceId, setDeletingVoiceId] = useState<string | null>(null)

  const loadJobs = useCallback(async () => {
    if (!projectId) return
    const response = (await audiobookApi.listJobs(projectId)) as unknown as {
      data: AudiobookJob[]
    }
    setJobs(response.data || [])
  }, [projectId])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    Promise.all([
      audiobookApi.getConfig(projectId),
      characterApi.list(projectId),
      settingsOnly ? Promise.resolve(null) : audiobookApi.getScopes(projectId),
      settingsOnly ? Promise.resolve(null) : audiobookApi.listJobs(projectId),
      llmConfigApi.list(),
    ])
      .then(([configValue, characterValue, scopeValue, jobValue, llmValue]) => {
        if (cancelled) return
        const config = configValue as unknown as AudiobookConfig
        const characterResponse = characterValue as unknown as { data: Character[] }
        const jobResponse = (jobValue || { data: [] }) as unknown as {
          data: AudiobookJob[]
        }
        const llmResponse = llmValue as unknown as { data: LLMConfig[] }
        const availableLlmConfigs = (llmResponse.data || []).filter(
          (item) => item.is_active
        )
        setConfigId(config.id)
        setForm(toForm(config))
        setVoices([])
        setHasQueriedVoices(false)
        setVoiceError(null)
        setCharacters(characterResponse.data || [])
        setScopes((scopeValue as unknown as AudiobookScopes | null) || null)
        setJobs(jobResponse.data || [])
        setLlmConfigs(availableLlmConfigs)
        const cachedLlmId = localStorage.getItem('nwa_active_llm_config_id')
        const preferredLlm =
          availableLlmConfigs.find((item) => item.id === cachedLlmId) ||
          availableLlmConfigs.find((item) => item.is_active) ||
          availableLlmConfigs[0]
        setSelectedLlmConfigId(preferredLlm?.id || '')
        if (
          config.id &&
          config.api_key_configured &&
          isMiniMaxUrl(config.base_url)
        ) {
          setLoadingVoices(true)
          audiobookApi
            .queryVoices(projectId, 'all')
            .then((value) => {
              if (cancelled) return
              const result = value as unknown as AudiobookVoiceQueryResult
              setVoices(result.voices || [])
              setHasQueriedVoices(true)
            })
            .catch((error) => {
              if (!cancelled) {
                setVoiceError(errorMessage(error, '查询 MiniMax 可用音色失败'))
              }
            })
            .finally(() => {
              if (!cancelled) setLoadingVoices(false)
            })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setNotice({ type: 'error', text: errorMessage(error, '加载有声书配置失败') })
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, settingsOnly])

  const hasActiveJobs = jobs.some((job) =>
    ['queued', 'processing'].includes(job.status)
  )

  useEffect(() => {
    if (!hasActiveJobs) return
    const timer = window.setInterval(() => {
      loadJobs().catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [hasActiveJobs, loadJobs])

  const scopeOptions = useMemo(() => {
    if (!scopes) return []
    return scopeType === 'volume' ? scopes.volumes : scopes.chapters
  }, [scopeType, scopes])

  const voiceById = useMemo(
    () => new Map(voices.map((voice) => [voice.voice_id, voice])),
    [voices]
  )

  const voiceOptions = useMemo(() => {
    const result = [...voices]
    const known = new Set(result.map((voice) => voice.voice_id))
    const selectedIds = [
      form?.narrator_voice,
      ...Object.values(form?.character_voices || {}),
    ]
    selectedIds.forEach((voiceId) => {
      if (voiceId && !known.has(voiceId)) {
        result.push({
          voice_id: voiceId,
          voice_name: null,
          description: [],
          created_time: null,
          voice_type: 'system',
          is_local_only: false,
        })
        known.add(voiceId)
      }
    })
    return result
  }, [form?.character_voices, form?.narrator_voice, voices])

  const filteredVoices = useMemo(() => {
    const keyword = voiceSearch.trim().toLowerCase()
    if (!keyword) return voices
    return voices.filter((voice) =>
      [voice.voice_id, voice.voice_name, ...voice.description]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword))
    )
  }, [voiceSearch, voices])

  const isMiniMaxConfig = useMemo(() => {
    return isMiniMaxUrl(form?.base_url || '')
  }, [form])

  useEffect(
    () => () => {
      if (designedTrialUrl) URL.revokeObjectURL(designedTrialUrl)
    },
    [designedTrialUrl]
  )

  const updateForm = <K extends keyof ConfigForm>(key: K, value: ConfigForm[K]) => {
    setForm((current) => (current ? { ...current, [key]: value } : current))
  }

  const selectProvider = (provider: AudiobookProvider) => {
    setForm((current) => {
      if (!current) return current
      if (provider === 'minimax_async' && current.provider !== 'minimax_async') {
        return {
          ...current,
          provider,
          base_url: 'https://api.minimaxi.com/v1',
          model_name: 'speech-2.8-hd',
          max_chars_per_segment: MINIMAX_ASYNC_MAX_TEXT_CHARS,
          request_timeout_seconds: 1800,
        }
      }
      return { ...current, provider }
    })
  }

  const loadVoices = async () => {
    if (!projectId || !configId) {
      setVoiceError('请先保存 MiniMax TTS 配置和 API Key')
      return
    }
    setLoadingVoices(true)
    setVoiceError(null)
    try {
      const result = (await audiobookApi.queryVoices(
        projectId,
        voiceQueryType
      )) as unknown as AudiobookVoiceQueryResult
      setVoices(result.voices || [])
      setHasQueriedVoices(true)
    } catch (error) {
      setVoiceError(errorMessage(error, '查询 MiniMax 可用音色失败'))
    } finally {
      setLoadingVoices(false)
    }
  }

  const createDesignedVoice = async () => {
    if (!projectId || !configId) {
      setVoiceError('请先保存 MiniMax TTS 配置和 API Key')
      return
    }
    if (!designPrompt.trim() || !designPreviewText.trim()) {
      setVoiceError('请填写音色描述和试听文本')
      return
    }
    setDesigningVoice(true)
    setVoiceError(null)
    try {
      const result = (await audiobookApi.designVoice(projectId, {
        prompt: designPrompt.trim(),
        preview_text: designPreviewText.trim(),
        voice_id: designVoiceId.trim() || null,
        aigc_watermark: designWatermark,
      })) as unknown as AudiobookVoiceDesignResult
      setVoices((current) => [
        result.voice,
        ...current.filter((voice) => voice.voice_id !== result.voice.voice_id),
      ])
      setDesignVoiceId(result.voice.voice_id)
      const trialUrl = URL.createObjectURL(
        audioBlobFromBase64(
          result.trial_audio_base64,
          result.trial_audio_content_type || 'audio/mpeg'
        )
      )
      setDesignedTrialUrl(trialUrl)
      setNotice({
        type: 'success',
        text: `音色 ${result.voice.voice_id} 已设计完成，可设为旁白或分配给人物。`,
      })
    } catch (error) {
      setVoiceError(errorMessage(error, 'MiniMax 音色设计失败'))
    } finally {
      setDesigningVoice(false)
    }
  }

  const removeVoice = async (
    requestedVoiceId?: string,
    requestedVoiceType?: Exclude<AudiobookVoiceType, 'system'>
  ) => {
    const voiceId = (requestedVoiceId || deleteVoiceId).trim()
    const voiceType = requestedVoiceType || deleteVoiceType
    if (!projectId || !configId) {
      setVoiceError('请先保存 MiniMax TTS 配置和 API Key')
      return
    }
    if (!voiceId) {
      setVoiceError('请输入要删除的 voice_id')
      return
    }
    const assigned =
      form?.narrator_voice === voiceId ||
      Object.values(form?.character_voices || {}).includes(voiceId)
    const assignmentWarning = assigned
      ? '\n当前配置仍在使用此音色，删除后请重新选择并保存旁白或人物音色。'
      : ''
    if (
      !window.confirm(
        `确认从 MiniMax 删除音色 ${voiceId}？删除后该 voice_id 将无法再次使用。${assignmentWarning}`
      )
    ) {
      return
    }
    setDeletingVoiceId(voiceId)
    setVoiceError(null)
    try {
      await audiobookApi.deleteVoice(projectId, voiceId, voiceType)
      setVoices((current) =>
        current.filter((voice) => voice.voice_id !== voiceId)
      )
      if (deleteVoiceId.trim() === voiceId) setDeleteVoiceId('')
      if (designVoiceId.trim() === voiceId) setDesignVoiceId('')
      await loadVoices()
      setNotice({
        type: 'success',
        text: `音色 ${voiceId} 已从 MiniMax 删除并重新同步列表。该 voice_id 不可再次使用，请换用新 ID。`,
      })
    } catch (error) {
      setVoiceError(errorMessage(error, '删除 MiniMax 音色失败'))
    } finally {
      setDeletingVoiceId(null)
    }
  }

  const saveConfig = async (event?: React.MouseEvent<HTMLButtonElement>) => {
    event?.preventDefault()
    event?.stopPropagation()
    if (!projectId || !form) return
    setSaving(true)
    setNotice(null)
    try {
      let workflow: Record<string, unknown> | null = null
      let customRequest: Record<string, unknown> | null = null
      if (form.provider === 'comfyui') {
        workflow = JSON.parse(form.comfyui_workflow) as Record<string, unknown>
      }
      if (['custom_http', 'custom_websocket'].includes(form.provider)) {
        customRequest = JSON.parse(form.custom_request) as Record<string, unknown>
      }
      const payload: Record<string, unknown> = {
        provider: form.provider,
        base_url: form.base_url,
        model_name: form.model_name,
        narrator_voice: form.narrator_voice,
        character_voices: form.character_voices,
        speed: form.speed,
        use_ffmpeg: form.use_ffmpeg,
        max_chars_per_segment: form.max_chars_per_segment,
        request_timeout_seconds: form.request_timeout_seconds,
        requests_per_minute: form.requests_per_minute,
        comfyui_workflow: workflow,
        custom_request: customRequest,
      }
      if (form.api_key) payload.api_key = form.api_key
      const saved = (await audiobookApi.updateConfig(
        projectId,
        payload
      )) as unknown as AudiobookConfig
      setConfigId(saved.id)
      setForm(toForm(saved))
      setNotice({ type: 'success', text: '有声书配置已保存' })
    } catch (error) {
      setNotice({
        type: 'error',
        text:
          error instanceof SyntaxError
            ? '工作流或自定义请求映射不是有效的 JSON'
            : errorMessage(error, '保存配置失败'),
      })
    } finally {
      setSaving(false)
    }
  }

  const saveCharacterVoices = async () => {
    if (!projectId || !form) return
    setSavingCharacterVoices(true)
    setNotice(null)
    try {
      const saved = (await audiobookApi.updateCharacterVoices(
        projectId,
        form.character_voices
      )) as unknown as AudiobookConfig
      setConfigId(saved.id)
      setForm((current) =>
        current
          ? { ...current, character_voices: saved.character_voices || {} }
          : current
      )
      setNotice({ type: 'success', text: '人物声音已保存' })
    } catch (error) {
      setNotice({
        type: 'error',
        text: errorMessage(error, '保存人物声音失败'),
      })
    } finally {
      setSavingCharacterVoices(false)
    }
  }

  const parseApiDocumentation = async () => {
    if (!projectId) return
    if (!selectedLlmConfigId) {
      setNotice({ type: 'error', text: '请先在系统设置中创建可用的 LLM 配置' })
      return
    }
    if (apiDocumentation.trim().length < 20) {
      setNotice({ type: 'error', text: '请粘贴较完整的语音 API 文档' })
      return
    }
    setParsingDocs(true)
    setNotice(null)
    setParseWarnings([])
    try {
      const suggestion = (await audiobookApi.parseDocs(
        projectId,
        selectedLlmConfigId,
        apiDocumentation
      )) as unknown as AudiobookApiSuggestion
      setForm((current) =>
        current
          ? {
              ...current,
              provider: suggestion.provider,
              base_url: suggestion.base_url,
              model_name: suggestion.model_name,
              narrator_voice: suggestion.narrator_voice,
              speed: suggestion.speed,
              max_chars_per_segment: suggestion.max_chars_per_segment,
              request_timeout_seconds: suggestion.request_timeout_seconds,
              requests_per_minute:
                suggestion.requests_per_minute ??
                DEFAULT_WEBSOCKET_REQUESTS_PER_MINUTE,
              custom_request: suggestion.custom_request
                ? JSON.stringify(suggestion.custom_request, null, 2)
                : '',
            }
          : current
      )
      setParseWarnings(suggestion.warnings || [])
      setNotice({
        type: 'success',
        text: 'API 文档解析完成。请检查自动填充结果、粘贴语音 API Key，然后保存并试听。',
      })
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error, '解析 API 文档失败') })
    } finally {
      setParsingDocs(false)
    }
  }

  const previewVoice = async () => {
    if (!projectId || !form) return
    if (!configId) {
      setNotice({ type: 'error', text: '请先保存配置再试听' })
      return
    }
    setPreviewing(true)
    setNotice(null)
    try {
      const blob = (await audiobookApi.preview(
        projectId,
        '欢迎使用文脉工坊有声书功能。',
        form.narrator_voice
      )) as unknown as Blob
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => URL.revokeObjectURL(url)
      audio.onerror = () => URL.revokeObjectURL(url)
      await audio.play()
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error, '试听失败') })
    } finally {
      setPreviewing(false)
    }
  }

  const createJob = async () => {
    if (!projectId || !configId) return
    if (!selectedLlmConfigId) {
      setNotice({
        type: 'error',
        text: '请先选择用于生成语音脚本 JSON 的 LLM',
      })
      return
    }
    if (scopeType !== 'book' && !scopeId) {
      setNotice({
        type: 'error',
        text: `请选择要生成的${scopeType === 'volume' ? '卷' : '章节'}`,
      })
      return
    }
    setCreating(true)
    setNotice(null)
    try {
      await audiobookApi.createJob(
        projectId,
        scopeType,
        scopeId || null,
        selectedLlmConfigId
      )
      await loadJobs()
      setNotice({
        type: 'success',
        text: '生成任务已创建：将先由 LLM 生成语音脚本 JSON，再调用语音模型。',
      })
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error, '创建任务失败') })
    } finally {
      setCreating(false)
    }
  }

  const cancelJob = async (jobId: string) => {
    if (!projectId) return
    try {
      await audiobookApi.cancelJob(projectId, jobId)
      await loadJobs()
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error, '取消任务失败') })
    }
  }

  const deleteJob = async (jobId: string) => {
    if (!projectId) return
    try {
      await audiobookApi.deleteJob(projectId, jobId)
      await loadJobs()
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error, '删除任务失败') })
    }
  }

  const downloadArtifact = (job: AudiobookJob, artifact: AudiobookArtifact) => {
    if (!projectId) return
    const anchor = document.createElement('a')
    anchor.href = audiobookApi.downloadUrl(projectId, job.id, artifact.filename)
    anchor.download = artifact.download_filename || artifact.filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }
  if (loading || !form) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-gray-500">
        <LoaderCircle className="h-5 w-5 animate-spin" /> 加载有声书配置...
      </div>
    )
  }

  return (
    <div className={embedded ? '' : 'min-h-full bg-gray-50'}>
      {!embedded && (
        <div className="border-b bg-white px-6 py-4">
          <div className="flex items-center gap-2">
            <Headphones className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-900">有声书生成</h2>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            为旁白和人物分配声音，生成全书、卷或章节的 MP3。
          </p>
        </div>
      )}

      <div
        className={
          embedded ? 'space-y-6' : 'mx-auto max-w-5xl space-y-6 p-6'
        }
      >
        {notice && (
          <div
            className={`rounded-md border px-4 py-3 text-sm ${
              notice.type === 'success'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-red-200 bg-red-50 text-red-700'
            }`}
          >
            {notice.text}
          </div>
        )}

        {settingsOnly && (
          <section className="space-y-3 rounded-lg border bg-white p-5 shadow-sm">
            <div>
              <h3 className="font-medium text-gray-900">音频后处理</h3>
              <p className="mt-1 text-xs leading-5 text-gray-500">
                此设置按项目保存，仅影响 MiniMax 异步多角色模式。
              </p>
            </div>
            <label className="flex cursor-pointer items-start gap-3 rounded-md border px-4 py-3">
              <input
                type="checkbox"
                checked={form.use_ffmpeg}
                onChange={(event) => updateForm('use_ffmpeg', event.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
              />
              <span>
                <span className="block text-sm font-medium text-gray-800">
                  启用 FFmpeg 高质量拼接（默认开启）
                </span>
                <span className="mt-1 block text-xs leading-5 text-gray-500">
                  开启后生成 WAV，并执行采样率与响度统一、角色切换停顿和一次性 MP3
                  编码；关闭后直接生成多个 MP3，按原顺序自动拼接，不要求安装 FFmpeg。
                </span>
              </span>
            </label>
          </section>
        )}

        <section className="space-y-5 rounded-lg border bg-white p-5 shadow-sm">
          <div>
            <h3 className="font-medium text-gray-900">1. TTS 服务</h3>
            <p className="mt-1 text-xs text-gray-500">
              OpenAI 兼容模式可连接云端 API，也可填写本地 vLLM/兼容服务的 /v1 地址。
            </p>
          </div>
          <div className="space-y-3 rounded-lg border border-blue-200 bg-blue-50/60 p-4">
            <div className="flex items-start gap-2">
              <WandSparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-blue-600" />
              <div>
                <h4 className="text-sm font-medium text-blue-900">
                  AI 自动接入语音 API
                </h4>
                <p className="mt-1 text-xs leading-5 text-blue-700">
                  复制语音服务的 API 文档，由现有 LLM 自动识别地址、请求字段和响应格式。API Key 不会交给 LLM，请在解析后自行粘贴。
                </p>
              </div>
            </div>
            <Select
              label="用于解析文档的 LLM"
              value={selectedLlmConfigId}
              onChange={(event) => setSelectedLlmConfigId(event.target.value)}
              options={
                llmConfigs.length
                  ? llmConfigs.map((item) => ({
                      value: item.id,
                      label: `${item.provider} · ${item.model_name}`,
                    }))
                  : [{ value: '', label: '请先到系统设置添加 LLM 配置' }]
              }
            />
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">
                语音 API 文档
              </label>
              <textarea
                className="h-44 w-full resize-y rounded-md border border-blue-200 bg-white p-3 text-xs leading-5 text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={apiDocumentation}
                onChange={(event) => setApiDocumentation(event.target.value)}
                placeholder="粘贴接口地址、鉴权方式、请求参数、响应示例和音色/模型说明……"
              />
            </div>
            <Button
              variant="outline"
              onClick={parseApiDocumentation}
              disabled={parsingDocs || !selectedLlmConfigId}
              className="border-blue-300 text-blue-700 hover:bg-blue-100"
            >
              <WandSparkles className="mr-2 h-4 w-4" />
              {parsingDocs ? 'LLM 正在解析文档...' : 'AI 解析并填充设置'}
            </Button>
            {parseWarnings.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                {parseWarnings.map((warning) => (
                  <p key={warning}>• {warning}</p>
                ))}
              </div>
            )}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Select
              label="服务类型"
              value={form.provider}
              onChange={(event) => selectProvider(event.target.value as AudiobookProvider)}
              options={[
                { value: 'openai_compatible', label: 'OpenAI 兼容 / vLLM' },
                {
                  value: 'minimax_async',
                  label: 'MiniMax 异步有声书（多角色）',
                },
                { value: 'custom_http', label: '自定义 HTTP API（AI 解析）' },
                {
                  value: 'custom_websocket',
                  label: '自定义 WebSocket API（AI 解析）',
                },
                { value: 'comfyui', label: 'ComfyUI API 工作流' },
              ]}
            />
            <Input
              label="服务地址"
              value={form.base_url}
              onChange={(event) => updateForm('base_url', event.target.value)}
              placeholder={
                form.provider === 'comfyui'
                  ? 'http://127.0.0.1:8188'
                  : form.provider === 'minimax_async'
                    ? 'https://api.minimaxi.com/v1'
                  : form.provider === 'custom_websocket'
                    ? 'wss://api.example.com/ws/tts'
                  : 'https://api.openai.com/v1'
              }
            />
            {form.provider !== 'comfyui' && (
              <>
                <Input
                  label="API Key（本地服务可留空）"
                  type="password"
                  value={form.api_key}
                  onChange={(event) => updateForm('api_key', event.target.value)}
                  placeholder={
                    form.api_key_configured ? '已配置；留空保持不变' : 'sk-...'
                  }
                />
                <Input
                  label="TTS 模型"
                  value={form.model_name}
                  onChange={(event) => updateForm('model_name', event.target.value)}
                  placeholder="tts-1"
                />
              </>
            )}
            <Input
              label="旁白声音 ID / 音色名"
              list="audiobook-voice-options"
              value={form.narrator_voice}
              onChange={(event) => updateForm('narrator_voice', event.target.value)}
              placeholder="alloy"
            />
            <Input
              label="语速"
              type="number"
              min="0.25"
              max="4"
              step="0.05"
              value={form.speed}
              onChange={(event) => updateForm('speed', Number(event.target.value))}
            />
            <div className="space-y-1">
              <Input
                label="单次请求最大字符数"
                type="number"
                min="100"
                max={MINIMAX_ASYNC_MAX_TEXT_CHARS}
                value={form.max_chars_per_segment}
                onChange={(event) =>
                  updateForm('max_chars_per_segment', Number(event.target.value))
                }
              />
              {form.provider === 'minimax_async' && (
                <p className="text-xs leading-5 text-gray-500">
                  MiniMax 异步接口直接传 text 时官方上限为 50,000 字符；更长文本需要文件上传，当前未使用该流程。
                </p>
              )}
            </div>
            <Input
              label="单次请求超时（秒）"
              type="number"
              min="10"
              max="1800"
              value={form.request_timeout_seconds}
              onChange={(event) =>
                updateForm('request_timeout_seconds', Number(event.target.value))
              }
            />
            {form.provider === 'custom_websocket' && (
              <div className="space-y-1">
                <Input
                  label="每分钟最大新连接数（RPM）"
                  type="number"
                  min="1"
                  max={MAX_WEBSOCKET_REQUESTS_PER_MINUTE}
                  step="1"
                  value={form.requests_per_minute}
                  onChange={(event) =>
                    updateForm('requests_per_minute', Number(event.target.value))
                  }
                />
                <p className="text-xs leading-5 text-gray-500">
                  默认 20，建议设置在 10–20。MiniMax 免费账户建议 10，充值账户建议 20；已申请提额时可按实际额度填写，允许范围为 1–120。
                </p>
              </div>
            )}
          </div>

          {form.provider === 'minimax_async' && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
              每个连续同音色片段会创建一个独立 MiniMax 异步任务，最多并发 4 个；
              {form.use_ffmpeg
                ? '当前启用 FFmpeg：下载 WAV 后统一响度和采样率、插入角色切换停顿，再编码为章节 MP3。运行后端的机器必须安装 FFmpeg。'
                : '当前已关闭 FFmpeg：MiniMax 直接生成 MP3，各片段按原顺序自动拼接；不会进行响度统一或插入额外停顿。'}
              推荐模型填写 <code>speech-2.8-hd</code>，任务超时设为 1800 秒。
            </div>
          )}

          {form.provider === 'comfyui' && (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">
                ComfyUI API 工作流 JSON
              </label>
              <textarea
                className="h-64 w-full rounded-md border border-gray-300 p-3 font-mono text-xs leading-5 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={form.comfyui_workflow}
                onChange={(event) => updateForm('comfyui_workflow', event.target.value)}
                placeholder={
                  '粘贴“保存（API 格式）”的工作流，并将输入替换为 {{text}}、音色替换为 {{voice}}。可选：{{speed}}、{{filename_prefix}}'
                }
              />
              <p className="text-xs text-gray-500">
                工作流必须包含 <code>{'{{text}}'}</code>，且最终输出 MP3；可使用
                <code> {'{{voice}}'}</code>、<code>{'{{speed}}'}</code> 和
                <code> {'{{filename_prefix}}'}</code>。
              </p>
            </div>
          )}

          {['custom_http', 'custom_websocket'].includes(form.provider) && (
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">
                自定义{form.provider === 'custom_websocket' ? ' WebSocket' : ' HTTP'}请求映射
              </label>
              <textarea
                className="h-64 w-full rounded-md border border-gray-300 p-3 font-mono text-xs leading-5 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={form.custom_request}
                onChange={(event) => updateForm('custom_request', event.target.value)}
                placeholder={'由 AI 根据 API 文档生成。必须包含 {{text}}，API Key 使用 {{api_key}}。'}
              />
              <p className="text-xs text-gray-500">
                {form.provider === 'custom_websocket'
                  ? '保存前请检查连接头、各阶段消息和响应路径。支持十六进制或 Base64 的 MP3 分块。'
                  : '保存前请对照文档检查请求字段。支持直接 MP3、JSON Base64 和 JSON 下载 URL 响应。'}
              </p>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              onClick={saveConfig}
              disabled={saving || savingCharacterVoices}
            >
              <Save className="mr-2 h-4 w-4" />
              {saving ? '保存中...' : '保存配置'}
            </Button>
            <Button
              variant="outline"
              onClick={previewVoice}
              disabled={previewing || !configId}
            >
              <Play className="mr-2 h-4 w-4" />
              {previewing ? '正在生成试听...' : '试听旁白'}
            </Button>
          </div>
        </section>

        <section className="space-y-5 rounded-lg border bg-white p-5 shadow-sm">
          <div>
            <h3 className="font-medium text-gray-900">2. MiniMax 音色库</h3>
            <p className="mt-1 text-xs text-gray-500">
              通过 MiniMax 官方接口查询、设计和删除音色。已设计但尚未正式调用的音色也会保留本地记录，刷新后仍可管理。
            </p>
          </div>

          {!configId && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              请先保存 TTS 配置和 API Key，再使用音色管理功能。
            </p>
          )}
          {configId && !isMiniMaxConfig && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              当前服务地址不是 MiniMax 官方域名。请先保存以 minimaxi.com 或 minimax.io 结尾的服务地址。
            </p>
          )}
          {voiceError && (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {voiceError}
            </p>
          )}

          <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <Select
              label="查询范围"
              value={voiceQueryType}
              onChange={(event) =>
                setVoiceQueryType(event.target.value as VoiceQueryType)
              }
              options={[
                { value: 'all', label: '全部音色' },
                { value: 'system', label: '系统音色' },
                { value: 'voice_cloning', label: '快速复刻音色' },
                { value: 'voice_generation', label: '设计生成音色' },
              ]}
            />
            <Button
              variant="outline"
              onClick={loadVoices}
              disabled={loadingVoices || !configId || !isMiniMaxConfig}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${loadingVoices ? 'animate-spin' : ''}`}
              />
              {loadingVoices ? '查询中...' : '查询可用音色'}
            </Button>
          </div>

          <div className="space-y-3 rounded-lg border border-violet-200 bg-violet-50/50 p-4">
            <div className="flex items-start gap-2">
              <Sparkles className="mt-0.5 h-4 w-4 flex-shrink-0 text-violet-600" />
              <div>
                <h4 className="text-sm font-medium text-violet-900">音色设计</h4>
                <p className="mt-1 text-xs leading-5 text-violet-700">
                  描述声音特征并填写试听文本。MiniMax 会返回新音色 ID 和试听音频；试听文本合成会按官方标准计费。
                  新音色成功用于一次正式语音合成后，才会出现在“设计生成音色”查询结果中。
                </p>
              </div>
            </div>
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">
                音色描述
              </label>
              <textarea
                className="h-24 w-full resize-y rounded-md border border-violet-200 bg-white p-3 text-sm focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                value={designPrompt}
                maxLength={2000}
                onChange={(event) => setDesignPrompt(event.target.value)}
                placeholder="例如：讲述悬疑故事的男播音员，声音低沉富有磁性，语速张弛有度。"
              />
            </div>
            <div className="space-y-1">
              <label className="block text-sm font-medium text-gray-700">
                试听文本（最多 500 字）
              </label>
              <textarea
                className="h-20 w-full resize-y rounded-md border border-violet-200 bg-white p-3 text-sm focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-500"
                value={designPreviewText}
                maxLength={500}
                onChange={(event) => setDesignPreviewText(event.target.value)}
              />
              <p className="text-right text-xs text-gray-400">
                {designPreviewText.length}/500
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Input
                label="自定义 voice_id（可选）"
                value={designVoiceId}
                maxLength={200}
                onChange={(event) => setDesignVoiceId(event.target.value)}
                placeholder="留空时由 MiniMax 自动生成"
              />
              <label className="flex items-center gap-2 self-end rounded-md border border-violet-200 bg-white px-3 py-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={designWatermark}
                  onChange={(event) => setDesignWatermark(event.target.checked)}
                />
                在试听音频末尾添加 AIGC 节奏标识
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                onClick={createDesignedVoice}
                disabled={designingVoice || !configId || !isMiniMaxConfig}
                className="bg-violet-600 hover:bg-violet-700"
              >
                <Sparkles className="mr-2 h-4 w-4" />
                {designingVoice ? '正在设计音色...' : '设计并生成试听'}
              </Button>
              {designedTrialUrl && (
                <audio
                  className="h-9 max-w-full"
                  controls
                  src={designedTrialUrl}
                  aria-label="设计音色试听"
                />
              )}
            </div>
          </div>

          <div className="space-y-3 rounded-lg border border-red-200 bg-red-50/50 p-4">
            <div className="flex items-start gap-2">
              <Trash2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600" />
              <div>
                <h4 className="text-sm font-medium text-red-900">按 ID 删除音色</h4>
                <p className="mt-1 text-xs leading-5 text-red-700">
                  可删除查询列表中的音色，也可在这里处理“查询不到但 ID 已占用”的历史音色。
                  MiniMax 规定删除后的 voice_id 无法再次使用。
                </p>
              </div>
            </div>
            <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
              <Input
                label="要删除的 voice_id"
                value={deleteVoiceId}
                maxLength={200}
                onChange={(event) => setDeleteVoiceId(event.target.value)}
                placeholder="粘贴已占用的 voice_id"
              />
              <Select
                label="音色类别"
                value={deleteVoiceType}
                onChange={(event) =>
                  setDeleteVoiceType(
                    event.target.value as Exclude<AudiobookVoiceType, 'system'>
                  )
                }
                options={[
                  { value: 'voice_generation', label: '设计生成音色' },
                  { value: 'voice_cloning', label: '快速复刻音色' },
                ]}
              />
              <Button
                variant="destructive"
                onClick={() => removeVoice()}
                disabled={
                  Boolean(deletingVoiceId) ||
                  !deleteVoiceId.trim() ||
                  !configId ||
                  !isMiniMaxConfig
                }
              >
                <Trash2 className="mr-2 h-4 w-4" />
                {deletingVoiceId === deleteVoiceId.trim() ? '删除中...' : '删除音色'}
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h4 className="text-sm font-medium text-gray-900">可用音色</h4>
                <p className="mt-1 text-xs text-gray-500">
                  {hasQueriedVoices || voices.length > 0
                    ? `当前显示 ${voices.length} 个音色`
                    : '点击“查询可用音色”从 MiniMax 加载列表'}
                </p>
              </div>
              <div className="relative w-full sm:w-72">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
                <input
                  className="w-full rounded-md border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={voiceSearch}
                  onChange={(event) => setVoiceSearch(event.target.value)}
                  placeholder="搜索名称、ID 或描述"
                />
              </div>
            </div>
            {filteredVoices.length > 0 ? (
              <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
                {filteredVoices.map((voice) => (
                  <div
                    key={voice.voice_id}
                    className="flex flex-wrap items-start justify-between gap-3 rounded-md border p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-gray-800">
                          {voice.voice_name || voice.voice_id}
                        </p>
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                          {voiceTypeLabel[voice.voice_type]}
                        </span>
                        {voice.is_local_only && (
                          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">
                            等待正式调用
                          </span>
                        )}
                      </div>
                      {voice.voice_name && (
                        <p className="mt-1 break-all font-mono text-xs text-gray-500">
                          {voice.voice_id}
                        </p>
                      )}
                      {voice.description.length > 0 && (
                        <p className="mt-1 text-xs leading-5 text-gray-500">
                          {voice.description.join('；')}
                        </p>
                      )}
                      {voice.created_time && (
                        <p className="mt-1 text-[11px] text-gray-400">
                          创建时间：{voice.created_time}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => updateForm('narrator_voice', voice.voice_id)}
                      >
                        设为旁白
                      </Button>
                      {voice.voice_type !== 'system' && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() =>
                            removeVoice(
                              voice.voice_id,
                              voice.voice_type as Exclude<
                                AudiobookVoiceType,
                                'system'
                              >
                            )
                          }
                          disabled={Boolean(deletingVoiceId)}
                        >
                          <Trash2 className="mr-1 h-3.5 w-3.5" />
                          {deletingVoiceId === voice.voice_id ? '删除中...' : '删除'}
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="rounded-md bg-gray-50 p-4 text-center text-sm text-gray-500">
                {hasQueriedVoices ? '没有匹配的音色' : '尚未查询音色'}
              </p>
            )}
          </div>

          <datalist id="audiobook-voice-options">
            {voiceOptions.map((voice) => (
              <option
                key={voice.voice_id}
                value={voice.voice_id}
                label={voiceDisplayName(voice)}
              />
            ))}
          </datalist>
        </section>

        <section className="space-y-4 rounded-lg border bg-white p-5 shadow-sm">
          <div>
            <h3 className="font-medium text-gray-900">3. 人物声音</h3>
            <p className="mt-1 text-xs text-gray-500">
              留空时使用旁白声音；系统会根据对白附近的“说、问、喊”等归属语句匹配人物。
            </p>
          </div>
          {characters.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {characters.map((character) => (
                <div
                  key={character.id}
                  className="flex items-center gap-3 rounded-md border p-3"
                >
                  <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-medium text-blue-600">
                    {character.name.slice(0, 1)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <label className="mb-1 block truncate text-sm font-medium text-gray-700">
                      {character.name}
                    </label>
                    {character.aliases && character.aliases.length > 0 && (
                      <p
                        className="mb-1 truncate text-[11px] text-gray-500"
                        title={character.aliases.join('、')}
                      >
                        别名：{character.aliases.join('、')}
                      </p>
                    )}
                    <input
                      className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      list="audiobook-voice-options"
                      value={form.character_voices[character.id] || ''}
                      onChange={(event) =>
                        updateForm('character_voices', {
                          ...form.character_voices,
                          [character.id]: event.target.value,
                        })
                      }
                      placeholder={`留空使用 ${form.narrator_voice}`}
                    />
                    {voiceById.get(form.character_voices[character.id] || '') && (
                      <p className="mt-1 truncate text-[11px] text-blue-600">
                        {voiceDisplayName(
                          voiceById.get(form.character_voices[character.id] || '')!
                        )}
                      </p>
                    )}
                    {character.aliases && character.aliases.length > 0 && (
                      <p className="mt-1 text-[11px] text-gray-400">
                        正式名和全部别名统一使用此音色
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-md bg-gray-50 p-3 text-sm text-gray-500">
              当前项目还没有人物，所有内容将使用旁白声音。
            </p>
          )}
          <div className="flex justify-end">
            <Button
              onClick={saveCharacterVoices}
              disabled={savingCharacterVoices || saving || !characters.length}
            >
              <Save className="mr-2 h-4 w-4" />
              {savingCharacterVoices ? '保存中...' : '人物声音保存'}
            </Button>
          </div>
        </section>

        {!settingsOnly && (
          <>
            <section className="space-y-4 rounded-lg border bg-white p-5 shadow-sm">
              <div>
                <h3 className="font-medium text-gray-900">4. 生成范围</h3>
                <p className="mt-1 text-xs text-gray-500">
                  任务先调用所选 LLM，将章节转换为经过校验的语音脚本 JSON；随后按旁白和人物音色调用 TTS。任务在后台执行，离开页面不会中断。
                </p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <Select
                  label="语音脚本 LLM"
                  value={selectedLlmConfigId}
                  onChange={(event) => setSelectedLlmConfigId(event.target.value)}
                  options={
                    llmConfigs.length
                      ? llmConfigs.map((item) => ({
                          value: item.id,
                          label: `${item.provider} · ${item.model_name}`,
                        }))
                      : [{ value: '', label: '请先到系统设置添加 LLM 配置' }]
                  }
                />
                <Select
                  label="范围"
                  value={scopeType}
                  onChange={(event) => {
                    setScopeType(event.target.value as AudiobookScopeType)
                    setScopeId('')
                  }}
                  options={[
                    {
                      value: 'book',
                      label: `全书（${scopes?.book_chapter_count || 0} 章）`,
                    },
                    { value: 'volume', label: '选定卷' },
                    { value: 'chapter', label: '选定章节' },
                  ]}
                />
                {scopeType !== 'book' && (
                  <Select
                    label={scopeType === 'volume' ? '选择卷' : '选择章节'}
                    value={scopeId}
                    onChange={(event) => setScopeId(event.target.value)}
                    options={[
                      {
                        value: '',
                        label: `请选择${scopeType === 'volume' ? '卷' : '章节'}`,
                      },
                      ...scopeOptions.map((item) => ({
                        value: item.id,
                        label: `${item.title}（${item.chapter_count} 章）`,
                      })),
                    ]}
                  />
                )}
              </div>
              <Button
                className="w-full"
                onClick={createJob}
                disabled={creating || !configId || !selectedLlmConfigId}
              >
                <Volume2 className="mr-2 h-4 w-4" />
                {creating ? '正在创建任务...' : '一键生成 MP3'}
              </Button>
              {!configId && (
                <p className="text-center text-xs text-amber-600">
                  保存 TTS 配置后即可生成
                </p>
              )}
              {configId && !selectedLlmConfigId && (
                <p className="text-center text-xs text-amber-600">
                  请选择语音脚本 LLM；章节会先转换为结构化 JSON，再提交给 TTS。
                </p>
              )}
            </section>

            <section className="space-y-4 rounded-lg border bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <h3 className="font-medium text-gray-900">生成记录</h3>
                {hasActiveJobs && (
                  <span className="flex items-center gap-1 text-xs text-blue-600">
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> 自动刷新
                  </span>
                )}
              </div>
              {!jobs.length ? (
                <p className="rounded-md bg-gray-50 p-4 text-center text-sm text-gray-500">
                  暂无生成记录
                </p>
              ) : (
                <div className="space-y-3">
                  {jobs.map((job) => {
                    const combined = job.output_files.find(
                      (file) => file.kind === 'combined'
                    )
                    const active = ['queued', 'processing'].includes(job.status)
                    return (
                      <div key={job.id} className="rounded-md border p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div>
                            <p className="font-medium text-gray-800">
                              {job.scope_title}
                            </p>
                            <p className="mt-1 text-xs text-gray-500">
                              {jobStatusLabel[job.status]} · {job.processed_chapters}/
                              {job.total_chapters} 章
                              {job.current_chapter_title
                                ? ` · ${job.current_chapter_title}`
                                : ''}
                            </p>
                            {(job.segment_tasks || []).length > 0 && (
                              <p className="mt-1 text-xs text-gray-500">
                                语音片段{' '}
                                {
                                  job.segment_tasks.filter(
                                    (segment) => segment.status === 'completed'
                                  ).length
                                }
                                /{job.segment_tasks.length}
                              </p>
                            )}
                          </div>
                          <div className="flex gap-2">
                            {combined && (
                              <Button
                                size="sm"
                                onClick={() => downloadArtifact(job, combined)}
                              >
                                <Download className="mr-1.5 h-3.5 w-3.5" />
                                下载 {formatBytes(combined.size_bytes)}
                              </Button>
                            )}
                            {active ? (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => cancelJob(job.id)}
                              >
                                <Square className="mr-1.5 h-3.5 w-3.5" />取消
                              </Button>
                            ) : (
                              <Button
                                variant="ghost"
                                size="icon"
                                title="删除记录和音频"
                                onClick={() => deleteJob(job.id)}
                              >
                                <Trash2 className="h-4 w-4 text-gray-500" />
                              </Button>
                            )}
                          </div>
                        </div>
                        {active && (
                          <div className="mt-3 h-2 overflow-hidden rounded-full bg-gray-100">
                            <div
                              className="h-full rounded-full bg-blue-500 transition-all"
                              style={{ width: `${job.progress}%` }}
                            />
                          </div>
                        )}
                        {job.status === 'failed' && job.error_message && (
                          <p className="mt-3 rounded bg-red-50 px-3 py-2 text-xs text-red-700">
                            {job.error_message}
                          </p>
                        )}
                        {job.status === 'completed' &&
                          job.output_files.length > 1 && (
                            <details className="mt-3 text-xs text-gray-600">
                              <summary className="cursor-pointer select-none">
                                下载单章音频
                              </summary>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {job.output_files
                                  .filter((file) => file.kind === 'chapter')
                                  .map((file) => (
                                    <button
                                      key={file.filename}
                                      className="rounded border bg-gray-50 px-2.5 py-1.5 hover:bg-gray-100"
                                      onClick={() => downloadArtifact(job, file)}
                                    >
                                      {file.title} · {formatBytes(file.size_bytes)}
                                    </button>
                                  ))}
                              </div>
                            </details>
                          )}
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
