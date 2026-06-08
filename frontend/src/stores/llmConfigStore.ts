import { create } from 'zustand'
import { llmConfigApi } from '@/services/api'
import type { LLMConfig } from '@/types'

interface LLMConfigState {
  configs: LLMConfig[]
  activeConfigId: string | null
  loading: boolean
  fetchConfigs: () => Promise<void>
  createConfig: (data: Record<string, unknown>) => Promise<LLMConfig>
  updateConfig: (id: string, data: Record<string, unknown>) => Promise<void>
  deleteConfig: (id: string) => Promise<void>
  testConfig: (id: string) => Promise<Record<string, unknown>>
  setActiveConfig: (id: string | null) => void
}

export const useLLMConfigStore = create<LLMConfigState>((set) => ({
  configs: [],
  activeConfigId: null,
  loading: false,

  fetchConfigs: async () => {
    set({ loading: true })
    try {
      const result = (await llmConfigApi.list()) as unknown as {
        data: LLMConfig[]
      }
      const configs = result.data || []
      const active = configs.find((c) => c.is_active)
      set({
        configs,
        activeConfigId: active?.id || null,
      })
    } finally {
      set({ loading: false })
    }
  },

  createConfig: async (data) => {
    const config = (await llmConfigApi.create(
      data
    )) as unknown as LLMConfig
    set((s) => ({ configs: [...s.configs, config] }))
    return config
  },

  updateConfig: async (id, data) => {
    const updated = (await llmConfigApi.update(
      id,
      data
    )) as unknown as LLMConfig
    set((s) => ({
      configs: s.configs.map((c) => (c.id === id ? updated : c)),
    }))
  },

  deleteConfig: async (id) => {
    await llmConfigApi.delete(id)
    set((s) => ({
      configs: s.configs.filter((c) => c.id !== id),
      activeConfigId: s.activeConfigId === id ? null : s.activeConfigId,
    }))
  },

  testConfig: async (id) => {
    return (await llmConfigApi.test(id)) as unknown as Record<string, unknown>
  },

  setActiveConfig: (id) => set({ activeConfigId: id }),
}))
