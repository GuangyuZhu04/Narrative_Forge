import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ProjectList } from '@/modules/project/ProjectList'
import { ProjectWorkspace } from '@/modules/workspace/ProjectWorkspace'
import { OutlineEditor } from '@/modules/outline/OutlineEditor'
import { CharacterManager } from '@/modules/character/CharacterManager'
import { SceneManager } from '@/modules/scene/SceneManager'
import { ChapterEditor } from '@/modules/chapter/ChapterEditor'
import { NovelContent } from '@/modules/novel/NovelContent'
import { NovelDiscussion } from '@/modules/discussion/NovelDiscussion'
import { ConsistencyReport } from '@/modules/consistency/ConsistencyReport'
import { LLMConfigPanel } from '@/modules/llm-config/LLMConfigPanel'
import { ExportPanel } from '@/modules/export/ExportPanel'

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:projectId" element={<ProjectWorkspace />}>
          <Route path="outline" element={<OutlineEditor />} />
          <Route path="characters" element={<CharacterManager />} />
          <Route path="scenes" element={<SceneManager />} />
          <Route path="chapters/:chapterId" element={<ChapterEditor />} />
          <Route path="novel" element={<NovelContent />} />
          <Route path="discussion" element={<NovelDiscussion />} />
          <Route path="consistency" element={<ConsistencyReport />} />
          <Route path="export" element={<ExportPanel />} />
        </Route>
        <Route path="/settings" element={<LLMConfigPanel />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
