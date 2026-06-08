import React, { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useProjectStore } from '@/stores/projectStore'
import {
  FolderOpen,
  FileText,
  Users,
  Shield,
  Settings,
  Download,
  Menu,
  X,
} from 'lucide-react'

const navItems = [
  { path: '/', label: '项目', icon: FolderOpen },
  { path: '/outline', label: '大纲', icon: FileText },
  { path: '/characters', label: '人物', icon: Users },
  { path: '/consistency', label: '一致性', icon: Shield },
  { path: '/export', label: '导出', icon: Download },
  { path: '/settings', label: '设置', icon: Settings },
]

export const Layout: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { currentProject } = useProjectStore()
  const [sidebarOpen, setSidebarOpen] = useState(true)

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
            <p className="truncate text-sm font-medium text-blue-600">
              {currentProject.name}
            </p>
          </div>
        )}

        <nav className="flex-1 space-y-1 p-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const active = location.pathname === item.path
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
      </aside>

      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
