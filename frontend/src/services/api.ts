import axios from 'axios'
import type {
  NovelAgentChatTurnRequest,
  NovelAgentSessionMode,
} from '@/types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API Error:', error.response?.data?.detail || error.message)
    return Promise.reject(error)
  }
)

export const projectApi = {
  list: (params?: Record<string, unknown>) => api.get('/projects', { params }),
  get: (id: string) => api.get(`/projects/${id}`),
  create: (data: Record<string, unknown>) => api.post('/projects', data),
  update: (id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${id}`, data),
  uploadCover: (id: string, file: File) =>
    api.put(`/projects/${id}/cover`, file, {
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
      },
    }),
  deleteCover: (id: string) => api.delete(`/projects/${id}/cover`),
  delete: (id: string) => api.delete(`/projects/${id}`),
}

export const outlineApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/outlines`),
  getTree: (projectId: string, id: string) =>
    api.get(`/projects/${projectId}/outlines/${id}/tree`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/outlines`, data),
  update: (projectId: string, outlineId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/outlines/${outlineId}`, data),
  generate: (projectId: string, llmConfigId: string, params: Record<string, string>) =>
    api.post(`/projects/${projectId}/outlines/generate`, {
      llm_config_id: llmConfigId,
      params,
    }),
  expandNode: (projectId: string, llmConfigId: string, nodeId: string, params: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/outlines/nodes/${nodeId}/expand`, {
      llm_config_id: llmConfigId,
      params,
    }, { timeout: 600000 }),
  optimize: (projectId: string, llmConfigId: string, outlineId: string, direction?: string) =>
    api.post(`/projects/${projectId}/outlines/${outlineId}/optimize`, {
      llm_config_id: llmConfigId,
      direction,
    }),
  structure: (projectId: string, llmConfigId: string, outlineId: string, params: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/outlines/${outlineId}/structure`, {
      llm_config_id: llmConfigId,
      params,
    }),
  addNode: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/outlines/nodes`, data),
  updateNode: (projectId: string, nodeId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/outlines/nodes/${nodeId}`, data),
  deleteNode: (projectId: string, nodeId: string) =>
    api.delete(`/projects/${projectId}/outlines/nodes/${nodeId}`),
  moveNode: (projectId: string, nodeId: string, newParentId: string | null, newOrder: number) =>
    api.put(`/projects/${projectId}/outlines/nodes/${nodeId}/move`, {
      new_parent_id: newParentId,
      new_order: newOrder,
    }),
}

export const characterApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/characters`),
  get: (projectId: string, id: string) =>
    api.get(`/projects/${projectId}/characters/${id}`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/characters`, data),
  update: (projectId: string, id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/characters/${id}`, data),
  uploadImage: (projectId: string, id: string, file: File) =>
    api.put(`/projects/${projectId}/characters/${id}/image`, file, {
      headers: {
        'Content-Type': file.type || 'application/octet-stream',
      },
    }),
  deleteImage: (projectId: string, id: string) =>
    api.delete(`/projects/${projectId}/characters/${id}/image`),
  delete: (projectId: string, id: string) =>
    api.delete(`/projects/${projectId}/characters/${id}`),
  move: (projectId: string, id: string, newOrder: number) =>
    api.put(`/projects/${projectId}/characters/${id}/move`, {
      new_order: newOrder,
    }),
  generateProfile: (projectId: string, llmConfigId: string, description: string) =>
    api.post(`/projects/${projectId}/characters/generate`, {
      llm_config_id: llmConfigId,
      description,
    }),
  importFromText: (projectId: string, llmConfigId: string, textContent: string) =>
    api.post(`/projects/${projectId}/characters/import`, {
      llm_config_id: llmConfigId,
      text_content: textContent,
    }),
  getRelationships: (projectId: string) =>
    api.get(`/projects/${projectId}/characters/relationships`),
  createRelationship: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/characters/relationships`, data),
  updateRelationship: (projectId: string, id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/characters/relationships/${id}`, data),
  deleteRelationship: (projectId: string, id: string) =>
    api.delete(`/projects/${projectId}/characters/relationships/${id}`),
}

export const sceneApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/scenes`),
  get: (projectId: string, id: string) =>
    api.get(`/projects/${projectId}/scenes/${id}`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/scenes`, data),
  update: (projectId: string, id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/scenes/${id}`, data),
  delete: (projectId: string, id: string) =>
    api.delete(`/projects/${projectId}/scenes/${id}`),
  move: (projectId: string, id: string, newOrder: number) =>
    api.put(`/projects/${projectId}/scenes/${id}/move`, {
      new_order: newOrder,
    }),
  importFromText: (projectId: string, llmConfigId: string, textContent: string) =>
    api.post(`/projects/${projectId}/scenes/import`, {
      llm_config_id: llmConfigId,
      text_content: textContent,
    }),
}

export const chapterApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/chapters`),
  get: (projectId: string, id: string) =>
    api.get(`/projects/${projectId}/chapters/${id}`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/chapters`, data),
  update: (projectId: string, id: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/chapters/${id}`, data),
  delete: (projectId: string, id: string) =>
    api.delete(`/projects/${projectId}/chapters/${id}`),
  getVersions: (projectId: string, chapterId: string) =>
    api.get(`/projects/${projectId}/chapters/${chapterId}/versions`),
  createVersion: (projectId: string, chapterId: string, changeSummary?: string) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/versions`, {
      change_summary: changeSummary,
    }),
  compareVersions: (projectId: string, chapterId: string, v1: number, v2: number) =>
    api.get(`/projects/${projectId}/chapters/${chapterId}/versions/compare`, {
      params: { v1, v2 },
    }),
  aiAssist: (
    projectId: string,
    llmConfigId: string,
    chapterId: string,
    action: string,
    selection?: string,
    context?: string
  ) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/ai-assist`, {
      llm_config_id: llmConfigId,
      action,
      selection,
      context,
    }),
  novelWrite: (
    projectId: string,
    llmConfigId: string,
    chapterId: string,
    styleRequirements?: string,
    writeContext?: Record<string, unknown>
  ) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/novel-write`, {
      llm_config_id: llmConfigId,
      style_requirements: styleRequirements || null,
      write_context: writeContext || null,
    }),
  getNovelWriteContext: (
    projectId: string,
    chapterId: string,
    styleRequirements?: string
  ) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/novel-write-context`, {
      style_requirements: styleRequirements || null,
    }),
  summarizeNovelWritePreviousContext: (
    projectId: string,
    chapterId: string,
    llmConfigId: string,
    styleRequirements?: string
  ) =>
    api.post(
      `/projects/${projectId}/chapters/${chapterId}/novel-write-context/summary`,
      {
        llm_config_id: llmConfigId,
        style_requirements: styleRequirements || null,
      }
    ),
  polish: (
    projectId: string,
    chapterId: string,
    llmConfigId: string,
    chapterContent: string,
    polishSuggestions: string,
    includePreviousChapter = false,
    includeNextChapter = false
  ) =>
    api.post(`/projects/${projectId}/chapters/${chapterId}/novel-polish`, {
      llm_config_id: llmConfigId,
      chapter_content: chapterContent,
      polish_suggestions: polishSuggestions,
      include_previous_chapter: includePreviousChapter,
      include_next_chapter: includeNextChapter,
    }),
}

export const novelAgentApi = {
  write: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/novel-agent/write`, data, {
      timeout: 900000,
    }),
  listSessions: (projectId: string, mode: NovelAgentSessionMode) =>
    api.get(`/projects/${projectId}/novel-agent/sessions`, {
      params: { mode },
    }),
  createSession: (
    projectId: string,
    mode: NovelAgentSessionMode,
    name?: string
  ) =>
    api.post(`/projects/${projectId}/novel-agent/sessions`, {
      mode,
      name: name || null,
    }),
  getSession: (projectId: string, sessionId: string) =>
    api.get(`/projects/${projectId}/novel-agent/sessions/${sessionId}`),
  syncConfirmedArtifacts: (projectId: string, sessionId: string) =>
    api.post(
      `/projects/${projectId}/novel-agent/sessions/${sessionId}/sync-confirmed-artifacts`
    ),
  renameSession: (projectId: string, sessionId: string, name: string) =>
    api.put(`/projects/${projectId}/novel-agent/sessions/${sessionId}`, {
      name,
    }),
  deleteSession: (projectId: string, sessionId: string) =>
    api.delete(`/projects/${projectId}/novel-agent/sessions/${sessionId}`),
  chatTurnStream: (
    projectId: string,
    data: NovelAgentChatTurnRequest,
    signal?: AbortSignal
  ) =>
    fetch(`/api/v1/projects/${projectId}/novel-agent/chat-turn-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal,
    }),
}

export const discussionApi = {
  list: (projectId: string) =>
    api.get(`/projects/${projectId}/discussions`),
  create: (projectId: string, data: Record<string, unknown>) =>
    api.post(`/projects/${projectId}/discussions`, data),
  get: (projectId: string, sessionId: string) =>
    api.get(`/projects/${projectId}/discussions/${sessionId}`),
  update: (projectId: string, sessionId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/discussions/${sessionId}`, data),
  delete: (projectId: string, sessionId: string) =>
    api.delete(`/projects/${projectId}/discussions/${sessionId}`),
  send: (
    projectId: string,
    sessionId: string,
    llmConfigId: string,
    content: string
  ) =>
    api.post(`/projects/${projectId}/discussions/${sessionId}/messages`, {
      llm_config_id: llmConfigId,
      content,
    }),
}

export const analysisApi = {
  getChapters: (projectId: string) =>
    api.get(`/projects/${projectId}/analysis/chapters`),
  analyze: (
    projectId: string,
    llmConfigId: string,
    chapterId: string,
    dimensions: string[]
  ) =>
    api.post(`/projects/${projectId}/analysis/consistency`, {
      llm_config_id: llmConfigId,
      chapter_id: chapterId,
      dimensions,
    }),
  streamAnalyze: (
    projectId: string,
    llmConfigId: string,
    chapterId: string,
    dimensions: string[]
  ) =>
    api.post(`/projects/${projectId}/analysis/consistency/stream`, {
      llm_config_id: llmConfigId,
      chapter_id: chapterId,
      dimensions,
    }),
  getReports: (projectId: string, chapterId?: string) =>
    api.get(`/projects/${projectId}/analysis/reports`, {
      params: { chapter_id: chapterId },
    }),
  getReport: (projectId: string, id: string) =>
    api.get(`/projects/${projectId}/analysis/reports/${id}`),
}

export const llmConfigApi = {
  list: () => api.get('/llm-configs'),
  get: (id: string) => api.get(`/llm-configs/${id}`),
  create: (data: Record<string, unknown>) => api.post('/llm-configs', data),
  update: (id: string, data: Record<string, unknown>) =>
    api.put(`/llm-configs/${id}`, data),
  delete: (id: string) => api.delete(`/llm-configs/${id}`),
  test: (id: string) => api.post(`/llm-configs/${id}/test`),
}

export const systemSettingsApi = {
  listPrompts: () => api.get('/system-settings/prompts'),
  updatePrompt: (key: string, value: string) =>
    api.put(`/system-settings/prompts/${encodeURIComponent(key)}`, { value }),
  resetPrompt: (key: string) =>
    api.post(`/system-settings/prompts/${encodeURIComponent(key)}/reset`),
}

const ACTIVE_LLM_KEY = 'nwa_active_llm_config_id'

export function setActiveLLMConfigId(configId: string | null): void {
  if (configId) {
    localStorage.setItem(ACTIVE_LLM_KEY, configId)
  } else {
    localStorage.removeItem(ACTIVE_LLM_KEY)
  }
}

export async function getActiveLLMConfigId(): Promise<string | null> {
  const cached = localStorage.getItem(ACTIVE_LLM_KEY)
  if (cached) return cached
  try {
    const result = (await llmConfigApi.list()) as unknown as {
      data: { id: string; is_active: boolean }[]
    }
    const configs = result.data || []
    const active = configs.find((c) => c.is_active)
    if (active) {
      localStorage.setItem(ACTIVE_LLM_KEY, active.id)
      return active.id
    }
  } catch {
    // Missing config is handled by callers prompting the user to configure LLM.
  }
  return null
}

export type PlatformExportTarget = 'fanqie' | 'qidian'

export interface PlatformExportPayload {
  platform: PlatformExportTarget
  platform_name: string
  target_url: string
  project_name: string
  chapter_count: number
  total_word_count: number
  clipboard_text: string
  chapters: {
    title: string
    content: string
    word_count: number
    sort_order: number
    status: string
  }[]
  warnings: string[]
}

export const exportApi = {
  exportProject: (
    projectId: string,
    format: string,
    options?: Record<string, unknown>
  ) =>
    api.post(
      `/projects/${projectId}/export`,
      { format, options },
      { responseType: 'blob' }
    ),
  exportToPlatform: (
    projectId: string,
    platform: PlatformExportTarget,
    options?: Record<string, unknown>
  ) =>
    api.post(`/projects/${projectId}/export/platform`, {
      platform,
      options,
    }),
}

export const audiobookApi = {
  getConfig: (projectId: string) =>
    api.get(`/projects/${projectId}/audiobook/config`),
  updateConfig: (projectId: string, data: Record<string, unknown>) =>
    api.put(`/projects/${projectId}/audiobook/config`, data),
  updateCharacterVoices: (
    projectId: string,
    characterVoices: Record<string, string>
  ) =>
    api.patch(`/projects/${projectId}/audiobook/config/character-voices`, {
      character_voices: characterVoices,
    }),
  parseDocs: (projectId: string, llmConfigId: string, apiDocumentation: string) =>
    api.post(`/projects/${projectId}/audiobook/config/parse-docs`, {
      llm_config_id: llmConfigId,
      api_documentation: apiDocumentation,
    }, { timeout: 600000 }),
  preview: (projectId: string, text: string, voice?: string) =>
    api.post(
      `/projects/${projectId}/audiobook/preview`,
      { text, voice: voice || null },
      { responseType: 'blob', timeout: 600000 }
    ),
  queryVoices: (projectId: string, voiceType: string) =>
    api.post(`/projects/${projectId}/audiobook/voices/query`, {
      voice_type: voiceType,
    }),
  designVoice: (
    projectId: string,
    data: {
      prompt: string
      preview_text: string
      voice_id?: string | null
      aigc_watermark: boolean
    }
  ) =>
    api.post(`/projects/${projectId}/audiobook/voices/design`, data, {
      timeout: 600000,
    }),
  deleteVoice: (
    projectId: string,
    voiceId: string,
    voiceType: 'voice_cloning' | 'voice_generation'
  ) =>
    api.post(`/projects/${projectId}/audiobook/voices/delete`, {
      voice_id: voiceId,
      voice_type: voiceType,
    }),
  getScopes: (projectId: string) =>
    api.get(`/projects/${projectId}/audiobook/scopes`),
  listJobs: (projectId: string) =>
    api.get(`/projects/${projectId}/audiobook/jobs`),
  createJob: (
    projectId: string,
    scopeType: string,
    scopeId: string | null,
    llmConfigId: string
  ) =>
    api.post(`/projects/${projectId}/audiobook/jobs`, {
      scope_type: scopeType,
      scope_id: scopeId || null,
      llm_config_id: llmConfigId,
    }),
  cancelJob: (projectId: string, jobId: string) =>
    api.post(`/projects/${projectId}/audiobook/jobs/${jobId}/cancel`),
  deleteJob: (projectId: string, jobId: string) =>
    api.delete(`/projects/${projectId}/audiobook/jobs/${jobId}`),
  downloadUrl: (projectId: string, jobId: string, filename: string) =>
    `/api/v1/projects/${encodeURIComponent(projectId)}/audiobook/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(filename)}`,
}
