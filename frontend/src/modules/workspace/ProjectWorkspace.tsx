import React, { useState, useEffect, useLayoutEffect, useRef } from 'react'
import { useNavigate, useLocation, useParams, useOutlet } from 'react-router-dom'
import { useProjectStore } from '@/stores/projectStore'
import {
  FileText,
  Users,
  Shield,
  Download,
  Menu,
  X,
  ArrowLeft,
  Settings,
  PenLine,
  MessageSquare,
  MapPinned,
} from 'lucide-react'

const workspaceNavItems = [
  { path: 'outline', label: '大纲', icon: FileText },
  { path: 'characters', label: '人物', icon: Users },
  { path: 'scenes', label: '场景', icon: MapPinned },
  { path: 'novel', label: '小说内容', icon: PenLine },
  { path: 'discussion', label: '小说讨论', icon: MessageSquare },
  { path: 'consistency', label: '一致性', icon: Shield },
  { path: 'export', label: '导出', icon: Download },
]

const getWorkspaceSection = (pathname: string, projectId?: string) => {
  if (!projectId) return ''
  const projectPrefix = `/projects/${projectId}/`
  const relativePath = pathname.startsWith(projectPrefix)
    ? pathname.slice(projectPrefix.length)
    : ''
  return relativePath.split('/')[0] || 'outline'
}

const getWorkspaceCacheKey = (pathname: string, projectId?: string) => {
  if (!projectId) return pathname
  const section = getWorkspaceSection(pathname, projectId)
  if (section === 'chapters') {
    return `${projectId}:${pathname}`
  }
  return `${projectId}:${section}`
}

export const ProjectWorkspace: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const outlet = useOutlet()
  const { currentProject, setCurrentProject, fetchProjects } = useProjectStore()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const mainRef = useRef<HTMLElement | null>(null)
  const outletCacheRef = useRef<Map<string, React.ReactElement>>(new Map())
  const scrollPositionsRef = useRef<Record<string, number>>({})
  const lastProjectIdRef = useRef<string | undefined>(projectId)

  if (lastProjectIdRef.current !== projectId) {
    outletCacheRef.current.clear()
    scrollPositionsRef.current = {}
    lastProjectIdRef.current = projectId
  }

  useEffect(() => {
    if (projectId && (!currentProject || currentProject.id !== projectId)) {
      fetchProjects().then(() => {
        const project = useProjectStore
          .getState()
          .projects.find((p) => p.id === projectId)
        if (project) setCurrentProject(project)
      })
    }
  }, [projectId])

  const currentSection = getWorkspaceSection(location.pathname, projectId)
  const activeCacheKey = getWorkspaceCacheKey(location.pathname, projectId)

  if (outlet && activeCacheKey && !outletCacheRef.current.has(activeCacheKey)) {
    outletCacheRef.current.set(activeCacheKey, outlet)
  }

  useLayoutEffect(() => {
    const main = mainRef.current
    if (!main || !activeCacheKey) return

    main.scrollTop = scrollPositionsRef.current[activeCacheKey] || 0

    return () => {
      scrollPositionsRef.current[activeCacheKey] = main.scrollTop
    }
  }, [activeCacheKey])

  return (
    <div className="flex h-screen bg-gray-50">
      <aside
        className={`flex flex-col border-r bg-white transition-width ${
          sidebarOpen ? 'w-56' : 'w-14'
        }`}
      >
        <div className="flex items-center justify-between border-b p-3">
          {sidebarOpen && (
            <span className="text-sm font-bold text-gray-700">NWA</span>
          )}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="text-gray-400 hover:text-gray-600"
          >
            {sidebarOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>

        {sidebarOpen && currentProject && (
          <div className="border-b p-3">
            <button
              onClick={() => navigate('/')}
              className="mb-1 flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
            >
              <ArrowLeft className="h-3 w-3" /> 返回项目列表
            </button>
            <p className="truncate text-sm font-medium text-blue-600">
              {currentProject.name}
            </p>
          </div>
        )}

        <nav className="flex-1 space-y-1 p-2">
          {workspaceNavItems.map((item) => {
            const Icon = item.icon
            const active = currentSection === item.path
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors ${
                  active
                    ? 'bg-blue-50 text-blue-600'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <Icon className="h-4 w-4 flex-shrink-0" />
                {sidebarOpen && <span>{item.label}</span>}
              </button>
            )
          })}
        </nav>
        <div className="border-t p-2">
          <button
            onClick={() => navigate('/settings')}
            className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-gray-500 transition-colors hover:bg-gray-50 hover:text-gray-700"
          >
            <Settings className="h-4 w-4 flex-shrink-0" />
            {sidebarOpen && <span>系统设置</span>}
          </button>
        </div>
      </aside>

      <main ref={mainRef} className="flex-1 overflow-auto">
        {Array.from(outletCacheRef.current.entries()).map(([key, element]) => (
          <div
            key={key}
            className={key === activeCacheKey ? 'h-full' : 'hidden'}
          >
            {element}
          </div>
        ))}
      </main>
    </div>
  )
}
