import { readLocal } from './highlights'

export const READING_THEMES = ['paper', 'white', 'green', 'night'] as const
export interface ReadingSettings { theme: typeof READING_THEMES[number]; fontSize: number; lineHeight: number; width: number; font: 'serif' | 'sans'; mode: 'scroll' | 'page' }
export const DEFAULT_READING_SETTINGS: ReadingSettings = { theme: 'paper', fontSize: 20, lineHeight: 1.9, width: 760, font: 'serif', mode: 'scroll' }
export function clamp(value: number, min: number, max: number) { return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min)) }
export function loadReadingSettings(): ReadingSettings {
  const value = readLocal<Partial<ReadingSettings>>('nforge:reading-settings', {})
  return {
    theme: READING_THEMES.includes(value.theme!) ? value.theme! : 'paper',
    fontSize: clamp(value.fontSize ?? 20, 14, 32),
    lineHeight: clamp(value.lineHeight ?? 1.9, 1.4, 2.6),
    width: clamp(value.width ?? 760, 480, 1100),
    font: value.font === 'sans' ? 'sans' : 'serif',
    mode: value.mode === 'page' ? 'page' : 'scroll',
  }
}
export interface ReadingBookmark { id: string; chapterId: string; progress: number; excerpt: string; createdAt: number }
export interface ReadingHistory { chapterId: string; positions: Record<string, number>; bookmarks: ReadingBookmark[] }
export const historyKey = (projectId: string) => `nforge:reading-history:${projectId}`
export function loadReadingHistory(projectId: string): ReadingHistory {
  const value = readLocal<Partial<ReadingHistory>>(historyKey(projectId), {})
  return { chapterId: typeof value.chapterId === 'string' ? value.chapterId : '', positions: value.positions && typeof value.positions === 'object' ? value.positions : {}, bookmarks: Array.isArray(value.bookmarks) ? value.bookmarks : [] }
}
