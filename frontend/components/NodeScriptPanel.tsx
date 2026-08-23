"use client";

import type { StoryNode } from "@/lib/api";

type Props = {
  node: StoryNode | null;
  inboundLabels: string[];
  onClose: () => void;
};

export function NodeScriptPanel({ node, inboundLabels, onClose }: Props) {
  if (!node) return null;

  return (
    <aside className="flex h-full w-[340px] shrink-0 flex-col border-l border-zinc-700 bg-[#1a1d24]">
      <div className="flex items-center justify-between border-b border-zinc-700 px-4 py-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-zinc-500">{node.kind}</div>
          <div className="text-sm font-semibold text-zinc-100">{node.title}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100"
        >
          关闭
        </button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3 text-sm text-zinc-300">
        <div>
          <div className="mb-1 text-xs text-zinc-500">画布摘要</div>
          <p className="leading-relaxed text-zinc-400">{node.summary || "（无）"}</p>
        </div>

        {inboundLabels.length > 0 ? (
          <div>
            <div className="mb-1 text-xs text-zinc-500">进入本节点的选项</div>
            <p className="leading-relaxed">{inboundLabels.join(" / ")}</p>
          </div>
        ) : null}

        {!node.script ? (
          <div className="rounded border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-amber-200/90">
            详细剧本尚未生成（待裂变剧本化）。当前仅有大纲：{node.summary || "（空）"}
          </div>
        ) : (
          <>
            <div>
              <div className="mb-1 text-xs text-zinc-500">进入状态</div>
              <p>{node.script.dramatic_state_in}</p>
            </div>
            <div className="space-y-3">
              <div className="text-xs text-zinc-500">
                时码剧本（{node.script.duration_seconds}s）
              </div>
              {node.script.beats.map((b, beatIdx) => (
                <div
                  key={`beat-${beatIdx}-${b.t_start}-${b.t_end}`}
                  className="rounded border border-zinc-700/80 bg-zinc-900/40 px-3 py-2"
                >
                  <div className="text-xs font-medium text-sky-300">
                    第{b.t_start}~{b.t_end}s · {b.shot || "镜头"}
                  </div>
                  <p className="mt-1 text-zinc-300">{b.action}</p>
                  {b.dialogue.map((d, i) => (
                    <p key={`${d.speaker}-${i}`} className="mt-1 text-zinc-200">
                      {d.speaker}：「{d.line}」
                    </p>
                  ))}
                </div>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs text-zinc-500">离开状态</div>
              <p>{node.script.dramatic_state_out}</p>
            </div>
            <div>
              <div className="mb-1 text-xs text-zinc-500">视觉计划</div>
              <p className="text-xs leading-relaxed text-zinc-400">
                首帧：{node.script.visual_plan.first_frame.depicts}
                {node.script.visual_plan.character_refs.length
                  ? `；定妆 ${node.script.visual_plan.character_refs.length} 张`
                  : "；无额外定妆"}
              </p>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
