export interface Project {
  id: string
  name: string
  description: string | null
  genre: string | null
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

export interface Chapter {
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

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  page_size: number
}
