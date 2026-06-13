import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { characterApi, getActiveLLMConfigId } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import {
  Plus,
  Sparkles,
  Trash2,
  Edit3,
  ChevronDown,
  ChevronRight,
  FileUp,
  Image as ImageIcon,
  Loader2,
  Upload,
  X,
  CheckCircle2,
  AlertCircle,
  GripVertical,
} from 'lucide-react'

interface CharacterItem {
  id: string
  name: string
  aliases?: string[]
  avatar_url?: string | null
  basic_info?: Record<string, unknown> | null
  personality?: Record<string, unknown> | null
  growth_arc?: Record<string, unknown> | null
  biography?: string | null
  setting_collection?: string | null
  notes?: string | null
  sort_order: number
}

type ToastType = 'success' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface DraggedCharacter {
  id: string
  index: number
}

let toastId = 0

const getApiErrorDetail = (error: unknown, fallback: string) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response
    ?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

const emptyForm = {
  name: '',
  aliases: '',
  age: '',
  gender: '',
  background: '',
  occupation: '',
  traits: '',
  values: '',
  habits: '',
  flaws: '',
  initial_state: '',
  development_direction: '',
  turning_point: '',
  final_state: '',
  biography: '',
  setting_collection: '',
  notes: '',
}

const toEditableText = (value: unknown): string => {
  if (value == null) return ''
  if (Array.isArray(value)) return value.map(toEditableText).filter(Boolean).join('、')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

const asRecord = (value: Record<string, unknown> | null | undefined) =>
  value && typeof value === 'object' && !Array.isArray(value) ? value : {}

const getProfileValue = (
  data: Record<string, unknown> | null | undefined,
  keys: string[]
) => {
  const record = asRecord(data)
  for (const key of keys) {
    if (record[key] != null && record[key] !== '') return toEditableText(record[key])
  }
  return ''
}

const setProfileValue = (
  data: Record<string, unknown>,
  keys: string[],
  canonicalKey: string,
  value: string
) => {
  keys.forEach((key) => {
    delete data[key]
  })
  if (value.trim()) data[canonicalKey] = value.trim()
}

const withNullableText = (
  value: string,
  originalValue: string | null | undefined
) => {
  const trimmed = value.trim()
  if (trimmed) return trimmed
  return originalValue ? null : undefined
}

const formToCharacterData = (
  form: typeof emptyForm,
  original?: CharacterItem | null
) => {
  const aliases = form.aliases
    ? form.aliases.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
    : original?.aliases?.length
      ? null
      : undefined

  const basicInfo: Record<string, unknown> = { ...asRecord(original?.basic_info) }
  setProfileValue(basicInfo, ['年龄', 'age'], '年龄', form.age)
  setProfileValue(basicInfo, ['性别', 'gender'], '性别', form.gender)
  setProfileValue(
    basicInfo,
    ['背景', 'background', 'background_story'],
    '背景',
    form.background
  )
  setProfileValue(basicInfo, ['职业', 'occupation'], '职业', form.occupation)

  const personality: Record<string, unknown> = { ...asRecord(original?.personality) }
  setProfileValue(personality, ['性格特征', 'traits'], '性格特征', form.traits)
  setProfileValue(personality, ['价值观', 'values'], '价值观', form.values)
  setProfileValue(personality, ['习惯', 'habits'], '习惯', form.habits)
  setProfileValue(personality, ['缺陷', 'flaws'], '缺陷', form.flaws)

  const growthArc: Record<string, unknown> = { ...asRecord(original?.growth_arc) }
  setProfileValue(
    growthArc,
    ['初始状态', 'starting_state', 'initial_state'],
    '初始状态',
    form.initial_state
  )
  setProfileValue(
    growthArc,
    ['发展方向', 'development_direction', 'transformation'],
    '发展方向',
    form.development_direction
  )
  setProfileValue(
    growthArc,
    ['转折点', 'turning_point', 'catalyst'],
    '转折点',
    form.turning_point
  )
  setProfileValue(
    growthArc,
    ['最终状态', 'final_state', 'ending_state'],
    '最终状态',
    form.final_state
  )

  return {
    name: form.name.trim(),
    aliases,
    basic_info: Object.keys(basicInfo).length > 0 ? basicInfo : undefined,
    personality: Object.keys(personality).length > 0 ? personality : undefined,
    growth_arc: Object.keys(growthArc).length > 0 ? growthArc : undefined,
    biography: withNullableText(form.biography, original?.biography),
    setting_collection: withNullableText(
      form.setting_collection,
      original?.setting_collection
    ),
    notes: withNullableText(form.notes, original?.notes),
  }
}

const characterToForm = (c: CharacterItem): typeof emptyForm => ({
  name: c.name || '',
  aliases: Array.isArray(c.aliases) ? c.aliases.join('、') : '',
  age: getProfileValue(c.basic_info, ['年龄', 'age']),
  gender: getProfileValue(c.basic_info, ['性别', 'gender']),
  background: getProfileValue(c.basic_info, [
    '背景',
    'background',
    'background_story',
  ]),
  occupation: getProfileValue(c.basic_info, ['职业', 'occupation']),
  traits: getProfileValue(c.personality, ['性格特征', 'traits']),
  values: getProfileValue(c.personality, ['价值观', 'values']),
  habits: getProfileValue(c.personality, ['习惯', 'habits']),
  flaws: getProfileValue(c.personality, ['缺陷', 'flaws']),
  initial_state: getProfileValue(c.growth_arc, [
    '初始状态',
    'starting_state',
    'initial_state',
  ]),
  development_direction: getProfileValue(c.growth_arc, [
    '发展方向',
    'development_direction',
    'transformation',
  ]),
  turning_point: getProfileValue(c.growth_arc, [
    '转折点',
    'turning_point',
    'catalyst',
  ]),
  final_state: getProfileValue(c.growth_arc, [
    '最终状态',
    'final_state',
    'ending_state',
  ]),
  biography: c.biography || '',
  setting_collection: c.setting_collection || '',
  notes: c.notes || '',
})

export const CharacterManager: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [characters, setCharacters] = useState<CharacterItem[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [genDesc, setGenDesc] = useState('')
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingSettingCollectionId, setEditingSettingCollectionId] =
    useState<string | null>(null)
  const [settingCollectionDraft, setSettingCollectionDraft] = useState('')
  const [savingSettingCollectionId, setSavingSettingCollectionId] = useState<
    string | null
  >(null)
  const [uploadingImageId, setUploadingImageId] = useState<string | null>(null)
  const [draggedCharacter, setDraggedCharacter] =
    useState<DraggedCharacter | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const showToast = (type: ToastType, message: string) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3000)
  }

  const fetchCharacters = async () => {
    if (!projectId) return
    const result = (await characterApi.list(projectId)) as unknown as {
      data: CharacterItem[]
    }
    setCharacters(result.data || [])
  }

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    const loadInitialCharacters = async () => {
      const result = (await characterApi.list(projectId)) as unknown as {
        data: CharacterItem[]
      }
      if (!cancelled) {
        setCharacters(result.data || [])
      }
    }

    void loadInitialCharacters()
    return () => {
      cancelled = true
    }
  }, [projectId])

  const handleCreate = async () => {
    if (!projectId || !form.name.trim()) return
    try {
      const data = formToCharacterData(form)
      await characterApi.create(projectId, data)
      setForm(emptyForm)
      setShowCreate(false)
      fetchCharacters()
      showToast('success', '人物创建成功')
    } catch {
      showToast('error', '创建人物失败')
    }
  }

  const handleUpdate = async () => {
    if (!projectId || !editingId || !form.name.trim()) return
    try {
      const current = characters.find((c) => c.id === editingId)
      const data = formToCharacterData(form, current)
      await characterApi.update(projectId, editingId, data)
      setForm(emptyForm)
      setEditingId(null)
      fetchCharacters()
      showToast('success', '人物信息已更新')
    } catch {
      showToast('error', '更新人物失败')
    }
  }

  const handleEdit = (c: CharacterItem) => {
    setEditingId(c.id)
    setForm(characterToForm(c))
  }

  const handleStartSettingCollectionEdit = (c: CharacterItem) => {
    setEditingSettingCollectionId(c.id)
    setSettingCollectionDraft(c.setting_collection || '')
  }

  const handleCancelSettingCollectionEdit = () => {
    setEditingSettingCollectionId(null)
    setSettingCollectionDraft('')
  }

  const handleSaveSettingCollection = async (c: CharacterItem) => {
    if (!projectId) return
    setSavingSettingCollectionId(c.id)
    try {
      const updated = (await characterApi.update(projectId, c.id, {
        setting_collection: settingCollectionDraft.trim() || null,
      })) as unknown as CharacterItem
      setCharacters((prev) =>
        prev.map((item) =>
          item.id === c.id
            ? {
                ...item,
                setting_collection: updated.setting_collection || null,
              }
            : item
        )
      )
      setEditingSettingCollectionId(null)
      setSettingCollectionDraft('')
      showToast('success', '人物设定集已保存')
    } catch {
      showToast('error', '保存人物设定集失败')
    } finally {
      setSavingSettingCollectionId(null)
    }
  }

  const updateCharacterImage = (updated: CharacterItem) => {
    setCharacters((prev) =>
      prev.map((item) =>
        item.id === updated.id
          ? { ...item, avatar_url: updated.avatar_url || null }
          : item
      )
    )
  }

  const handleUploadCharacterImage = async (
    c: CharacterItem,
    file: File | undefined
  ) => {
    if (!projectId || !file) return
    if (!file.type.startsWith('image/')) {
      showToast('error', '请选择图片文件')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      showToast('error', '图片大小不能超过 5MB')
      return
    }

    setUploadingImageId(c.id)
    try {
      const updated = (await characterApi.uploadImage(
        projectId,
        c.id,
        file
      )) as unknown as CharacterItem
      updateCharacterImage(updated)
      showToast('success', '人物形象已更新')
    } catch {
      showToast('error', '上传人物形象失败')
    } finally {
      setUploadingImageId(null)
    }
  }

  const handleDeleteCharacterImage = async (c: CharacterItem) => {
    if (!projectId) return

    setUploadingImageId(c.id)
    try {
      const updated = (await characterApi.deleteImage(
        projectId,
        c.id
      )) as unknown as CharacterItem
      updateCharacterImage(updated)
      showToast('success', '人物形象已清除')
    } catch {
      showToast('error', '清除人物形象失败')
    } finally {
      setUploadingImageId(null)
    }
  }

  const handleGenerate = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId || !genDesc.trim()) {
      showToast('error', '请先配置 LLM')
      return
    }
    try {
      await characterApi.generateProfile(projectId, cfgId, genDesc)
      setGenDesc('')
      setShowGenerate(false)
      fetchCharacters()
      showToast('success', '人物生成成功')
    } catch {
      showToast('error', 'AI 生成人物失败，请检查 LLM 配置')
    }
  }

  const handleImport = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId || !importText.trim()) {
      showToast('error', '请先配置 LLM 并输入文本内容')
      return
    }
    setImporting(true)
    try {
      const result = (await characterApi.importFromText(
        projectId,
        cfgId,
        importText
      )) as unknown as { count: number }
      const count = result.count || 0
      setImportText('')
      setShowImport(false)
      fetchCharacters()
      showToast('success', `成功导入 ${count} 个人物档案`)
    } catch (error) {
      showToast(
        'error',
        getApiErrorDetail(error, '导入失败，请检查 LLM 配置后重试')
      )
    } finally {
      setImporting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!projectId) return
    try {
      await characterApi.delete(projectId, id)
      fetchCharacters()
      showToast('success', '人物已删除')
    } catch {
      showToast('error', '删除人物失败')
    }
  }

  const handleMoveCharacter = async (
    dragged: DraggedCharacter | null,
    targetIndex: number
  ) => {
    if (!projectId || !dragged || dragged.index === targetIndex) return

    const previousCharacters = characters
    const nextCharacters = [...characters]
    const [moving] = nextCharacters.splice(dragged.index, 1)
    nextCharacters.splice(targetIndex, 0, moving)
    setCharacters(nextCharacters)

    try {
      const result = (await characterApi.move(
        projectId,
        dragged.id,
        targetIndex
      )) as unknown as { data: CharacterItem[] }
      setCharacters(result.data || nextCharacters)
      showToast('success', '人物顺序已更新')
    } catch {
      setCharacters(previousCharacters)
      showToast('error', '调整人物顺序失败')
      fetchCharacters()
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
        <h2 className="text-lg font-semibold">人物管理</h2>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setForm(emptyForm)
              setShowCreate(true)
            }}
          >
            <Plus className="mr-1 h-4 w-4" /> 添加人物
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowImport(true)}
          >
            <FileUp className="mr-1 h-4 w-4" /> 一键导入
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowGenerate(true)}
          >
            <Sparkles className="mr-1 h-4 w-4" /> AI 生成
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {characters.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="space-y-4 text-center">
              <p className="text-gray-500">暂无人物</p>
              <div className="flex justify-center gap-3">
                <Button onClick={() => setShowImport(true)}>
                  <FileUp className="mr-2 h-4 w-4" /> 一键导入
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setShowGenerate(true)}
                >
                  <Sparkles className="mr-2 h-4 w-4" /> AI 生成
                </Button>
              </div>
              <p className="text-sm text-gray-400">
                粘贴人物描述文本，AI 自动生成完整档案
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {characters.map((c, index) => {
              const expanded = expandedId === c.id
              const basicInfo = c.basic_info as Record<string, string> | null
              const personality = c.personality as Record<string, string> | null
              const growthArc = c.growth_arc as Record<string, string> | null

              return (
                <div
                  key={c.id}
                  className="rounded-lg border bg-white shadow-sm"
                  onDragOver={(e) => {
                    if (draggedCharacter) e.preventDefault()
                  }}
                  onDrop={(e) => {
                    e.preventDefault()
                    handleMoveCharacter(draggedCharacter, index)
                    setDraggedCharacter(null)
                  }}
                >
                  <div
                    className="flex items-center gap-2 p-4 cursor-pointer"
                    onClick={() => setExpandedId(expanded ? null : c.id)}
                  >
                    <button
                      type="button"
                      draggable
                      className="cursor-grab text-gray-300 hover:text-gray-500 active:cursor-grabbing"
                      onClick={(e) => e.stopPropagation()}
                      onDragStart={(e) => {
                        e.stopPropagation()
                        e.dataTransfer.effectAllowed = 'move'
                        setDraggedCharacter({ id: c.id, index })
                      }}
                      onDragEnd={() => setDraggedCharacter(null)}
                      title="拖拽调整顺序"
                    >
                      <GripVertical className="h-4 w-4" />
                    </button>
                    <button className="text-gray-400">
                      {expanded ? (
                        <ChevronDown className="h-4 w-4" />
                      ) : (
                        <ChevronRight className="h-4 w-4" />
                      )}
                    </button>
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-gray-50">
                      {c.avatar_url ? (
                        <img
                          src={c.avatar_url}
                          alt={`${c.name}人物形象`}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <ImageIcon className="h-5 w-5 text-gray-300" />
                      )}
                    </div>
                    <h3 className="font-medium">{c.name}</h3>
                    {c.aliases && c.aliases.length > 0 && (
                      <span className="text-sm text-gray-500">
                        （{c.aliases.join('、')}）
                      </span>
                    )}
                    {basicInfo?.['年龄'] && (
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                        {basicInfo['年龄']}
                      </span>
                    )}
                    {basicInfo?.['性别'] && (
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                        {basicInfo['性别']}
                      </span>
                    )}
                    <div className="ml-auto flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleEdit(c)
                        }}
                      >
                        <Edit3 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete(c.id)
                        }}
                      >
                        <Trash2 className="h-4 w-4 text-red-400" />
                      </Button>
                    </div>
                  </div>

                  {expanded && (
                    <div className="border-t px-4 pb-4 pt-3 space-y-3">
                      <div>
                        <h4 className="mb-2 text-xs font-semibold uppercase text-gray-400">
                          人物形象
                        </h4>
                        <div className="flex flex-wrap items-center gap-3 rounded-md border bg-gray-50 p-3">
                          <div className="flex h-28 w-20 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-white">
                            {c.avatar_url ? (
                              <img
                                src={c.avatar_url}
                                alt={`${c.name}人物形象`}
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <ImageIcon className="h-8 w-8 text-gray-300" />
                            )}
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <label
                              className={`inline-flex h-9 cursor-pointer items-center rounded-md border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 ${
                                uploadingImageId === c.id
                                  ? 'pointer-events-none opacity-60'
                                  : ''
                              }`}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {uploadingImageId === c.id ? (
                                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                              ) : (
                                <Upload className="mr-1 h-4 w-4" />
                              )}
                              {c.avatar_url ? '更换图片' : '上传图片'}
                              <input
                                type="file"
                                accept="image/png,image/jpeg,image/webp,image/gif"
                                className="hidden"
                                disabled={uploadingImageId === c.id}
                                onChange={(e) => {
                                  const file = e.currentTarget.files?.[0]
                                  e.currentTarget.value = ''
                                  void handleUploadCharacterImage(c, file)
                                }}
                              />
                            </label>
                            {c.avatar_url && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  void handleDeleteCharacterImage(c)
                                }}
                                disabled={uploadingImageId === c.id}
                              >
                                <X className="mr-1 h-4 w-4" />
                                清除图片
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>

                      {basicInfo && Object.keys(basicInfo).length > 0 && (
                        <div>
                          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
                            基本信息
                          </h4>
                          <div className="grid grid-cols-2 gap-2">
                            {Object.entries(basicInfo).map(([k, v]) => (
                              <div key={k} className="text-sm">
                                <span className="text-gray-500">{k}：</span>
                                <span>{v}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {personality && Object.keys(personality).length > 0 && (
                        <div>
                          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
                            性格特征
                          </h4>
                          <div className="space-y-1">
                            {Object.entries(personality).map(([k, v]) => (
                              <div key={k} className="text-sm">
                                <span className="text-gray-500">{k}：</span>
                                <span>{v}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {growthArc && Object.keys(growthArc).length > 0 && (
                        <div>
                          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
                            成长弧线
                          </h4>
                          <div className="space-y-1">
                            {Object.entries(growthArc).map(([k, v]) => (
                              <div key={k} className="text-sm">
                                <span className="text-gray-500">{k}：</span>
                                <span>{v}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {c.biography && (
                        <div>
                          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
                            人物小传
                          </h4>
                          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-600">
                            {c.biography}
                          </p>
                        </div>
                      )}

                      <div className="rounded-md border border-amber-100 bg-amber-50/50 p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <h4 className="text-xs font-semibold uppercase text-amber-700">
                            人物设定集
                          </h4>
                          {editingSettingCollectionId !== c.id && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleStartSettingCollectionEdit(c)
                              }}
                            >
                              <Edit3 className="mr-1 h-3.5 w-3.5" />
                              {c.setting_collection ? '编辑' : '添加'}
                            </Button>
                          )}
                        </div>
                        {editingSettingCollectionId === c.id ? (
                          <div className="space-y-2">
                            <textarea
                              className="min-h-[140px] w-full resize-y rounded-md border border-amber-200 bg-white p-2 text-sm leading-relaxed outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
                              value={settingCollectionDraft}
                              onChange={(e) =>
                                setSettingCollectionDraft(e.target.value)
                              }
                              placeholder="记录不需要进入 AI 编写输入的补充设定、创作备忘、隐藏信息、后续安排等..."
                            />
                            <div className="flex justify-end gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleCancelSettingCollectionEdit()
                                }}
                                disabled={savingSettingCollectionId === c.id}
                              >
                                取消
                              </Button>
                              <Button
                                size="sm"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleSaveSettingCollection(c)
                                }}
                                disabled={savingSettingCollectionId === c.id}
                              >
                                {savingSettingCollectionId === c.id ? (
                                  <>
                                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                                    保存中
                                  </>
                                ) : (
                                  '保存'
                                )}
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <p className="min-h-[72px] whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                            {c.setting_collection || '暂无人物设定集'}
                          </p>
                        )}
                      </div>

                      {c.notes && (
                        <div>
                          <h4 className="mb-1 text-xs font-semibold uppercase text-gray-400">
                            备注
                          </h4>
                          <p className="text-sm text-gray-600">{c.notes}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <CharacterFormModal
        open={showCreate}
        title="添加人物"
        form={form}
        setForm={setForm}
        onConfirm={handleCreate}
        onCancel={() => {
          setShowCreate(false)
          setForm(emptyForm)
        }}
      />

      <CharacterFormModal
        open={!!editingId}
        title="编辑人物"
        form={form}
        setForm={setForm}
        onConfirm={handleUpdate}
        onCancel={() => {
          setEditingId(null)
          setForm(emptyForm)
        }}
      />

      <Modal
        open={showGenerate}
        onClose={() => setShowGenerate(false)}
        title="AI 生成人物"
      >
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              描述
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={4}
              value={genDesc}
              onChange={(e) => setGenDesc(e.target.value)}
              placeholder="描述你想要的人物特征，如：一个表面冷漠内心温柔的剑客，出身名门却流落江湖..."
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setShowGenerate(false)}
            >
              取消
            </Button>
            <Button onClick={handleGenerate}>生成</Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={showImport}
        onClose={() => setShowImport(false)}
        title="一键导入人物"
      >
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-sm text-gray-500">
              粘贴包含人物信息的文本内容，AI 将自动提取并生成结构化人物档案。
              支持一次导入多个人物。
            </p>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              人物描述文本
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={12}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={`示例：\n林墨寒，男，28岁，江湖人称"寒剑"。出身江南林家，幼年家族遭灭门之祸，被隐世高人救走并传授剑法。性格外冷内热，对亲近之人极为护短，对敌人毫不留情。习惯独来独往，不轻易相信他人。弱点是过于执着于复仇，容易冲动。...\n\n苏婉清，女，24岁，医谷传人。温婉聪慧，医术精湛...`}
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">
              {importText.length > 0 && `${importText.length} 字`}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setShowImport(false)}
              >
                取消
              </Button>
              <Button
                onClick={handleImport}
                disabled={importing || !importText.trim()}
              >
                {importing ? (
                  <>
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" /> 导入中...
                  </>
                ) : (
                  <>
                    <FileUp className="mr-1 h-4 w-4" /> 开始导入
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </Modal>

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
    </div>
  )
}

interface FormModalProps {
  open: boolean
  title: string
  form: typeof emptyForm
  setForm: React.Dispatch<React.SetStateAction<typeof emptyForm>>
  onConfirm: () => void
  onCancel: () => void
}

const CharacterFormModal: React.FC<FormModalProps> = ({
  open,
  title,
  form,
  setForm,
  onConfirm,
  onCancel,
}) => {
  const update = (key: keyof typeof emptyForm, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  return (
    <Modal open={open} onClose={onCancel} title={title}>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        <div>
          <h4 className="mb-2 text-sm font-semibold text-gray-700">基础</h4>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="姓名"
              value={form.name}
              onChange={(e) => update('name', e.target.value)}
              placeholder="角色姓名"
            />
            <Input
              label="别名"
              value={form.aliases}
              onChange={(e) => update('aliases', e.target.value)}
              placeholder="多个用顿号分隔"
            />
          </div>
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold text-gray-700">基本信息</h4>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="年龄"
              value={form.age}
              onChange={(e) => update('age', e.target.value)}
              placeholder="如：25岁"
            />
            <Input
              label="性别"
              value={form.gender}
              onChange={(e) => update('gender', e.target.value)}
              placeholder="如：男"
            />
            <Input
              label="职业"
              value={form.occupation}
              onChange={(e) => update('occupation', e.target.value)}
              placeholder="如：剑客"
            />
          </div>
          <div className="mt-2">
            <label className="mb-1 block text-sm font-medium text-gray-700">
              背景
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={2}
              value={form.background}
              onChange={(e) => update('background', e.target.value)}
              placeholder="角色的身世背景..."
            />
          </div>
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold text-gray-700">性格</h4>
          <div className="space-y-2">
            <Input
              label="性格特征"
              value={form.traits}
              onChange={(e) => update('traits', e.target.value)}
              placeholder="如：外冷内热、重情重义"
            />
            <Input
              label="价值观"
              value={form.values}
              onChange={(e) => update('values', e.target.value)}
              placeholder="如：正义至上"
            />
            <Input
              label="习惯"
              value={form.habits}
              onChange={(e) => update('habits', e.target.value)}
              placeholder="如：独处时练剑"
            />
            <Input
              label="缺陷"
              value={form.flaws}
              onChange={(e) => update('flaws', e.target.value)}
              placeholder="如：过于固执"
            />
          </div>
        </div>

        <div>
          <h4 className="mb-2 text-sm font-semibold text-gray-700">成长弧线</h4>
          <div className="space-y-2">
            <Input
              label="初始状态"
              value={form.initial_state}
              onChange={(e) => update('initial_state', e.target.value)}
              placeholder="角色开始时的状态"
            />
            <Input
              label="发展方向"
              value={form.development_direction}
              onChange={(e) => update('development_direction', e.target.value)}
              placeholder="角色的成长方向"
            />
            <Input
              label="转折点"
              value={form.turning_point}
              onChange={(e) => update('turning_point', e.target.value)}
              placeholder="改变角色命运的关键事件"
            />
            <Input
              label="最终状态"
              value={form.final_state}
              onChange={(e) => update('final_state', e.target.value)}
              placeholder="角色最终的成长结果"
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            人物小传
          </label>
          <textarea
            className="w-full rounded-md border p-2 text-sm"
            rows={5}
            value={form.biography}
            onChange={(e) => update('biography', e.target.value)}
            placeholder="补充人物成长经历、关键过往、性格成因、重要关系、隐藏伤痕等细节..."
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            人物设定集
          </label>
          <textarea
            className="w-full rounded-md border p-2 text-sm"
            rows={5}
            value={form.setting_collection}
            onChange={(e) => update('setting_collection', e.target.value)}
            placeholder="记录不需要进入 AI 编写输入的补充设定、创作备忘、隐藏信息、后续安排等..."
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            备注
          </label>
          <textarea
            className="w-full rounded-md border p-2 text-sm"
            rows={2}
            value={form.notes}
            onChange={(e) => update('notes', e.target.value)}
            placeholder="其他补充信息..."
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button onClick={onConfirm} disabled={!form.name.trim()}>
            {title === '添加人物' ? '创建' : '保存'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
