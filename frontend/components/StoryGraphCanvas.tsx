"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  Handle,
  Position,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type OnNodeDrag,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { NodeScriptPanel } from "@/components/NodeScriptPanel";
import { updateNodeLayout, type StoryGraph, type StoryNode } from "@/lib/api";

const kindColor: Record<string, string> = {
  root: "#3d8bfd",
  main: "#3ecf8e",
  branch: "#f0b429",
  ending: "#f07178",
};

function StoryNodeView({ data, selected }: NodeProps) {
  const kind = String(data.kind || "branch");
  const color = kindColor[kind] || "#9aa4b2";
  return (
    <div
      className="min-w-[180px] max-w-[240px] rounded-md border-2 bg-[#23262e] shadow-lg"
      style={{
        borderColor: selected ? "#f8fafc" : color,
        boxShadow: selected ? `0 0 0 1px ${color}` : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} className="!bg-zinc-400" />
      <div
        className="rounded-t-[4px] px-3 py-1 text-[11px] font-medium uppercase tracking-wide text-zinc-950"
        style={{ backgroundColor: color }}
      >
        {kind}
      </div>
      <div className="space-y-1 px-3 py-2">
        <div className="text-sm font-semibold text-zinc-100">{String(data.title)}</div>
        {data.summary ? (
          <div className="line-clamp-3 text-xs leading-relaxed text-zinc-400">
            {String(data.summary)}
          </div>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-zinc-400" />
    </div>
  );
}

const nodeTypes = { story: StoryNodeView };

type Props = {
  storyId: string;
  graph: StoryGraph | null;
  /** 最新事件 seq，用于在节点数不变时仍同步 title/script 等变更 */
  graphRevision?: number;
};

export function StoryGraphCanvas({ storyId, graph, graphRevision = 0 }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [didFit, setDidFit] = useState(false);
  const nodeCountRef = useRef(0);
  const localPosRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const dragMovedRef = useRef(false);
  const draggingRef = useRef(false);

  const inboundByNode = useMemo(() => {
    const map = new Map<string, string[]>();
    if (!graph) return map;
    for (const opt of graph.options) {
      const list = map.get(opt.to_node_id) || [];
      list.push(opt.label);
      map.set(opt.to_node_id, list);
    }
    return map;
  }, [graph]);

  useEffect(() => {
    if (!graph) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const count = Object.keys(graph.nodes).length;
    if (count !== nodeCountRef.current) {
      nodeCountRef.current = count;
      setDidFit(false);
    }
    const optionLabel = new Map<string, string>();
    for (const opt of graph.options) {
      optionLabel.set(`${opt.from_node_id}\0${opt.to_node_id}`, opt.label);
      if (opt.id) optionLabel.set(`id:${opt.id}`, opt.label);
    }

    setNodes((prev) => {
      const prevById = new Map(prev.map((n) => [n.id, n]));
      return Object.values(graph.nodes).map((n) => {
        const local = localPosRef.current.get(n.id);
        const existing = prevById.get(n.id);
        const position = local
          ? local
          : existing && draggingRef.current
            ? existing.position
            : { x: n.canvas_x || 0, y: n.canvas_y || 0 };
        return {
          id: n.id,
          type: "story",
          position,
          selected: n.id === selectedId,
          data: {
            title: n.title,
            summary: n.summary,
            kind: n.kind,
            script: n.script,
          },
        } as Node;
      });
    });

    setEdges(
      graph.edges.map((e) => {
        const label =
          (e.option_id && optionLabel.get(`id:${e.option_id}`)) ||
          optionLabel.get(`${e.source}\0${e.target}`) ||
          "";
        const short = label.length > 18 ? `${label.slice(0, 17)}…` : label;
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          animated: true,
          label: short || undefined,
          style: { stroke: "#6b7280" },
          labelStyle: { fill: "#f3f4f6", fontSize: 11, fontWeight: 500 },
          labelBgStyle: { fill: "#111827", fillOpacity: 0.92 },
          labelBgPadding: [6, 4] as [number, number],
          labelBgBorderRadius: 4,
        };
      })
    );
  }, [graph, selectedId, graphRevision, setNodes]);

  const selectedNode: StoryNode | null =
    graph && selectedId ? graph.nodes[selectedId] || null : null;

  const onNodeDragStart: OnNodeDrag = useCallback(() => {
    draggingRef.current = true;
    dragMovedRef.current = false;
  }, []);

  const onNodeDrag: OnNodeDrag = useCallback(() => {
    dragMovedRef.current = true;
  }, []);

  const onNodeDragStop: OnNodeDrag = useCallback(
    async (_e, node) => {
      draggingRef.current = false;
      localPosRef.current.set(node.id, {
        x: node.position.x,
        y: node.position.y,
      });
      try {
        await updateNodeLayout(storyId, node.id, {
          canvas_x: node.position.x,
          canvas_y: node.position.y,
        });
      } catch {
        // 保留本地坐标；下次轮询仍优先本地
      }
    },
    [storyId]
  );

  const onNodeClick = useCallback((_e: MouseEvent, node: Node) => {
    if (dragMovedRef.current) {
      dragMovedRef.current = false;
      return;
    }
    setSelectedId(node.id);
  }, []);

  const onPaneClick = useCallback(() => setSelectedId(null), []);

  return (
    <div className="flex h-full min-h-[60vh] w-full">
      <div className="relative min-w-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          nodeTypes={nodeTypes}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          nodesDraggable
          fitView={!didFit}
          onInit={() => setDidFit(true)}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background color="#3f4550" gap={18} />
          <Controls />
          <MiniMap
            pannable
            zoomable
            maskColor="rgba(0,0,0,0.5)"
            nodeColor={(n) => kindColor[String(n.data?.kind || "branch")] || "#888"}
          />
        </ReactFlow>
      </div>
      <NodeScriptPanel
        node={selectedNode}
        inboundLabels={selectedId ? inboundLabels(inboundByNode, selectedId) : []}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}

function inboundLabels(map: Map<string, string[]>, nodeId: string): string[] {
  return map.get(nodeId) || [];
}
