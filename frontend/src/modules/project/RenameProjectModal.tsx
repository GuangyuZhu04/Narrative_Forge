import React, { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { useProjectStore } from '@/stores/projectStore'
import type { Project } from '@/types'

interface RenameProjectModalProps {
  open: boolean
  project: Project | null
  onClose: () => void
}

export const RenameProjectModal: React.FC<RenameProjectModalProps> = ({
  open,
  project,
  onClose,
}) => {
  if (!open || !project) return null

  return (
    <RenameProjectForm
      key={project.id}
      project={project}
      onClose={onClose}
    />
  )
}

interface RenameProjectFormProps {
  project: Project
  onClose: () => void
}

const RenameProjectForm: React.FC<RenameProjectFormProps> = ({
  project,
  onClose,
}) => {
  const updateProject = useProjectStore((s) => s.updateProject)
  const [name, setName] = useState(project.name)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const trimmedName = name.trim()
  const unchanged = trimmedName === project.name
  const canSave = Boolean(trimmedName && !unchanged && !saving)

  const handleClose = () => {
    if (!saving) onClose()
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!trimmedName) {
      setError('项目名称不能为空')
      return
    }

    if (unchanged) {
      onClose()
      return
    }

    setSaving(true)
    setError('')
    try {
      await updateProject(project.id, { name: trimmedName })
      onClose()
    } catch {
      setError('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={handleClose} title="修改项目名称">
      <form className="space-y-4" onSubmit={handleSubmit}>
        <Input
          autoFocus
          label="项目名称"
          maxLength={200}
          value={name}
          error={error}
          onChange={(event) => {
            setName(event.target.value)
            if (error) setError('')
          }}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={handleClose}>
            取消
          </Button>
          <Button type="submit" disabled={!canSave}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
