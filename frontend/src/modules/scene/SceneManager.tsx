import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Edit3,
  FileUp,
  GripVertical,
  Loader2,
  MapPinned,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { getActiveLLMConfigId, sceneApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import type { Scene as SceneItem } from '@/types'

type ToastType = 'success' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface DraggedScene {
  id: string
  index: number
}

const SCENE_ORDER_UPDATED_EVENT = 'scene-order-updated'

const emptyForm = {
  name: '',
  location: '',
  time: '',
  atmosphere: '',
  description: '',
  details: '',
  notes: '',
}

let toastId = 0

const getApiErrorDetail = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response
    ?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

const sceneToForm = (scene: SceneItem): typeof emptyForm => ({
  name: scene.name || '',
  location: scene.location || '',
  time: scene.time || '',
  atmosphere: scene.atmosphere || '',
  description: scene.description || '',
  details: scene.details || '',
  notes: scene.notes || '',
})

const formToSceneData = (form: typeof emptyForm) => ({
  name: form.name.trim(),
  location: form.location.trim() || null,
  time: form.time.trim() || null,
  atmosphere: form.atmosphere.trim() || null,
  description: form.description.trim() || null,
  details: form.details.trim() || null,
  notes: form.notes.trim() || null,
})

export const SceneManager: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [scenes, setScenes] = useState<SceneItem[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [draggedScene, setDraggedScene] = useState<DraggedScene | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const showToast = (type: ToastType, message: string) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id))
    }, 3000)
  }

  const fetchScenes = async () => {
    if (!projectId) return
    const result = (await sceneApi.list(projectId)) as unknown as {
      data: SceneItem[]
    }
    setScenes(result.data || [])
  }

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    const loadScenes = async () => {
      const result = (await sceneApi.list(projectId)) as unknown as {
        data: SceneItem[]
      }
      if (!cancelled) {
        setScenes(result.data || [])
      }
    }

    void loadScenes()
    return () => {
      cancelled = true
    }
  }, [projectId])

  const openCreateModal = () => {
    setForm(emptyForm)
    setShowCreate(true)
  }

  const openEditModal = (scene: SceneItem) => {
    setForm(sceneToForm(scene))
    setEditingId(scene.id)
  }

  const closeModal = () => {
    setShowCreate(false)
    setEditingId(null)
    setForm(emptyForm)
  }

  const handleCreate = async () => {
    if (!projectId || !form.name.trim()) return
    try {
      await sceneApi.create(projectId, formToSceneData(form))
      closeModal()
      void fetchScenes()
      showToast('success', '场景已创建')
    } catch {
      showToast('error', '创建场景失败')
    }
  }

  const handleUpdate = async () => {
    if (!projectId || !editingId || !form.name.trim()) return
    try {
      await sceneApi.update(projectId, editingId, formToSceneData(form))
      closeModal()
      void fetchScenes()
      showToast('success', '场景已更新')
    } catch {
      showToast('error', '更新场景失败')
    }
  }

  const handleImport = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId || !importText.trim()) {
      showToast('error', '请先配置 LLM 并输入场景描述')
      return
    }

    setImporting(true)
    try {
      const result = (await sceneApi.importFromText(
        projectId,
        cfgId,
        importText
      )) as unknown as { count: number }
      const count = result.count || 0
      setImportText('')
      setShowImport(false)
      void fetchScenes()
      showToast('success', `成功导入 ${count} 个场景`)
    } catch (error) {
      showToast('error', getApiErrorDetail(error, 'AI 导入场景失败'))
    } finally {
      setImporting(false)
    }
  }

  const handleDelete = async (sceneId: string) => {
    if (!projectId) return
    try {
      await sceneApi.delete(projectId, sceneId)
      setExpandedId((prev) => (prev === sceneId ? null : prev))
      void fetchScenes()
      showToast('success', '场景已删除')
    } catch {
      showToast('error', '删除场景失败')
    }
  }

  const handleMoveScene = async (
    dragged: DraggedScene | null,
    targetIndex: number
  ) => {
    if (!projectId || !dragged || dragged.index === targetIndex) return

    const previousScenes = scenes
    const nextScenes = [...scenes]
    const [moving] = nextScenes.splice(dragged.index, 1)
    nextScenes.splice(targetIndex, 0, moving)
    setScenes(nextScenes)

    try {
      const result = (await sceneApi.move(
        projectId,
        dragged.id,
        targetIndex
      )) as unknown as { data: SceneItem[] }
      const orderedScenes = result.data || nextScenes
      setScenes(orderedScenes)
      window.dispatchEvent(
        new CustomEvent(SCENE_ORDER_UPDATED_EVENT, {
          detail: {
            projectId,
            scenes: orderedScenes.map((scene) => ({
              id: scene.id,
              sort_order: scene.sort_order,
            })),
          },
        })
      )
      showToast('success', '场景顺序已更新')
    } catch {
      setScenes(previousScenes)
      showToast('error', '调整场景顺序失败')
      void fetchScenes()
    }
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b p-4">
        <h2 className="text-lg font-semibold">场景管理</h2>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowImport(true)}
          >
            <Sparkles className="mr-1 h-4 w-4" /> AI导入场景
          </Button>
          <Button variant="outline" size="sm" onClick={openCreateModal}>
            <Plus className="mr-1 h-4 w-4" /> 添加场景
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {scenes.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="space-y-4 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                <MapPinned className="h-6 w-6" />
              </div>
              <p className="text-gray-500">暂无场景</p>
              <div className="flex justify-center gap-3">
                <Button onClick={() => setShowImport(true)}>
                  <FileUp className="mr-2 h-4 w-4" /> AI导入场景
                </Button>
                <Button variant="outline" onClick={openCreateModal}>
                  <Plus className="mr-2 h-4 w-4" /> 添加场景
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {scenes.map((scene, index) => {
              const expanded = expandedId === scene.id
              return (
                <div
                  key={scene.id}
                  className="rounded-lg border bg-white shadow-sm"
                  onDragOver={(event) => {
                    if (draggedScene) event.preventDefault()
                  }}
                  onDrop={(event) => {
                    event.preventDefault()
                    void handleMoveScene(draggedScene, index)
                    setDraggedScene(null)
                  }}
                >
                  <div
                    role="button"
                    tabIndex={0}
                    className="flex w-full items-center gap-3 p-4 text-left"
                    onClick={() => setExpandedId(expanded ? null : scene.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setExpandedId(expanded ? null : scene.id)
                      }
                    }}
                  >
                    <button
                      type="button"
                      draggable
                      className="cursor-grab text-gray-300 hover:text-gray-500 active:cursor-grabbing"
                      onClick={(event) => event.stopPropagation()}
                      onDragStart={(event) => {
                        event.stopPropagation()
                        event.dataTransfer.effectAllowed = 'move'
                        setDraggedScene({ id: scene.id, index })
                      }}
                      onDragEnd={() => setDraggedScene(null)}
                      title="拖拽调整顺序"
                    >
                      <GripVertical className="h-4 w-4" />
                    </button>
                    <span className="text-gray-400">
                      {expanded ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                    </span>
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700">
                      <MapPinned className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate font-medium text-gray-900">
                          {scene.name}
                        </h3>
                        {scene.location && (
                          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                            {scene.location}
                          </span>
                        )}
                        {scene.time && (
                          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                            {scene.time}
                          </span>
                        )}
                      </div>
                      {scene.description && (
                        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-gray-500">
                          {scene.description}
                        </p>
                      )}
                    </div>
                    <div
                      className="flex gap-1"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditModal(scene)}
                      >
                        <Edit3 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(scene.id)}
                      >
                        <Trash2 className="h-4 w-4 text-red-400" />
                      </Button>
                    </div>
                  </div>

                  {expanded && (
                    <div className="space-y-3 border-t px-4 pb-4 pt-3">
                      {scene.atmosphere && (
                        <SceneBlock title="氛围" content={scene.atmosphere} />
                      )}
                      {scene.description && (
                        <SceneBlock title="场景描述" content={scene.description} />
                      )}
                      {scene.details && (
                        <SceneBlock title="关键细节" content={scene.details} />
                      )}
                      {scene.notes && (
                        <SceneBlock title="备注" content={scene.notes} />
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <SceneFormModal
        open={showCreate || Boolean(editingId)}
        title={editingId ? '编辑场景' : '添加场景'}
        form={form}
        setForm={setForm}
        onClose={closeModal}
        onSubmit={editingId ? handleUpdate : handleCreate}
      />
      <SceneImportModal
        open={showImport}
        text={importText}
        importing={importing}
        setText={setImportText}
        onClose={() => {
          if (!importing) setShowImport(false)
        }}
        onSubmit={handleImport}
      />

      <div className="fixed right-4 top-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm shadow-lg ${
              toast.type === 'success'
                ? 'bg-green-50 text-green-700'
                : 'bg-red-50 text-red-700'
            }`}
          >
            {toast.type === 'success' ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <AlertCircle className="h-4 w-4" />
            )}
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  )
}

const SceneBlock: React.FC<{ title: string; content: string }> = ({
  title,
  content,
}) => (
  <div>
    <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
      {title}
    </h4>
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
      {content}
    </p>
  </div>
)

interface SceneFormModalProps {
  open: boolean
  title: string
  form: typeof emptyForm
  setForm: React.Dispatch<React.SetStateAction<typeof emptyForm>>
  onClose: () => void
  onSubmit: () => void
}

const SceneFormModal: React.FC<SceneFormModalProps> = ({
  open,
  title,
  form,
  setForm,
  onClose,
  onSubmit,
}) => (
  <Modal open={open} onClose={onClose} title={title}>
    <div className="max-h-[75vh] space-y-3 overflow-auto pr-1">
      <Input
        label="场景名称"
        value={form.name}
        onChange={(event) =>
          setForm((prev) => ({ ...prev, name: event.target.value }))
        }
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label="地点"
          value={form.location}
          onChange={(event) =>
            setForm((prev) => ({ ...prev, location: event.target.value }))
          }
        />
        <Input
          label="时间"
          value={form.time}
          onChange={(event) =>
            setForm((prev) => ({ ...prev, time: event.target.value }))
          }
        />
      </div>
      <Input
        label="氛围"
        value={form.atmosphere}
        onChange={(event) =>
          setForm((prev) => ({ ...prev, atmosphere: event.target.value }))
        }
      />
      <SceneTextarea
        label="场景描述"
        rows={4}
        value={form.description}
        onChange={(value) =>
          setForm((prev) => ({ ...prev, description: value }))
        }
      />
      <SceneTextarea
        label="关键细节"
        rows={4}
        value={form.details}
        onChange={(value) => setForm((prev) => ({ ...prev, details: value }))}
      />
      <SceneTextarea
        label="备注"
        rows={3}
        value={form.notes}
        onChange={(value) => setForm((prev) => ({ ...prev, notes: value }))}
      />
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="outline" onClick={onClose}>
          取消
        </Button>
        <Button onClick={onSubmit} disabled={!form.name.trim()}>
          保存
        </Button>
      </div>
    </div>
  </Modal>
)

const SceneTextarea: React.FC<{
  label: string
  rows: number
  value: string
  onChange: (value: string) => void
}> = ({ label, rows, value, onChange }) => (
  <div className="space-y-1">
    <label className="block text-sm font-medium text-gray-700">{label}</label>
    <textarea
      className="w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-sm leading-relaxed focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
      rows={rows}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  </div>
)

interface SceneImportModalProps {
  open: boolean
  text: string
  importing: boolean
  setText: React.Dispatch<React.SetStateAction<string>>
  onClose: () => void
  onSubmit: () => void
}

const SceneImportModal: React.FC<SceneImportModalProps> = ({
  open,
  text,
  importing,
  setText,
  onClose,
  onSubmit,
}) => (
  <Modal open={open} onClose={onClose} title="AI导入场景">
    <div className="space-y-3">
      <textarea
        className="w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-sm leading-relaxed focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
        rows={12}
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="粘贴场景描述、世界观地点说明、章节片段或素材笔记"
        disabled={importing}
      />
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose} disabled={importing}>
          取消
        </Button>
        <Button onClick={onSubmit} disabled={importing || !text.trim()}>
          {importing ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="mr-1 h-4 w-4" />
          )}
          开始导入
        </Button>
      </div>
    </div>
  </Modal>
)
