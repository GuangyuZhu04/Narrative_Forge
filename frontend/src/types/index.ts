export interface Project {
  id: string
  name: string
  description: string | null
  genre: string | null
  cover_url: string | null
  status: string
  word_count_target: number | null
  settings: string | null
  created_at: string
  updated_at: string
}

export interface Outline {
  id: string
  project_id: string
  title: string
  description: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface OutlineNode {
  id: string
  node_type: 'VOLUME' | 'CHAPTER' | 'SCENE' | 'PLOT_POINT' | 'KEY_EVENT'
  title: string
  summary: string | null
  sort_order: number
  metadata: Record<string, unknown> | null
  llm_generated: boolean
  children: OutlineNode[]
}

export interface Character {
  id: string
  project_id: string
  name: string
  aliases: string[] | null
  avatar_url: string | null
  basic_info: Record<string, unknown> | null
  personality: Record<string, unknown> | null
  growth_arc: Record<string, unknown> | null
  biography: string | null
  setting_collection: string | null
  notes: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CharacterRelationship {
  id: string
  project_id: string
  source_id: string
  target_id: string
  relationship_type: string
  description: string | null
  intensity: number
  start_chapter: string | null
  end_chapter: string | null
  metadata: Record<string, unknown> | null
  source_name: string | null
  target_name: string | null
}

export interface Scene {
  id: string
  project_id: string
  name: string
  location: string | null
  time: string | null
  atmosphere: string | null
  description: string | null
  details: string | null
  notes: string | null
  sort_order: number
  created_at: string
  updated_at: string
}

export interface Chapter {
  highlights?: import('@/features/reading/highlights').TextHighlight[]
  id: string
  project_id: string
  outline_node_id: string | null
  title: string
  content: string | null
  summary: string | null
  sort_order: number
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

export interface DiscussionMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  thinking_content?: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface DiscussionSession {
  id: string
  project_id: string
  title: string
  system_prompt: string | null
  created_at: string
  updated_at: string
}

export interface DiscussionSessionDetail extends DiscussionSession {
  messages: DiscussionMessage[]
}

export interface ChapterVersion {
  id: string
  chapter_id: string
  version_number: number
  word_count: number
  change_summary: string | null
  created_at: string
}

export interface LLMConfig {
  id: string
  provider: string
  api_key_encrypted: string
  base_url: string
  model_name: string
  default_params: Record<string, unknown> | null
  rate_limit: Record<string, unknown> | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SystemPromptSetting {
  key: string
  category: string
  title: string
  description: string
  value: string
  default_value: string
  effective_value: string
  is_custom: boolean
  value_type: 'text' | 'number'
  min_value: number | null
  max_value: number | null
  step: number | null
  integer_only: boolean
  updated_at: string | null
}

export interface NovelAgentStepResult {
  step: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  message: string
  current: number | null
  total: number | null
}

export interface NovelAgentWriteResponse {
  session_id: string | null
  project: Project
  outline: Outline
  characters: Character[]
  scenes: Scene[]
  chapters: Chapter[]
  written_chapters: Chapter[]
  blueprint: Record<string, unknown>
  steps: NovelAgentStepResult[]
}

export type NovelAgentSessionMode =
  | 'generate'
  | 'continue_edit'
  | 'chat_generate'

export interface NovelAgentChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  kind?: string
  created_at?: string
  metadata?: Record<string, unknown> | null
}

export interface NovelAgentChatOption {
  id: string
  label: string
  description: string
  recommended: boolean
  value: unknown
}

export interface NovelAgentChatQuestion {
  id: string
  header: string
  question: string
  options: NovelAgentChatOption[]
  allow_custom: boolean
  state_version: number
}

export interface NovelAgentChatAnswer {
  question_id: string
  option_id?: string
  custom_text?: string
}

export type NovelAgentChatArtifact = Record<string, unknown> & {
  id?: string
  kind?: string
  title?: string
  status?: string
  content?: string
  summary?: string
}

export interface NovelAgentChatExecution extends Record<string, unknown> {
  status?: string
  stage?: string
  label?: string
  message?: string
  current?: number
  total?: number
  percent?: number
}

export interface NovelAgentChatState {
  stage: string
  state_version: number
  messages: NovelAgentChatMessage[]
  pending_questions: NovelAgentChatQuestion[]
  artifacts: NovelAgentChatArtifact[]
  execution: NovelAgentChatExecution | null
}

export interface NovelAgentChatTurnRequest {
  session_id?: string
  llm_config_id: string
  message?: string
  answers?: NovelAgentChatAnswer[]
}

export interface NovelAgentContinueRequestPayload {
  llm_config_id: string
  instruction: string
  style_requirements: string | null
  max_actions: number
}

export interface NovelAgentSession {
  id: string
  project_id: string
  mode: NovelAgentSessionMode
  name: string
  status: string
  request_payload: Record<string, unknown> | null
  plan: Record<string, unknown> | null
  result: Record<string, unknown> | null
  steps: NovelAgentStepResult[] | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface NovelAgentContinueActionResult {
  index: number
  action: 'write' | 'polish'
  chapter_id: string
  chapter_title: string
  instruction: string
  status: string
  word_count: number
  content: string | null
  backup_version_id: string | null
  worker_session_id?: string
}

export interface NovelAgentContinuePlanAction {
  action: 'write' | 'polish'
  chapter_id: string
  chapter_title: string
  instruction: string
  style_requirements: string | null
  include_previous_chapter: boolean
  include_next_chapter: boolean
}

export interface NovelAgentContinuePlan {
  summary: string
  actions: NovelAgentContinuePlanAction[]
}

export interface NovelAgentContinueResult {
  session_id: string
  summary: string
  actions: NovelAgentContinueActionResult[]
}

export interface AnalysisReport {
  id: string
  project_id: string
  chapter_id: string | null
  chapter_title: string | null
  analysis_type: string
  status: string
  issues: Record<string, unknown>[] | null
  suggestions: unknown[] | null
  score: number | null
  created_at: string
  updated_at: string
}

export type AudiobookProvider =
  | 'openai_compatible'
  | 'comfyui'
  | 'custom_http'
  | 'custom_websocket'
  | 'minimax_async'
export type AudiobookScopeType = 'book' | 'volume' | 'chapter'
export type AudiobookJobStatus =
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface AudiobookConfig {
  id: string | null
  project_id: string
  provider: AudiobookProvider
  base_url: string
  api_key_configured: boolean
  model_name: string
  narrator_voice: string
  character_voices: Record<string, string>
  speed: number
  use_ffmpeg: boolean
  max_chars_per_segment: number
  request_timeout_seconds: number
  requests_per_minute: number
  comfyui_workflow: Record<string, unknown> | null
  custom_request: Record<string, unknown> | null
  created_at: string | null
  updated_at: string | null
}

export interface AudiobookApiSuggestion {
  provider: 'openai_compatible' | 'custom_http' | 'custom_websocket' | 'minimax_async'
  base_url: string
  model_name: string
  narrator_voice: string
  speed: number
  max_chars_per_segment: number
  request_timeout_seconds: number
  requests_per_minute: number
  custom_request: Record<string, unknown> | null
  warnings: string[]
}

export type AudiobookVoiceType =
  | 'system'
  | 'voice_cloning'
  | 'voice_generation'

export interface AudiobookVoice {
  voice_id: string
  voice_name: string | null
  description: string[]
  created_time: string | null
  voice_type: AudiobookVoiceType
  is_local_only: boolean
}

export interface AudiobookVoiceQueryResult {
  voices: AudiobookVoice[]
}

export interface AudiobookVoiceDesignResult {
  voice: AudiobookVoice
  trial_audio_base64: string
  trial_audio_content_type: string
}

export interface AudiobookVoiceDeleteResult {
  voice_id: string
  voice_type: Exclude<AudiobookVoiceType, 'system'>
  created_time: string | null
}

export interface AudiobookScopeItem {
  id: string
  title: string
  chapter_count: number
  outline_title: string | null
}

export interface AudiobookScopes {
  book_title: string
  book_chapter_count: number
  volumes: AudiobookScopeItem[]
  chapters: AudiobookScopeItem[]
}

export interface AudiobookArtifact {
  kind: 'combined' | 'chapter'
  filename: string
  download_filename: string | null
  title: string
  size_bytes: number
  chapter_id: string | null
}

export interface AudiobookSegmentTask {
  chapter_id: string
  chapter_index: number
  segment_index: number
  voice_id: string
  status: string
  task_id: string | null
  file_id: string | null
  pause_after_ms: number
  error_message: string | null
}

export interface AudiobookJob {
  id: string
  project_id: string
  config_id: string | null
  script_llm_config_id: string | null
  scope_type: AudiobookScopeType
  scope_id: string | null
  scope_title: string
  status: AudiobookJobStatus
  progress: number
  processed_chapters: number
  total_chapters: number
  current_chapter_title: string | null
  segment_tasks: AudiobookSegmentTask[]
  output_files: AudiobookArtifact[]
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  page_size: number
}
