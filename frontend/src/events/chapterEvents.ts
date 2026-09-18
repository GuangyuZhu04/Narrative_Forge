export const CHAPTER_CONTENT_UPDATED_EVENT = 'chapter-content-updated'
export const CHAPTERS_CHANGED_EVENT = 'chapters-changed'

export interface ChapterContentUpdatedDetail {
  projectId: string
  chapterId: string
  content: string | null
  wordCount: number
}

export interface ChaptersChangedDetail {
  projectId: string
}

export const notifyChapterContentUpdated = (
  detail: ChapterContentUpdatedDetail
) => {
  window.dispatchEvent(
    new CustomEvent<ChapterContentUpdatedDetail>(
      CHAPTER_CONTENT_UPDATED_EVENT,
      { detail }
    )
  )
}

export const notifyChaptersChanged = (detail: ChaptersChangedDetail) => {
  window.dispatchEvent(
    new CustomEvent<ChaptersChangedDetail>(CHAPTERS_CHANGED_EVENT, { detail })
  )
}
