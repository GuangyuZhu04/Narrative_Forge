import { create } from 'zustand'
import { chapterApi } from '@/services/api'
import type { Chapter, ChapterVersion } from '@/types'

interface ChapterState {
  chapters: Chapter[]
  currentChapter: Chapter | null
  versions: ChapterVersion[]
  loading: boolean
  fetchChapters: (projectId: string) => Promise<void>
  setCurrentChapter: (chapter: Chapter | null) => void
  createChapter: (projectId: string, data: Partial<Chapter>) => Promise<Chapter>
  updateChapter: (projectId: string, id: string, data: Partial<Chapter>) => Promise<void>
  deleteChapter: (projectId: string, id: string) => Promise<void>
  fetchVersions: (projectId: string, chapterId: string) => Promise<void>
  createVersion: (projectId: string, chapterId: string, changeSummary?: string) => Promise<void>
  compareVersions: (
    projectId: string,
    chapterId: string,
    v1: number,
    v2: number
  ) => Promise<Record<string, unknown>>
  aiAssist: (
    projectId: string,
    llmConfigId: string,
    chapterId: string,
    action: string,
    selection?: string,
    context?: string
  ) => Promise<{ content: string; action: string; tokens_used: number }>
}

export const useChapterStore = create<ChapterState>((set) => ({
  chapters: [],
  currentChapter: null,
  versions: [],
  loading: false,

  fetchChapters: async (projectId) => {
    set({ loading: true })
    try {
      const result = (await chapterApi.list(projectId)) as unknown as {
        data: Chapter[]
      }
      set({ chapters: result.data || [] })
    } finally {
      set({ loading: false })
    }
  },

  setCurrentChapter: (chapter) => set({ currentChapter: chapter }),

  createChapter: async (projectId, data) => {
    const chapter = (await chapterApi.create(
      projectId,
      data as Record<string, unknown>
    )) as unknown as Chapter
    set((s) => ({ chapters: [...s.chapters, chapter] }))
    return chapter
  },

  updateChapter: async (projectId, id, data) => {
    const updated = (await chapterApi.update(
      projectId,
      id,
      data as Record<string, unknown>
    )) as unknown as Chapter
    set((s) => ({
      chapters: s.chapters.map((c) => (c.id === id ? updated : c)),
      currentChapter: s.currentChapter?.id === id ? updated : s.currentChapter,
    }))
  },

  deleteChapter: async (projectId, id) => {
    await chapterApi.delete(projectId, id)
    set((s) => ({
      chapters: s.chapters.filter((c) => c.id !== id),
      currentChapter: s.currentChapter?.id === id ? null : s.currentChapter,
    }))
  },

  fetchVersions: async (projectId, chapterId) => {
    const result = (await chapterApi.getVersions(projectId, chapterId)) as unknown as {
      data: ChapterVersion[]
    }
    set({ versions: result.data || [] })
  },

  createVersion: async (projectId, chapterId, changeSummary) => {
    const version = (await chapterApi.createVersion(
      projectId,
      chapterId,
      changeSummary
    )) as unknown as ChapterVersion
    set((s) => ({ versions: [version, ...s.versions] }))
  },

  compareVersions: async (projectId, chapterId, v1, v2) => {
    return (await chapterApi.compareVersions(
      projectId,
      chapterId,
      v1,
      v2
    )) as unknown as Record<string, unknown>
  },

  aiAssist: async (projectId, llmConfigId, chapterId, action, selection, context) => {
    return (await chapterApi.aiAssist(
      projectId,
      llmConfigId,
      chapterId,
      action,
      selection,
      context
    )) as unknown as { content: string; action: string; tokens_used: number }
  },
}))
