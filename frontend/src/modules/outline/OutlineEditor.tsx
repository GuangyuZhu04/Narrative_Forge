import React, { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useOutlineStore } from '@/stores/outlineStore'
import { outlineApi, getActiveLLMConfigId, systemSettingsApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import {
  Plus,
  Sparkles,
  ChevronRight,
  ChevronDown,
  Trash2,
  Edit3,
  Wand2,
  Settings2,
  UnfoldVertical,
  FoldVertical,
  Loader2,
  CheckCircle2,
  AlertCircle,
  GripVertical,
  Maximize2,
  Minimize2,
} from 'lucide-react'
import type { OutlineNode, SystemPromptSetting } from '@/types'

type ToastType = 'success' | 'error'
type ExpandConfig = {
  node: OutlineNode
  systemPrompt: string
  count: number
}

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface DraggedNode {
  id: string
  parentId: string | null
}

let toastId = 0
const OUTLINE_EXPAND_SYSTEM_KEY = 'outline_expand.system'
const OUTLINE_EXPAND_DEFAULT_COUNT_KEY = 'outline_expand.default_count'

const getApiErrorDetail = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response
    ?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

export const OutlineEditor: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const {
    outlines,
    currentOutline,
    currentTree,
    generating,
    fetchOutlines,
    fetchTree,
    generateOutline,
    expandNode,
    addNode,
    updateNode,
    deleteNode,
    moveNode,
  } = useOutlineStore()

  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showGenDialog, setShowGenDialog] = useState(false)
  const [showPolishDialog, setShowPolishDialog] = useState(false)
  const [showExpandDialog, setShowExpandDialog] = useState(false)
  const [showEditOutlineDialog, setShowEditOutlineDialog] = useState(false)
  const [editOutlineTitle, setEditOutlineTitle] = useState('')
  const [editOutlineDesc, setEditOutlineDesc] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [genParams, setGenParams] = useState({
    genre: '',
    theme: '',
    style: '',
    word_count_target: '',
    extra_requirements: '',
  })
  const [polishDirection, setPolishDirection] = useState('')
  const [polishing, setPolishing] = useState(false)
  const [expandConfig, setExpandConfig] = useState<ExpandConfig | null>(null)
  const [expandDefaultsLoading, setExpandDefaultsLoading] = useState(false)
  const [editOutlineFullscreen, setEditOutlineFullscreen] = useState(false)
  const [editNodeFullscreen, setEditNodeFullscreen] = useState(false)
  const [editingNode, setEditingNode] = useState<{
    id: string
    title: string
    summary: string
  } | null>(null)
  const [allExpanded, setAllExpanded] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [draggedNode, setDraggedNode] = useState<DraggedNode | null>(null)

  const showToast = useCallback((type: ToastType, message: string) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3000)
  }, [])

  useEffect(() => {
    if (projectId) {
      fetchOutlines(projectId)
    }
  }, [projectId])

  useEffect(() => {
    if (outlines.length > 0 && !currentOutline) {
      fetchTree(projectId!, outlines[0].id)
    }
  }, [outlines, currentOutline])

  const handleCreateOutline = async () => {
    if (!projectId || !newTitle.trim()) return
    try {
      setActionLoading('create-outline')
      const outline = (await outlineApi.create(projectId, {
        title: newTitle,
        description: newDesc || null,
      })) as unknown as { id: string }
      setNewTitle('')
      setNewDesc('')
      setShowCreateDialog(false)
      await fetchOutlines(projectId)
      await fetchTree(projectId, outline.id)
      showToast('success', '大纲创建成功')
    } catch {
      showToast('error', '创建大纲失败，请重试')
    } finally {
      setActionLoading(null)
    }
  }

  const handleSelectOutline = async (outlineId: string) => {
    if (!projectId) return
    try {
      await fetchTree(projectId, outlineId)
      setAllExpanded(false)
    } catch {
      showToast('error', '加载大纲失败')
    }
  }

  const handleOpenEditOutline = () => {
    if (!currentOutline) return
    setEditOutlineFullscreen(false)
    setEditOutlineTitle(currentOutline.title)
    setEditOutlineDesc(currentOutline.description || '')
    setShowEditOutlineDialog(true)
  }

  const handleSaveOutline = async () => {
    if (!projectId || !currentOutline) return
    try {
      setActionLoading('save-outline')
      const data: Record<string, unknown> = {}
      if (editOutlineTitle.trim()) data.title = editOutlineTitle.trim()
      data.description = editOutlineDesc || null
      await outlineApi.update(projectId, currentOutline.id, data)
      setShowEditOutlineDialog(false)
      setEditOutlineFullscreen(false)
      await fetchOutlines(projectId)
      await fetchTree(projectId, currentOutline.id)
      showToast('success', '大纲信息已更新')
    } catch {
      showToast('error', '更新大纲失败，请重试')
    } finally {
      setActionLoading(null)
    }
  }

  const handleGenerate = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId) {
      showToast('error', '请先配置 LLM')
      return
    }
    try {
      const outline = await generateOutline(projectId, cfgId, genParams)
      setShowGenDialog(false)
      if (outline?.id) {
        await fetchTree(projectId, outline.id)
      }
      showToast('success', '大纲生成成功')
    } catch {
      showToast('error', 'AI 生成大纲失败，请检查 LLM 配置')
    }
  }

  const handlePolish = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId || !currentOutline) {
      showToast('error', '请先配置 LLM')
      return
    }
    setPolishing(true)
    try {
      await outlineApi.optimize(projectId, cfgId, currentOutline.id, polishDirection)
      await fetchTree(projectId, currentOutline.id)
      setShowPolishDialog(false)
      setPolishDirection('')
      showToast('success', '大纲打磨完成')
    } catch {
      showToast('error', 'AI 打磨失败，请检查 LLM 配置')
    } finally {
      setPolishing(false)
    }
  }

  const handleAddChild = useCallback(
    async (parentId: string | null, nodeType: string) => {
      if (!projectId || !currentOutline) {
        showToast('error', '请先选择大纲')
        return
      }
      try {
        setActionLoading(`add-${parentId ?? 'root'}`)
        await addNode(projectId, currentOutline.id, parentId, {
          node_type: nodeType as OutlineNode['node_type'],
          title: '新节点',
          summary: null,
        })
        await fetchTree(projectId, currentOutline.id)
        showToast('success', '节点添加成功')
      } catch {
        showToast('error', '添加节点失败，请重试')
      } finally {
        setActionLoading(null)
      }
    },
    [projectId, currentOutline, addNode, fetchTree, showToast]
  )

  const parseExpandCount = (value: unknown) => {
    const count = Number.parseInt(String(value ?? ''), 10)
    if (Number.isNaN(count)) return 3
    return Math.max(1, Math.min(count, 100))
  }

  const handleExpand = useCallback(
    async (node: OutlineNode) => {
      const cfgId = await getActiveLLMConfigId()
      if (!cfgId || !projectId || !currentOutline) {
        showToast('error', '请先配置 LLM')
        return
      }
      try {
        setExpandDefaultsLoading(true)
        const result = (await systemSettingsApi.listPrompts()) as unknown as {
          data: SystemPromptSetting[]
        }
        const settings = result.data || []
        const systemPromptSetting = settings.find(
          (item) => item.key === OUTLINE_EXPAND_SYSTEM_KEY
        )
        const defaultCountSetting = settings.find(
          (item) => item.key === OUTLINE_EXPAND_DEFAULT_COUNT_KEY
        )
        setExpandConfig({
          node,
          systemPrompt: systemPromptSetting?.effective_value || '',
          count: parseExpandCount(defaultCountSetting?.effective_value),
        })
        setShowExpandDialog(true)
      } catch {
        showToast('error', '加载 AI 扩展配置失败，请稍后重试')
      } finally {
        setExpandDefaultsLoading(false)
      }
    },
    [projectId, currentOutline, showToast]
  )

  const handleConfirmExpand = useCallback(
    async () => {
      if (!expandConfig || !projectId || !currentOutline) return
      const cfgId = await getActiveLLMConfigId()
      if (!cfgId) {
        showToast('error', '请先配置 LLM')
        return
      }
      const count = parseExpandCount(expandConfig.count)
      try {
        setActionLoading(`expand-${expandConfig.node.id}`)
        await expandNode(projectId, cfgId, expandConfig.node.id, {
          count,
          system_prompt: expandConfig.systemPrompt,
        })
        setShowExpandDialog(false)
        setExpandConfig(null)
        await fetchTree(projectId, currentOutline.id)
        showToast('success', `节点扩展成功，已请求生成 ${count} 个子节点`)
      } catch (error) {
        showToast(
          'error',
          getApiErrorDetail(error, 'AI 扩展失败，请检查 LLM 配置')
        )
      } finally {
        setActionLoading(null)
      }
    },
    [projectId, currentOutline, expandConfig, expandNode, fetchTree, showToast]
  )

  const handleEditNode = (node: OutlineNode) => {
    setEditNodeFullscreen(false)
    setEditingNode({
      id: node.id,
      title: node.title,
      summary: node.summary || '',
    })
  }

  const handleSaveNode = async () => {
    if (!editingNode || !projectId || !currentOutline) return
    try {
      setActionLoading('save-node')
      await updateNode(projectId, editingNode.id, {
        title: editingNode.title,
        summary: editingNode.summary || null,
      })
      setEditingNode(null)
      await fetchTree(projectId, currentOutline.id)
      showToast('success', '节点已更新')
    } catch {
      showToast('error', '更新节点失败')
    } finally {
      setActionLoading(null)
    }
  }

  const handleDeleteNode = async (nodeId: string) => {
    if (!projectId || !currentOutline) return
    try {
      setActionLoading(`delete-${nodeId}`)
      await deleteNode(projectId, nodeId)
      await fetchTree(projectId, currentOutline.id)
      showToast('success', '节点已删除')
    } catch {
      showToast('error', '删除节点失败')
    } finally {
      setActionLoading(null)
    }
  }

  const handleMoveNode = useCallback(
    async (nodeId: string, parentId: string | null, newOrder: number) => {
      if (!projectId || !currentOutline) return
      try {
        setActionLoading(`move-${nodeId}`)
        await moveNode(projectId, nodeId, parentId, newOrder)
        await fetchTree(projectId, currentOutline.id)
        showToast('success', '节点顺序已更新')
      } catch {
        showToast('error', '调整节点顺序失败')
      } finally {
        setActionLoading(null)
        setDraggedNode(null)
      }
    },
    [projectId, currentOutline, moveNode, fetchTree, showToast]
  )

  const toggleExpandAll = () => {
    setAllExpanded(!allExpanded)
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }

  return (
    <div className="relative flex h-full flex-col">
      <div className="border-b p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold">大纲编辑</h2>
            {outlines.length > 0 && (
              <select
                className="rounded-md border px-2 py-1 text-sm"
                value={currentOutline?.id || ''}
                onChange={(e) => handleSelectOutline(e.target.value)}
              >
                {outlines.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title}
                  </option>
                ))}
              </select>
            )}
            {currentOutline && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleOpenEditOutline}
                title="编辑大纲信息"
              >
                <Settings2 className="h-4 w-4 text-gray-500" />
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            {currentOutline && currentTree.length > 0 && (
              <Button variant="outline" size="sm" onClick={toggleExpandAll}>
                {allExpanded ? (
                  <>
                    <FoldVertical className="mr-1 h-4 w-4" /> 收起全部
                  </>
                ) : (
                  <>
                    <UnfoldVertical className="mr-1 h-4 w-4" /> 展开全部
                  </>
                )}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowCreateDialog(true)}
            >
              <Plus className="mr-1 h-4 w-4" /> 新建大纲
            </Button>
            {currentOutline && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleAddChild(null, 'VOLUME')}
                  disabled={actionLoading === 'add-root'}
                >
                  {actionLoading === 'add-root' ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Plus className="mr-1 h-4 w-4" />
                  )}{' '}
                  添加卷
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowPolishDialog(true)}
                >
                  <Wand2 className="mr-1 h-4 w-4" /> AI 打磨
                </Button>
              </>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowGenDialog(true)}
            >
              <Sparkles className="mr-1 h-4 w-4" /> AI 生成
            </Button>
          </div>
        </div>
        {currentOutline?.description && (
          <p className="mt-2 text-sm text-gray-500 line-clamp-2">
            {currentOutline.description}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-auto p-4">
        {generating ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <Loader2 className="mx-auto mb-2 h-8 w-8 animate-spin text-blue-500" />
              <p className="text-gray-500">AI 正在生成大纲...</p>
            </div>
          </div>
        ) : polishing ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <Loader2 className="mx-auto mb-2 h-8 w-8 animate-spin text-purple-500" />
              <p className="text-gray-500">AI 正在打磨大纲...</p>
            </div>
          </div>
        ) : !currentOutline ? (
          <div className="flex h-full items-center justify-center">
            <div className="space-y-4 text-center">
              <p className="text-gray-500">暂无大纲，请新建或使用 AI 生成</p>
              <div className="flex justify-center gap-3">
                <Button onClick={() => setShowCreateDialog(true)}>
                  <Plus className="mr-2 h-4 w-4" /> 新建大纲
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowGenDialog(true)}
                >
                  <Sparkles className="mr-2 h-4 w-4" /> AI 生成
                </Button>
              </div>
            </div>
          </div>
        ) : currentTree.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="space-y-4 text-center">
              <p className="text-gray-500">大纲为空，请添加节点</p>
              <Button
                onClick={() => handleAddChild(null, 'VOLUME')}
                disabled={actionLoading === 'add-root'}
              >
                {actionLoading === 'add-root' ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="mr-2 h-4 w-4" />
                )}{' '}
                添加第一卷
              </Button>
            </div>
          </div>
        ) : (
          currentTree.map((node: OutlineNode, index: number) => (
            <OutlineNodeItem
              key={node.id}
              node={node}
              parentId={null}
              siblingIndex={index}
              allExpanded={allExpanded}
              onExpand={handleExpand}
              onAddChild={handleAddChild}
              onEdit={handleEditNode}
              onDelete={handleDeleteNode}
              onMove={handleMoveNode}
              draggedNode={draggedNode}
              onDragStart={(nodeId, parentId) =>
                setDraggedNode({ id: nodeId, parentId })
              }
              onDragEnd={() => setDraggedNode(null)}
              actionLoading={actionLoading}
            />
          ))
        )}
      </div>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-center gap-2 rounded-lg px-4 py-2 text-sm shadow-lg transition-all ${
              t.type === 'success'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}
          >
            {t.type === 'success' ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <AlertCircle className="h-4 w-4" />
            )}
            {t.message}
          </div>
        ))}
      </div>

      <Modal
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        title="新建大纲"
      >
        <div className="space-y-4">
          <Input
            label="大纲标题"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="输入大纲标题"
          />
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              描述
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={3}
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="简要描述大纲内容..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowCreateDialog(false)}
            >
              取消
            </Button>
            <Button
              onClick={handleCreateOutline}
              disabled={!newTitle.trim() || actionLoading === 'create-outline'}
            >
              {actionLoading === 'create-outline' ? '创建中...' : '创建'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showGenDialog}
        onClose={() => setShowGenDialog(false)}
        title="AI 生成大纲"
      >
        <div className="space-y-4">
          <Input
            label="体裁"
            value={genParams.genre}
            onChange={(e) =>
              setGenParams({ ...genParams, genre: e.target.value })
            }
            placeholder="如：玄幻、都市、科幻"
          />
          <Input
            label="主题"
            value={genParams.theme}
            onChange={(e) =>
              setGenParams({ ...genParams, theme: e.target.value })
            }
            placeholder="如：逆袭、成长、复仇"
          />
          <Input
            label="风格"
            value={genParams.style}
            onChange={(e) =>
              setGenParams({ ...genParams, style: e.target.value })
            }
            placeholder="如：轻松幽默、热血燃向"
          />
          <Input
            label="目标字数"
            value={genParams.word_count_target}
            onChange={(e) =>
              setGenParams({ ...genParams, word_count_target: e.target.value })
            }
            placeholder="如：100万字"
          />
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              额外要求
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={2}
              value={genParams.extra_requirements}
              onChange={(e) =>
                setGenParams({
                  ...genParams,
                  extra_requirements: e.target.value,
                })
              }
              placeholder="其他特殊要求..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowGenDialog(false)}
            >
              取消
            </Button>
            <Button onClick={handleGenerate} disabled={generating}>
              {generating ? '生成中...' : '生成'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showPolishDialog}
        onClose={() => setShowPolishDialog(false)}
        title="AI 打磨大纲"
      >
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            AI 将对当前大纲进行优化打磨，使情节更合理、结构更紧凑。
          </p>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              打磨方向（可选）
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={3}
              value={polishDirection}
              onChange={(e) => setPolishDirection(e.target.value)}
              placeholder="如：增强悬念、加快节奏、丰富支线..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowPolishDialog(false)}
            >
              取消
            </Button>
            <Button onClick={handlePolish} disabled={polishing}>
              {polishing ? '打磨中...' : '开始打磨'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showExpandDialog}
        onClose={() => {
          setShowExpandDialog(false)
          setExpandConfig(null)
        }}
        title="AI 扩展配置"
      >
        <div className="max-h-[70vh] space-y-4 overflow-auto pr-1">
          {expandDefaultsLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载配置中...
            </div>
          ) : expandConfig ? (
            <>
              <div className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
                当前节点：
                <span className="font-medium text-gray-800">
                  {expandConfig.node.title}
                </span>
              </div>
              <Input
                label="扩展子节点数量"
                type="number"
                min={1}
                max={100}
                value={expandConfig.count}
                onChange={(e) =>
                  setExpandConfig({
                    ...expandConfig,
                    count: parseExpandCount(e.target.value),
                  })
                }
              />
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  System Prompt
                </label>
                <textarea
                  className="w-full resize-y rounded-md border p-2 text-sm leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={12}
                  value={expandConfig.systemPrompt}
                  onChange={(e) =>
                    setExpandConfig({
                      ...expandConfig,
                      systemPrompt: e.target.value,
                    })
                  }
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowExpandDialog(false)
                    setExpandConfig(null)
                  }}
                  disabled={!!actionLoading}
                >
                  取消
                </Button>
                <Button
                  onClick={handleConfirmExpand}
                  disabled={
                    !!actionLoading ||
                    !expandConfig.systemPrompt.trim() ||
                    expandConfig.count < 1 ||
                    expandConfig.count > 100
                  }
                >
                  {actionLoading === `expand-${expandConfig.node.id}` ? (
                    <>
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                      扩展中...
                    </>
                  ) : (
                    <>
                      <Sparkles className="mr-1 h-4 w-4" />
                      开始扩展
                    </>
                  )}
                </Button>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">暂无可用配置</p>
          )}
        </div>
      </Modal>

      {showEditOutlineDialog && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/30 p-4">
          <div
            className={`flex flex-col rounded-lg bg-white shadow-xl ${
              editOutlineFullscreen
                ? 'h-full w-full'
                : 'max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] resize overflow-auto'
            }`}
            style={
              editOutlineFullscreen
                ? undefined
                : {
                    width: '640px',
                    height: '430px',
                    minWidth: '420px',
                    minHeight: '300px',
                  }
            }
          >
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-lg font-semibold text-gray-800">
                编辑大纲信息
              </h3>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() =>
                    setEditOutlineFullscreen(!editOutlineFullscreen)
                  }
                  title={editOutlineFullscreen ? '退出全屏' : '全屏'}
                >
                  {editOutlineFullscreen ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                </Button>
                <button
                  onClick={() => {
                    setShowEditOutlineDialog(false)
                    setEditOutlineFullscreen(false)
                  }}
                  className="text-gray-400 hover:text-gray-600"
                  title="关闭"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4">
              <Input
                label="大纲标题"
                value={editOutlineTitle}
                onChange={(e) => setEditOutlineTitle(e.target.value)}
                placeholder="输入大纲标题"
              />
              <div className="flex min-h-0 flex-1 flex-col">
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  描述
                </label>
                <textarea
                  className="min-h-[160px] flex-1 resize-none rounded-md border p-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={editOutlineDesc}
                  onChange={(e) => setEditOutlineDesc(e.target.value)}
                  placeholder="描述大纲的整体构思、核心设定、故事走向..."
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t px-4 py-3">
              <Button
                variant="outline"
                onClick={() => {
                  setShowEditOutlineDialog(false)
                  setEditOutlineFullscreen(false)
                }}
              >
                取消
              </Button>
              <Button
                onClick={handleSaveOutline}
                disabled={
                  !editOutlineTitle.trim() || actionLoading === 'save-outline'
                }
              >
                {actionLoading === 'save-outline' ? '保存中...' : '保存'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {editingNode && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/30 p-4">
          <div
            className={`flex flex-col rounded-lg bg-white shadow-xl ${
              editNodeFullscreen
                ? 'h-full w-full'
                : 'max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] resize overflow-auto'
            }`}
            style={
              editNodeFullscreen
                ? undefined
                : { width: '640px', height: '430px', minWidth: '420px', minHeight: '300px' }
            }
          >
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h3 className="text-lg font-semibold text-gray-800">编辑节点</h3>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setEditNodeFullscreen(!editNodeFullscreen)}
                  title={editNodeFullscreen ? '退出全屏' : '全屏'}
                >
                  {editNodeFullscreen ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                </Button>
                <button
                  onClick={() => setEditingNode(null)}
                  className="text-gray-400 hover:text-gray-600"
                  title="关闭"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4">
              <Input
                label="标题"
                value={editingNode.title}
                onChange={(e) =>
                  setEditingNode({ ...editingNode, title: e.target.value })
                }
              />
              <div className="flex min-h-0 flex-1 flex-col">
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  摘要
                </label>
                <textarea
                  className="min-h-[160px] flex-1 resize-none rounded-md border p-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={editingNode.summary}
                  onChange={(e) =>
                    setEditingNode({ ...editingNode, summary: e.target.value })
                  }
                  placeholder="描述该节点的情节概要..."
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t px-4 py-3">
              <Button
                variant="outline"
                onClick={() => setEditingNode(null)}
              >
                取消
              </Button>
              <Button
                onClick={handleSaveNode}
                disabled={actionLoading === 'save-node'}
              >
                {actionLoading === 'save-node' ? '保存中...' : '保存'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

interface NodeProps {
  node: OutlineNode
  parentId: string | null
  siblingIndex: number
  depth?: number
  allExpanded: boolean
  onExpand: (node: OutlineNode) => void
  onAddChild: (parentId: string | null, nodeType: string) => void
  onEdit: (node: OutlineNode) => void
  onDelete: (nodeId: string) => void
  onMove: (nodeId: string, parentId: string | null, newOrder: number) => void
  draggedNode: DraggedNode | null
  onDragStart: (nodeId: string, parentId: string | null) => void
  onDragEnd: () => void
  actionLoading: string | null
}

const OutlineNodeItem: React.FC<NodeProps> = ({
  node,
  parentId,
  siblingIndex,
  depth = 0,
  allExpanded,
  onExpand,
  onAddChild,
  onEdit,
  onDelete,
  onMove,
  draggedNode,
  onDragStart,
  onDragEnd,
  actionLoading,
}) => {
  const [localExpanded, setLocalExpanded] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [actionHovered, setActionHovered] = useState(false)

  const expanded = allExpanded || localExpanded

  useEffect(() => {
    if (!allExpanded) {
      setLocalExpanded(false)
    }
  }, [allExpanded])

  const typeLabel: Record<string, string> = {
    VOLUME: '卷',
    CHAPTER: '章',
    SCENE: '场景',
    PLOT_POINT: '情节',
    KEY_EVENT: '事件',
  }

  const childTypeMap: Record<string, string> = {
    VOLUME: 'CHAPTER',
    CHAPTER: 'SCENE',
    SCENE: 'PLOT_POINT',
    PLOT_POINT: 'KEY_EVENT',
  }

  const isLoading =
    actionLoading === `expand-${node.id}` ||
    actionLoading === `add-${node.id}` ||
    actionLoading === `delete-${node.id}` ||
    actionLoading === `move-${node.id}`
  const canDropHere =
    !!draggedNode && draggedNode.id !== node.id && draggedNode.parentId === parentId
  const isDragging = draggedNode?.id === node.id

  return (
    <div style={{ paddingLeft: depth * 20 }}>
      <div
        className={`flex items-center gap-2 rounded px-2 py-1.5 transition-colors ${
          canDropHere
            ? 'border border-dashed border-blue-300 bg-blue-50'
            : actionHovered
              ? 'bg-blue-50 ring-1 ring-blue-200'
              : ''
        } ${isDragging ? 'opacity-50' : 'hover:bg-gray-50'}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => {
          setHovered(false)
          setActionHovered(false)
        }}
        onDragOver={(e) => {
          if (!canDropHere) return
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
        }}
        onDrop={(e) => {
          e.preventDefault()
          if (!canDropHere || !draggedNode) return
          onMove(draggedNode.id, parentId, siblingIndex)
        }}
      >
        <span
          draggable={!isLoading}
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move'
            onDragStart(node.id, parentId)
          }}
          onDragEnd={onDragEnd}
          className="cursor-grab text-gray-300 hover:text-gray-500 active:cursor-grabbing"
          title="拖动排序"
        >
          <GripVertical className="h-4 w-4" />
        </span>
        {node.children.length > 0 ? (
          <button
            onClick={() => setLocalExpanded(!localExpanded)}
            className="text-gray-400 hover:text-gray-600"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        ) : (
          <span className="w-4" />
        )}
        <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">
          {typeLabel[node.node_type] || node.node_type}
        </span>
        <span className="text-sm font-medium">{node.title}</span>
        {node.llm_generated && (
          <span className="rounded bg-purple-100 px-1 py-0.5 text-xs text-purple-600">
            AI
          </span>
        )}
        {node.summary && !expanded && (
          <span className="max-w-xs truncate text-xs text-gray-400">
            — {node.summary}
          </span>
        )}
        {isLoading && (
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
        )}
        <div
          className={`ml-auto flex gap-1 transition-opacity ${
            hovered ? 'opacity-100' : 'opacity-0'
          }`}
          onMouseEnter={() => setActionHovered(true)}
          onMouseLeave={() => setActionHovered(false)}
        >
          {childTypeMap[node.node_type] && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onAddChild(node.id, childTypeMap[node.node_type])}
              title="添加子节点"
              disabled={isLoading}
            >
              <Plus className="h-3 w-3" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onEdit(node)}
            title="编辑"
            disabled={isLoading}
          >
            <Edit3 className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onExpand(node)}
            title="AI 扩展"
            disabled={isLoading}
          >
            <Sparkles className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDelete(node.id)}
            title="删除"
            disabled={isLoading}
          >
            <Trash2 className="h-3 w-3 text-red-400" />
          </Button>
        </div>
      </div>
      {expanded &&
        node.children.map((child: OutlineNode, index: number) => (
          <OutlineNodeItem
            key={child.id}
            node={child}
            parentId={node.id}
            siblingIndex={index}
            depth={depth + 1}
            allExpanded={allExpanded}
            onExpand={onExpand}
            onAddChild={onAddChild}
            onEdit={onEdit}
            onDelete={onDelete}
            onMove={onMove}
            draggedNode={draggedNode}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            actionLoading={actionLoading}
          />
        ))}
    </div>
  )
}
