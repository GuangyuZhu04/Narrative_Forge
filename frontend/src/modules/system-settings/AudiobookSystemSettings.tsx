import React, { useEffect, useState } from 'react'
import { Headphones, LoaderCircle } from 'lucide-react'
import { Select } from '@/components/ui/Select'
import { AudiobookPanel } from '@/modules/audiobook/AudiobookPanel'
import { useProjectStore } from '@/stores/projectStore'

export const AudiobookSystemSettings: React.FC = () => {
  const { projects, currentProject, loading, fetchProjects } = useProjectStore()
  const [selectedProjectId, setSelectedProjectId] = useState(
    currentProject?.id || ''
  )

  useEffect(() => {
    void fetchProjects()
  }, [fetchProjects])

  const effectiveProjectId =
    (selectedProjectId &&
      projects.some((project) => project.id === selectedProjectId) &&
      selectedProjectId) ||
    (currentProject &&
      projects.some((project) => project.id === currentProject.id) &&
      currentProject.id) ||
    projects[0]?.id ||
    ''

  if (loading && projects.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center gap-2 text-sm text-gray-500">
        <LoaderCircle className="h-4 w-4 animate-spin" /> 加载项目...
      </div>
    )
  }

  if (projects.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-lg border border-dashed bg-white text-center">
        <Headphones className="mb-3 h-12 w-12 text-gray-300" />
        <p className="text-sm text-gray-500">请先创建项目，再配置有声书。</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border bg-white p-4 shadow-sm">
        <div className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <Select
            label="配置所属项目"
            value={effectiveProjectId}
            onChange={(event) => setSelectedProjectId(event.target.value)}
            options={projects.map((project) => ({
              value: project.id,
              label: project.name,
            }))}
          />
          <p className="pb-2 text-xs leading-5 text-gray-500">
            API、FFmpeg 开关、旁白音色和人物音色均按项目保存。这里与项目内“有声书”页面使用同一份配置，任一处保存后另一处刷新即可看到。
          </p>
        </div>
      </section>

      <AudiobookPanel
        key={effectiveProjectId}
        projectIdOverride={effectiveProjectId}
        settingsOnly
        embedded
      />
    </div>
  )
}
