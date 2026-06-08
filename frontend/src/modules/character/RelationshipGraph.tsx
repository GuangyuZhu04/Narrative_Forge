import React, { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Character, CharacterRelationship } from '@/types'

const COLORS: Record<string, string> = {
  FAMILY: '#ef4444',
  FRIEND: '#22c55e',
  ENEMY: '#dc2626',
  LOVER: '#ec4899',
  MENTOR: '#8b5cf6',
  SUBORDINATE: '#f59e0b',
  ALLY: '#06b6d4',
  RIVAL: '#f97316',
  OTHER: '#6b7280',
}

interface Props {
  characters: Character[]
  relationships: CharacterRelationship[]
}

export const RelationshipGraph: React.FC<Props> = ({
  characters,
  relationships,
}) => {
  const nodes: Node[] = useMemo(() => {
    const step = (2 * Math.PI) / Math.max(characters.length, 1)
    return characters.map((c, i) => ({
      id: c.id,
      type: 'default',
      position: {
        x: 300 + 250 * Math.cos(step * i - Math.PI / 2),
        y: 300 + 250 * Math.sin(step * i - Math.PI / 2),
      },
      data: { label: c.name },
    }))
  }, [characters])

  const edges: Edge[] = useMemo(
    () =>
      relationships.map((r) => ({
        id: r.id,
        source: r.source_id,
        target: r.target_id,
        label: r.description || r.relationship_type,
        style: {
          stroke: COLORS[r.relationship_type] || COLORS.OTHER,
          strokeWidth: Math.max(1, r.intensity / 3),
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: COLORS[r.relationship_type] || COLORS.OTHER,
        },
      })),
    [relationships]
  )

  return (
    <div className="h-[600px] w-full rounded-lg border">
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
