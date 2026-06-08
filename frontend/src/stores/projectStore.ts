import { create } from 'zustand'
import { projectApi } from '@/services/api'
import type { Project } from '@/types'

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  loading: boolean
  fetchProjects: (status?: string) => Promise<void>
  createProject: (data: Partial<Project>) => Promise<Project>
  setCurrentProject: (project: Project | null) => void
  updateProject: (id: string, data: Partial<Project>) => Promise<void>
  deleteProject: (id: string) => Promise<void>
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProject: null,
  loading: false,

  fetchProjects: async (status?: string) => {
    set({ loading: true })
    try {
      const result = (await projectApi.list(
        status ? { status } : undefined
      )) as unknown as { data: Project[] }
      set({ projects: result.data || (result as unknown as Project[]) })
    } finally {
      set({ loading: false })
    }
  },

  createProject: async (data) => {
    const project = (await projectApi.create(data)) as unknown as Project
    set((s) => ({ projects: [...s.projects, project] }))
    return project
  },

  setCurrentProject: (project) => set({ currentProject: project }),

  updateProject: async (id, data) => {
    const updated = (await projectApi.update(id, data)) as unknown as Project
    set((s) => ({
      projects: s.projects.map((p) => (p.id === id ? updated : p)),
      currentProject: s.currentProject?.id === id ? updated : s.currentProject,
    }))
  },

  deleteProject: async (id) => {
    await projectApi.delete(id)
    set((s) => ({
      projects: s.projects.filter((p) => p.id !== id),
      currentProject: s.currentProject?.id === id ? null : s.currentProject,
    }))
  },
}))
