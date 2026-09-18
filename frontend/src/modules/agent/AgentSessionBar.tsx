import React, { useState } from 'react'
import { Pencil, Plus, Save, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import type { NovelAgentSession } from '@/types'

interface AgentSessionBarProps {
  sessions: NovelAgentSession[]
  activeSession: NovelAgentSession | null
  className?: string
  busy?: boolean
  onSelect: (sessionId: string) => void
  onCreate: () => void
  onRename: (name: string) => Promise<void>
  onDelete: () => Promise<void>
}

const statusLabel: Record<string, string> = {
  idle: '未执行',
  planning: '计划生成中',
  awaiting_confirmation: '等待确认',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

const SessionRenameEditor: React.FC<{
  initialName: string
  busy?: boolean
  onRename: (name: string) => Promise<void>
}> = ({ initialName, busy, onRename }) => {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(initialName)

  if (!editing) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => setEditing(true)}
      >
        <Pencil className="mr-1 h-3.5 w-3.5" />
        修改名称
      </Button>
    )
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      <input
        value={name}
        maxLength={200}
        disabled={busy}
        onChange={(event) => setName(event.target.value)}
        className="min-w-0 flex-1 rounded-md border px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <Button
        type="button"
        size="sm"
        disabled={busy || !name.trim()}
        onClick={async () => {
          await onRename(name.trim())
          setEditing(false)
        }}
      >
        <Save className="mr-1 h-3.5 w-3.5" />
        保存
      </Button>
    </div>
  )
}

export const AgentSessionBar: React.FC<AgentSessionBarProps> = ({
  sessions,
  activeSession,
  className,
  busy,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}) => {
  return (
    <div
      className={`rounded-md border border-gray-200 bg-white p-4 shadow-sm ${className || ''}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm font-medium text-gray-700">Agent Session</div>
        <select
          value={activeSession?.id || ''}
          disabled={busy || sessions.length === 0}
          onChange={(event) => onSelect(event.target.value)}
          className="min-w-[260px] flex-1 rounded-md border bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {sessions.length === 0 && <option value="">暂无会话</option>}
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.name} · {statusLabel[session.status] || session.status}
            </option>
          ))}
        </select>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={onCreate}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          新建会话
        </Button>
      </div>

      {activeSession && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          <span className="max-w-full truncate font-mono text-xs text-gray-400">
            ID: {activeSession.id}
          </span>
          <SessionRenameEditor
            key={`${activeSession.id}:${activeSession.name}`}
            initialName={activeSession.name}
            busy={busy}
            onRename={onRename}
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            className="text-red-500 hover:text-red-600"
            onClick={() => void onDelete()}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            删除会话
          </Button>
        </div>
      )}
    </div>
  )
}
