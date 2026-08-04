import { create } from 'zustand'
import { outlineApi } from '@/services/api'
import type { Outline, OutlineNode } from '@/types'

interface OutlineState {
  projectId: string | null
  outlines: Outline[]
  currentOutline: Outline | null
  currentTree: OutlineNode[]
  generating: boolean
  fetchOutlines: (projectId: string) => Promise<void>
  fetchTree: (projectId: string, outlineId: string) => Promise<void>
  generateOutline: (
    projectId: string,
    llmConfigId: string,
    params: Record<string, string>
  ) => Promise<Outline>
  expandNode: (
    projectId: string,
    llmConfigId: string,
    nodeId: string,
    params: Record<string, unknown>
  ) => Promise<OutlineNode[]>
  addNode: (
    projectId: string,
    outlineId: string,
    parentId: string | null,
    data: Partial<OutlineNode>
  ) => Promise<OutlineNode>
  updateNode: (projectId: string, nodeId: string, data: Partial<OutlineNode>) => Promise<void>
  deleteNode: (projectId: string, nodeId: string) => Promise<void>
  moveNode: (
    projectId: string,
    nodeId: string,
    newParentId: string | null,
    newOrder: number
  ) => Promise<void>
}

export const useOutlineStore = create<OutlineState>((set, get) => ({
  projectId: null,
  outlines: [],
  currentOutline: null,
  currentTree: [],
  generating: false,

  fetchOutlines: async (projectId) => {
    set((state) =>
      state.projectId === projectId
        ? state
        : {
            projectId,
            outlines: [],
            currentOutline: null,
            currentTree: [],
          }
    )

    const result = (await outlineApi.list(projectId)) as unknown as {
      data: Outline[]
    }
    if (get().projectId !== projectId) return

    const outlines = result.data || []
    set((state) => {
      const hasCurrentOutline =
        !!state.currentOutline &&
        state.currentOutline.project_id === projectId &&
        outlines.some((outline) => outline.id === state.currentOutline?.id)
      return {
        outlines,
        ...(hasCurrentOutline ? {} : { currentOutline: null, currentTree: [] }),
      }
    })
  },

  fetchTree: async (projectId, outlineId) => {
    const state = get()
    const outlineBelongsToProject = state.outlines.some(
      (outline) => outline.id === outlineId && outline.project_id === projectId
    )
    if (state.projectId !== projectId || !outlineBelongsToProject) return

    const result = (await outlineApi.getTree(projectId, outlineId)) as unknown as {
      outline: Outline
      tree: OutlineNode[]
    }
    if (
      get().projectId !== projectId ||
      result.outline.project_id !== projectId
    ) {
      return
    }
    set({
      currentOutline: result.outline,
      currentTree: result.tree || [],
    })
  },

  generateOutline: async (projectId, llmConfigId, params) => {
    set({ generating: true })
    try {
      const outline = (await outlineApi.generate(
        projectId,
        llmConfigId,
        params
      )) as unknown as Outline
      if (get().projectId === projectId && outline.project_id === projectId) {
        set((s) => ({
          outlines: [...s.outlines, outline],
          currentOutline: outline,
        }))
      }
      return outline
    } finally {
      set({ generating: false })
    }
  },

  expandNode: async (projectId, llmConfigId, nodeId, params) => {
    const result = (await outlineApi.expandNode(
      projectId,
      llmConfigId,
      nodeId,
      params
    )) as unknown as { data: OutlineNode[] }
    return result.data || []
  },

  addNode: async (projectId, outlineId, parentId, data) => {
    const node = (await outlineApi.addNode(projectId, {
      outline_id: outlineId,
      parent_id: parentId,
      ...data,
    })) as unknown as OutlineNode
    return node
  },

  updateNode: async (projectId, nodeId, data) => {
    await outlineApi.updateNode(projectId, nodeId, data)
  },

  deleteNode: async (projectId, nodeId) => {
    await outlineApi.deleteNode(projectId, nodeId)
  },

  moveNode: async (projectId, nodeId, newParentId, newOrder) => {
    await outlineApi.moveNode(projectId, nodeId, newParentId, newOrder)
  },
}))

export const refreshProjectOutlineData = async (
  projectId: string,
  preferredOutlineId?: string
) => {
  await useOutlineStore.getState().fetchOutlines(projectId)

  const state = useOutlineStore.getState()
  if (state.projectId !== projectId) return

  const targetOutlineId =
    (preferredOutlineId &&
    state.outlines.some((outline) => outline.id === preferredOutlineId)
      ? preferredOutlineId
      : null) ||
    state.currentOutline?.id ||
    state.outlines[0]?.id

  if (targetOutlineId) {
    await state.fetchTree(projectId, targetOutlineId)
  }
}
