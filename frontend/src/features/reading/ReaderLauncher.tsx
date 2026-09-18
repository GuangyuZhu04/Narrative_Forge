import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { ReadingMode } from './ReadingMode'

interface Props { projectId: string; chapterId?: string; content?: string; disabled?: boolean }
export function ReaderLauncher({ projectId, chapterId, content, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const [openedAt, setOpenedAt] = useState('')
  const { pathname } = useLocation()
  return <>
    <Button variant="outline" size="sm" disabled={disabled} onClick={() => { setOpenedAt(pathname); setOpen(true) }}><BookOpen className="mr-1 h-4 w-4" />阅读模式</Button>
    {open && openedAt === pathname && <ReadingMode projectId={projectId} initialChapterId={chapterId} draftContent={content} onClose={() => setOpen(false)} />}
  </>
}
