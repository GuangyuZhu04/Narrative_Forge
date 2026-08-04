import { create } from 'zustand'

export type AgentInputDraftTarget = 'generate' | 'continue_edit'

export interface AgentInputDraft {
  id: number
  projectId: string
  target: AgentInputDraftTarget
  content: string
  sourceTitle: string
}

interface AgentInputDraftState {
  draft: AgentInputDraft | null
  publishDraft: (draft: Omit<AgentInputDraft, 'id'>) => void
  clearDraft: (draftId: number) => void
}

let nextDraftId = 0

export const useAgentInputDraftStore = create<AgentInputDraftState>((set) => ({
  draft: null,
  publishDraft: (draft) => {
    nextDraftId += 1
    set({ draft: { ...draft, id: nextDraftId } })
  },
  clearDraft: (draftId) =>
    set((state) =>
      state.draft?.id === draftId ? { draft: null } : state
    ),
}))
