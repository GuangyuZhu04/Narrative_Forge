import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProjectStore } from '@/stores/projectStore'
import { projectApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { Plus, Trash2, Settings, FolderOpen } from 'lucide-react'

export const ProjectList: React.FC = () => {
  const navigate = useNavigate()
  const { projects, fetchProjects, setCurrentProject } = useProjectStore()
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')

  useEffect(() => {
    fetchProjects()
  }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    await projectApi.create({ name: newName, description: newDesc })
    setNewName('')
    setNewDesc('')
    setShowCreate(false)
    fetchProjects()
  }

  const handleDelete = async (id: string) => {
    await projectApi.delete(id)
    fetchProjects()
  }

  const handleOpen = (project: Record<string, unknown>) => {
    setCurrentProject(project as unknown as Parameters<typeof setCurrentProject>[0])
    navigate(`/projects/${project.id}/outline`)
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <h1 className="text-xl font-bold text-gray-800">
          文脉工坊
          <span className="ml-2 text-sm font-normal text-gray-500">
            Narrative Forge
          </span>
        </h1>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/settings')}
          >
            <Settings className="mr-1 h-4 w-4" /> LLM 配置
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="mr-1 h-4 w-4" /> 新建项目
          </Button>
        </div>
      </header>
      <main className="flex-1 overflow-auto p-6">
        {projects.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <FolderOpen className="mx-auto mb-4 h-16 w-16 text-gray-300" />
              <p className="mb-4 text-gray-500">暂无写作项目</p>
              <Button onClick={() => setShowCreate(true)}>
                <Plus className="mr-2 h-4 w-4" /> 创建第一个项目
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div
                key={p.id}
                className="group cursor-pointer rounded-lg border bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
                onClick={() => handleOpen(p as unknown as Record<string, unknown>)}
              >
                <div className="flex items-start justify-between">
                  <h3 className="text-lg font-medium text-gray-800">
                    {p.name}
                  </h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(p.id)
                    }}
                  >
                    <Trash2 className="h-4 w-4 text-red-400" />
                  </Button>
                </div>
                {p.description && (
                  <p className="mt-2 text-sm text-gray-500 line-clamp-2">
                    {p.description}
                  </p>
                )}
                <p className="mt-3 text-xs text-gray-400">
                  创建于 {new Date(p.created_at).toLocaleDateString()}
                </p>
              </div>
            ))}
          </div>
        )}
      </main>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="新建写作项目"
      >
        <div className="space-y-4">
          <Input
            label="项目名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              项目描述
            </label>
            <textarea
              className="w-full rounded-md border p-2 text-sm"
              rows={3}
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowCreate(false)}>
              取消
            </Button>
            <Button onClick={handleCreate}>创建</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
