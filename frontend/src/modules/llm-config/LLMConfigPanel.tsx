import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { llmConfigApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { Select } from '@/components/ui/Select'
import { SystemPromptSettings } from '@/modules/system-settings/SystemPromptSettings'
import {
  Plus,
  Trash2,
  XCircle,
  Settings,
  ArrowLeft,
  Zap,
  SlidersHorizontal,
} from 'lucide-react'
import type { LLMConfig } from '@/types'

const ACTIVE_LLM_KEY = 'nwa_active_llm_config_id'

const PROVIDER_PRESETS = {
  deepseek: {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    models: ['deepseek-v4-pro'],
    messageFormat: 'OpenAI Chat Completions: messages[]',
  },
  openai: {
    label: 'OpenAI',
    baseUrl: 'https://api.openai.com/v1',
    models: ['gpt-5.5'],
    messageFormat: 'Responses API: instructions + input[]',
  },
  anthropic: {
    label: 'Anthropic',
    baseUrl: 'https://api.anthropic.com/v1',
    models: ['claude-sonnet-4-6', 'claude-opus-4-8', 'claude-haiku-4-5'],
    messageFormat: 'Messages API: system + messages[]',
  },
  google: {
    label: 'Google Gemini',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta',
    models: [
      'gemini-3.5-flash',
      'gemini-3.5-flash-lite-preview',
      'gemini-3.1-pro',
      'gemini-3.0-flash',
      'gemini-3.1-flash-lite',
    ],
    messageFormat: 'Gemini API: systemInstruction + contents[]',
  },
  openai_compatible: {
    label: 'OpenAI Compatible',
    baseUrl: 'https://api.openai.com/v1',
    models: ['deepseek-v4-pro', 'gpt-5.5'],
    messageFormat: 'OpenAI Chat Completions: messages[]',
  },
}

type ProviderKey = keyof typeof PROVIDER_PRESETS

const providerOptions = Object.entries(PROVIDER_PRESETS).map(([value, preset]) => ({
  value,
  label: preset.label,
}))

const getProviderPreset = (provider: string) =>
  PROVIDER_PRESETS[provider as ProviderKey] || PROVIDER_PRESETS.openai_compatible

export const LLMConfigPanel: React.FC = () => {
  const navigate = useNavigate()
  const [configs, setConfigs] = useState<LLMConfig[]>([])
  const [activeId, setActiveId] = useState<string | null>(
    localStorage.getItem(ACTIVE_LLM_KEY)
  )
  const [showCreate, setShowCreate] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'llm' | 'prompts'>('llm')
  const [newConfig, setNewConfig] = useState({
    provider: 'deepseek',
    api_key: '',
    base_url: 'https://api.deepseek.com',
    model_name: 'deepseek-v4-pro',
  })
  const selectedPreset = getProviderPreset(newConfig.provider)
  const modelDatalistId = 'llm-model-presets'

  useEffect(() => {
    loadConfigs()
  }, [])

  const loadConfigs = async () => {
    const result = (await llmConfigApi.list()) as unknown as {
      data: LLMConfig[]
    }
    setConfigs(result.data || [])
  }

  const handleCreate = async () => {
    if (!newConfig.api_key.trim()) return
    const created = (await llmConfigApi.create(newConfig)) as unknown as LLMConfig
    setNewConfig({
      provider: 'deepseek',
      api_key: '',
      base_url: 'https://api.deepseek.com',
      model_name: 'deepseek-v4-pro',
    })
    setShowCreate(false)
    await loadConfigs()
    if (created.id) {
      handleSetActive(created.id)
    }
  }

  const handleProviderChange = (provider: string) => {
    const preset = getProviderPreset(provider)
    setNewConfig({
      ...newConfig,
      provider,
      base_url: preset.baseUrl,
      model_name: preset.models[0],
    })
  }

  const handleSetActive = (id: string) => {
    localStorage.setItem(ACTIVE_LLM_KEY, id)
    setActiveId(id)
  }

  const handleTest = async (id: string) => {
    setTesting(id)
    try {
      const result = (await llmConfigApi.test(id)) as unknown as {
        success: boolean
        message: string
      }
      alert(result.success ? '连接成功！' : `连接失败：${result.message}`)
    } finally {
      setTesting(null)
    }
  }

  const handleDelete = async (id: string) => {
    await llmConfigApi.delete(id)
    if (activeId === id) {
      localStorage.removeItem(ACTIVE_LLM_KEY)
      setActiveId(null)
    }
    loadConfigs()
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/')}
          >
            <ArrowLeft className="mr-1 h-4 w-4" /> 返回
          </Button>
          <h1 className="text-xl font-bold text-gray-800">系统设置</h1>
        </div>
        {activeTab === 'llm' && (
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" /> 添加配置
          </Button>
        )}
      </header>

      <main className="flex-1 overflow-auto p-6">
        <div className="mb-5 flex gap-2">
          <Button
            variant={activeTab === 'llm' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setActiveTab('llm')}
          >
            <Settings className="mr-1 h-4 w-4" /> 模型配置
          </Button>
          <Button
            variant={activeTab === 'prompts' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setActiveTab('prompts')}
          >
            <SlidersHorizontal className="mr-1 h-4 w-4" /> 系统 Prompt
          </Button>
        </div>

        {activeTab === 'prompts' ? (
          <SystemPromptSettings />
        ) : configs.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <Settings className="mx-auto mb-4 h-16 w-16 text-gray-300" />
              <p className="mb-4 text-gray-500">暂无 LLM 配置</p>
              <Button onClick={() => setShowCreate(true)}>
                <Plus className="mr-2 h-4 w-4" /> 添加第一个配置
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {configs.map((c) => {
              const isActive = activeId === c.id
              return (
                <div
                  key={c.id}
                  className={`flex items-center justify-between rounded-lg border bg-white p-4 shadow-sm transition-all ${
                    isActive ? 'border-blue-300 ring-2 ring-blue-100' : ''
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Settings className="h-5 w-5 text-gray-400" />
                    <div>
                      <h3 className="font-semibold">{c.model_name}</h3>
                      <p className="text-sm text-gray-500">
                        {c.provider} · {c.base_url}
                      </p>
                    </div>
                    {isActive ? (
                      <span className="flex items-center gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                        <Zap className="h-3 w-3" /> 使用中
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                        <XCircle className="h-3 w-3" /> 未启用
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!isActive && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleSetActive(c.id)}
                      >
                        <Zap className="mr-1 h-3 w-3" /> 设为活跃
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleTest(c.id)}
                      disabled={testing === c.id}
                    >
                      {testing === c.id ? '测试中...' : '测试连接'}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(c.id)}
                    >
                      <Trash2 className="h-4 w-4 text-red-400" />
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </main>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="添加 LLM 配置"
      >
        <div className="space-y-4">
          <Select
            label="服务商"
            value={newConfig.provider}
            onChange={(e) => handleProviderChange(e.target.value)}
            options={providerOptions}
          />
          <div className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
            <p>消息格式：{selectedPreset.messageFormat}</p>
            <p className="mt-1">
              推荐模型：{selectedPreset.models.join(' / ')}
            </p>
          </div>
          <Input
            label="API 密钥"
            type="password"
            value={newConfig.api_key}
            onChange={(e) =>
              setNewConfig({ ...newConfig, api_key: e.target.value })
            }
            placeholder="sk-..."
          />
          <Input
            label="Base URL"
            value={newConfig.base_url}
            onChange={(e) =>
              setNewConfig({ ...newConfig, base_url: e.target.value })
            }
          />
          <Input
            label="模型名称"
            value={newConfig.model_name}
            onChange={(e) =>
              setNewConfig({ ...newConfig, model_name: e.target.value })
            }
            list={modelDatalistId}
          />
          <datalist id={modelDatalistId}>
            {selectedPreset.models.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              取消
            </Button>
            <Button onClick={handleCreate} disabled={!newConfig.api_key.trim()}>
              创建
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
