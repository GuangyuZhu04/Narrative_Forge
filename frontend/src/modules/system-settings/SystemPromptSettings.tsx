import React, { useEffect, useMemo, useState } from 'react'
import { RotateCcw, Save, SlidersHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { systemSettingsApi } from '@/services/api'
import type { SystemPromptSetting } from '@/types'

type PromptResponse = { data: SystemPromptSetting[] }

export const SystemPromptSettings: React.FC = () => {
  const [settings, setSettings] = useState<SystemPromptSetting[]>([])
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    setLoading(true)
    try {
      const result = (await systemSettingsApi.listPrompts()) as unknown as PromptResponse
      const data = result.data || []
      setSettings(data)
      const nextSelectedKey = selectedKey || data[0]?.key || null
      setSelectedKey(nextSelectedKey)
      setDraft(data.find((item) => item.key === nextSelectedKey)?.value || '')
    } finally {
      setLoading(false)
    }
  }

  const grouped = useMemo(() => {
    return settings.reduce<Record<string, SystemPromptSetting[]>>((acc, item) => {
      if (!acc[item.category]) acc[item.category] = []
      acc[item.category].push(item)
      return acc
    }, {})
  }, [settings])

  const selected = settings.find((item) => item.key === selectedKey) || null
  const dirty = Boolean(selected && draft !== selected.value)
  const isNumberSetting = selected?.value_type === 'number'

  const selectSetting = (item: SystemPromptSetting) => {
    setSelectedKey(item.key)
    setDraft(item.value)
    setMessage('')
  }

  const replaceSetting = (updated: SystemPromptSetting) => {
    setSettings((items) =>
      items.map((item) => (item.key === updated.key ? updated : item))
    )
    setSelectedKey(updated.key)
    setDraft(updated.value)
  }

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setMessage('')
    try {
      const updated = (await systemSettingsApi.updatePrompt(
        selected.key,
        draft
      )) as unknown as SystemPromptSetting
      replaceSetting(updated)
      setMessage('已保存')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!selected) return
    setSaving(true)
    setMessage('')
    try {
      const updated = (await systemSettingsApi.resetPrompt(
        selected.key
      )) as unknown as SystemPromptSetting
      replaceSetting(updated)
      setMessage('已恢复默认')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-500">
        加载中...
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 gap-4">
      <aside className="w-72 shrink-0 overflow-auto border-r pr-4">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category} className="mb-5">
            <div className="mb-2 px-1 text-xs font-semibold text-gray-400">
              {category}
            </div>
            <div className="space-y-1">
              {items.map((item) => {
                const active = item.key === selectedKey
                return (
                  <button
                    key={item.key}
                    onClick={() => selectSetting(item)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      active
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <SlidersHorizontal className="h-4 w-4 shrink-0" />
                      <span className="truncate font-medium">{item.title}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
                      <span className="truncate">{item.key}</span>
                      {item.is_custom && (
                        <span className="shrink-0 rounded bg-blue-100 px-1.5 py-0.5 text-blue-700">
                          自定义
                        </span>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        {selected ? (
          <>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold text-gray-800">
                    {selected.title}
                  </h2>
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      selected.is_custom
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {selected.is_custom ? '自定义' : '默认'}
                  </span>
                </div>
                <p className="mt-1 text-sm text-gray-500">
                  {selected.description}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {message && (
                  <span className="text-xs text-green-600">{message}</span>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleReset}
                  disabled={saving || !selected.is_custom}
                >
                  <RotateCcw className="mr-1 h-4 w-4" /> 恢复默认
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={saving || !dirty}
                >
                  <Save className="mr-1 h-4 w-4" /> 保存修改
                </Button>
              </div>
            </div>

            {isNumberSetting ? (
              <div className="rounded-md border bg-white p-4">
                <label className="mb-2 block text-sm font-medium text-gray-700">
                  当前值
                </label>
                <input
                  type="number"
                  className="w-48 rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={draft}
                  min={selected.min_value ?? undefined}
                  max={selected.max_value ?? undefined}
                  step={selected.step ?? undefined}
                  onChange={(event) => {
                    setDraft(event.target.value)
                    setMessage('')
                  }}
                />
                <div className="mt-3 text-xs leading-relaxed text-gray-500">
                  {selected.min_value !== null && selected.max_value !== null
                    ? `允许范围：${selected.min_value} ~ ${selected.max_value}`
                    : '允许范围：未限制'}
                  {selected.step !== null ? `，步长：${selected.step}` : ''}
                  {selected.integer_only ? '，必须为整数。' : '。'}
                </div>
              </div>
            ) : (
              <textarea
                className="min-h-[460px] flex-1 resize-none rounded-md border border-gray-300 bg-white p-3 font-mono text-sm leading-relaxed text-gray-800 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  setMessage('')
                }}
              />
            )}

            <details className="mt-3 shrink-0 rounded-md border bg-white p-3">
              <summary className="cursor-pointer text-sm font-medium text-gray-600">
                默认内容
              </summary>
              <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-gray-500">
                {selected.default_value}
              </pre>
            </details>
          </>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-500">
            暂无系统设置
          </div>
        )}
      </section>
    </div>
  )
}
