import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProjectStore } from '@/stores/projectStore'
import { projectApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import { Input } from '@/components/ui/Input'
import { RenameProjectModal } from '@/modules/project/RenameProjectModal'
import type { Project } from '@/types'
import {
  Image as ImageIcon,
  ImagePlus,
  Pencil,
  Plus,
  Settings,
  Trash2,
  X,
  FolderOpen,
} from 'lucide-react'

export const ProjectList: React.FC = () => {
  const navigate = useNavigate()
  const { projects, fetchProjects, setCurrentProject } = useProjectStore()
  const [showCreate, setShowCreate] = useState(false)
  const [editingProject, setEditingProject] = useState<Project | null>(null)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newCoverFile, setNewCoverFile] = useState<File | null>(null)
  const [newCoverPreview, setNewCoverPreview] = useState<string | null>(null)
  const [createError, setCreateError] = useState('')
  const [coverBusyProjectId, setCoverBusyProjectId] = useState<string | null>(null)

  useEffect(() => {
    void fetchProjects()
  }, [fetchProjects])

  useEffect(() => {
    return () => {
      if (newCoverPreview) {
        window.URL.revokeObjectURL(newCoverPreview)
      }
    }
  }, [newCoverPreview])

  const resetCreateForm = () => {
    setNewName('')
    setNewDesc('')
    setNewCoverFile(null)
    setNewCoverPreview(null)
    setCreateError('')
  }

  const setCreateCover = (file: File | null) => {
    if (newCoverPreview) {
      window.URL.revokeObjectURL(newCoverPreview)
    }
    setNewCoverFile(file)
    setNewCoverPreview(file ? window.URL.createObjectURL(file) : null)
    setCreateError('')
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreateError('')
    try {
      const created = (await projectApi.create({
        name: newName,
        description: newDesc,
      })) as unknown as Project
      if (newCoverFile) {
        await projectApi.uploadCover(created.id, newCoverFile)
      }
      resetCreateForm()
      setShowCreate(false)
      fetchProjects()
    } catch {
      setCreateError('创建失败，请稍后重试')
    }
  }

  const handleDelete = async (id: string) => {
    await projectApi.delete(id)
    fetchProjects()
  }

  const handleCoverUpload = async (project: Project, file: File | null) => {
    if (!file) return
    if (!file.type.startsWith('image/')) return
    setCoverBusyProjectId(project.id)
    try {
      await projectApi.uploadCover(project.id, file)
      fetchProjects()
    } finally {
      setCoverBusyProjectId(null)
    }
  }

  const handleCoverDelete = async (project: Project) => {
    setCoverBusyProjectId(project.id)
    try {
      await projectApi.deleteCover(project.id)
      fetchProjects()
    } finally {
      setCoverBusyProjectId(null)
    }
  }

  const handleOpen = (project: Project) => {
    setCurrentProject(project)
    navigate(`/projects/${project.id}/outline`)
  }

  return (
    <div className="app-wallpaper-root flex h-screen flex-col bg-gray-50">
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
            <Settings className="mr-1 h-4 w-4" /> 系统设置
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
                onClick={() => handleOpen(p)}
              >
                <div className="flex gap-4">
                  <div className="flex h-32 w-24 flex-shrink-0 items-center justify-center overflow-hidden rounded-md border bg-gray-100">
                    {p.cover_url ? (
                      <img
                        src={p.cover_url}
                        alt={`${p.name}封面`}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <ImageIcon className="h-8 w-8 text-gray-300" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between">
                      <h3 className="min-w-0 flex-1 truncate text-lg font-medium text-gray-800">
                        {p.name}
                      </h3>
                      <div className="ml-2 flex flex-shrink-0 gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          title="修改项目名称"
                          aria-label="修改项目名称"
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditingProject(p)
                          }}
                        >
                          <Pencil className="h-4 w-4 text-gray-400" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          title="删除项目"
                          aria-label="删除项目"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(p.id)
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-red-400" />
                        </Button>
                      </div>
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
                </div>
                <div
                  className="mt-4 flex flex-wrap gap-2"
                  onClick={(event) => event.stopPropagation()}
                >
                  <label
                    className={`inline-flex cursor-pointer items-center justify-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium transition-colors hover:bg-gray-50 ${
                      coverBusyProjectId === p.id
                        ? 'pointer-events-none opacity-50'
                        : ''
                    }`}
                    title={p.cover_url ? '更换项目封面' : '添加项目封面'}
                  >
                    <ImagePlus className="mr-1 h-4 w-4" />
                    {p.cover_url ? '更换封面' : '添加封面'}
                    <input
                      className="hidden"
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      onChange={(event) => {
                        handleCoverUpload(p, event.currentTarget.files?.[0] || null)
                        event.currentTarget.value = ''
                      }}
                    />
                  </label>
                  {p.cover_url && (
                    <Button
                      variant="outline"
                      size="sm"
                      title="删除项目封面"
                      aria-label="删除项目封面"
                      disabled={coverBusyProjectId === p.id}
                      onClick={() => handleCoverDelete(p)}
                    >
                      <X className="mr-1 h-4 w-4" />
                      删除封面
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      <Modal
        open={showCreate}
        onClose={() => {
          setShowCreate(false)
          resetCreateForm()
        }}
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
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-700">
              小说封面
            </label>
            <div className="flex items-center gap-4">
              <div className="flex h-32 w-24 flex-shrink-0 items-center justify-center overflow-hidden rounded-md border bg-gray-100">
                {newCoverPreview ? (
                  <img
                    src={newCoverPreview}
                    alt="小说封面预览"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <ImageIcon className="h-8 w-8 text-gray-300" />
                )}
              </div>
              <div className="space-y-2">
                <label className="inline-flex cursor-pointer items-center justify-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium transition-colors hover:bg-gray-50">
                  <ImagePlus className="mr-1 h-4 w-4" />
                  {newCoverFile ? '更换封面' : '选择封面'}
                  <input
                    className="hidden"
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0] || null
                      if (file && !file.type.startsWith('image/')) {
                        setCreateError('请选择图片文件')
                        event.currentTarget.value = ''
                        return
                      }
                      setCreateCover(file)
                      event.currentTarget.value = ''
                    }}
                  />
                </label>
                {newCoverFile && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setCreateCover(null)}
                  >
                    <X className="mr-1 h-4 w-4" />
                    移除封面
                  </Button>
                )}
              </div>
            </div>
          </div>
          {createError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {createError}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowCreate(false)
                resetCreateForm()
              }}
            >
              取消
            </Button>
            <Button onClick={handleCreate}>创建</Button>
          </div>
        </div>
      </Modal>
      <RenameProjectModal
        open={Boolean(editingProject)}
        project={editingProject}
        onClose={() => setEditingProject(null)}
      />
    </div>
  )
}
