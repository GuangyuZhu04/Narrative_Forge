import React, { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Button } from '@/components/ui/Button'
import { chapterApi, getActiveLLMConfigId } from '@/services/api'
import { debounce } from '@/utils/debounce'
import { Sparkles, Save, History } from 'lucide-react'

export const ChapterEditor: React.FC = () => {
  const { projectId, chapterId } = useParams<{
    projectId: string
    chapterId: string
  }>()
  const [chapter, setChapter] = useState<{
    id: string
    title: string
    content: string
  } | null>(null)
  const [showAi, setShowAi] = useState(false)
  const [aiResult, setAiResult] = useState('')
  const [aiAction, setAiAction] = useState('continue')
  const [saving, setSaving] = useState(false)
  const [wordCount, setWordCount] = useState(0)

  useEffect(() => {
    if (!projectId || !chapterId) return
    chapterApi.get(projectId, chapterId).then((data) => {
      setChapter(data as unknown as typeof chapter)
    })
  }, [projectId, chapterId])

  const editor = useEditor({
    extensions: [StarterKit],
    content: chapter?.content || '',
    onUpdate: ({ editor }) => {
      setWordCount(editor.getText().length)
      debouncedSave(editor.getHTML())
    },
  })

  useEffect(() => {
    if (editor && chapter?.content !== undefined) {
      editor.commands.setContent(chapter.content)
    }
  }, [chapter, editor])

  const debouncedSave = useCallback(
    debounce(async (content: string) => {
      if (!projectId || !chapterId) return
      setSaving(true)
      try {
        await chapterApi.update(projectId, chapterId, {
          content,
          word_count: content.length,
        })
      } finally {
        setSaving(false)
      }
    }, 3000),
    [projectId, chapterId]
  )

  const handleAiAssist = async () => {
    if (!projectId || !chapterId || !editor) return
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId) return
    const selection = editor.state.selection.empty
      ? undefined
      : editor.state.doc.textBetween(
          editor.state.selection.from,
          editor.state.selection.to
        )
    const result = (await chapterApi.aiAssist(
      projectId,
      cfgId,
      chapterId,
      aiAction,
      selection
    )) as unknown as { content: string }
    setAiResult(result.content)
  }

  const handleInsertAiResult = () => {
    if (editor && aiResult) {
      editor.chain().focus().insertContent(aiResult).run()
      setAiResult('')
    }
  }

  const actionLabels: Record<string, string> = {
    continue: '续写',
    rewrite: '改写',
    polish: '润色',
    expand: '扩写',
    summarize: '摘要',
    dialogue: '对话',
  }

  if (!projectId || !chapterId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请从大纲中选择章节
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <div className="flex flex-1 flex-col">
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-4 text-sm text-gray-500">
            <span className="font-medium text-gray-700">
              {chapter?.title || '加载中...'}
            </span>
            <span>{wordCount} 字</span>
            <span>{saving ? '保存中...' : '已保存'}</span>
          </div>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowAi(!showAi)}
            >
              <Sparkles className="mr-1 h-4 w-4" /> AI 助手
            </Button>
            <Button variant="ghost" size="sm">
              <History className="mr-1 h-4 w-4" /> 版本
            </Button>
          </div>
        </div>
        <div className="mx-auto w-full max-w-4xl flex-1 overflow-auto p-8">
          <EditorContent
            editor={editor}
            className="prose prose-lg max-w-none"
          />
        </div>
      </div>

      {showAi && (
        <div className="w-80 overflow-auto border-l p-4">
          <h3 className="mb-3 font-semibold">AI 助手</h3>
          <div className="mb-3 space-y-2">
            {Object.entries(actionLabels).map(([key, label]) => (
              <Button
                key={key}
                variant={aiAction === key ? 'default' : 'outline'}
                size="sm"
                onClick={() => setAiAction(key)}
                className="mr-1"
              >
                {label}
              </Button>
            ))}
          </div>
          <Button
            onClick={handleAiAssist}
            className="mb-4 w-full"
          >
            <Sparkles className="mr-2 h-4 w-4" /> 执行
          </Button>
          {aiResult && (
            <div className="space-y-2">
              <div className="rounded-md bg-gray-50 p-3 text-sm">
                {aiResult}
              </div>
              <Button onClick={handleInsertAiResult} size="sm" className="w-full">
                <Save className="mr-1 h-4 w-4" /> 插入到编辑器
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
