export const CHAPTER_CONTENT_UPDATED_EVENT = 'chapter-content-updated'

export interface ChapterContentUpdatedDetail {
  projectId: string
  chapterId: string
  content: string | null
  wordCount: number
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
