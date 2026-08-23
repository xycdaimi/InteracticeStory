"use client";

import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import type { ProgressEvent, StoryMeta } from "@/lib/api";

const phaseLabel: Record<string, string> = {
  idle: "待命",
  collect: "收集故事信息",
  bible: "故事总纲",
  mainline: "梳理主线",
  plot_tree: "剧情树结构",
  branch_script: "节点剧本",
  consistency: "一致性校验",
  expand: "支线裂变",
  converge: "收束结局",
  compliance: "合规审查",
  persist: "定稿入库",
  done: "完成",
  failed: "失败",
};

const produceLabel: Record<string, string> = {
  none: "未开始",
  cast: "人物素材",
  scenes: "场景素材",
  prompts: "视频提示词",
  frames: "合成首帧",
  awaiting_video: "待生成视频",
  videos: "视频出片",
  qc: "质检",
  ready: "生产就绪",
  paused: "已暂停",
  failed: "生产失败",
};

const typeLabel: Record<string, string> = {
  error: "失败",
  phase: "阶段",
  graph: "图结构",
  assets: "素材",
  video: "视频",
  qc: "质检",
  log: "日志",
  tool: "工具",
};

const PRODUCE_EVENT_TYPES = new Set(["assets", "video", "qc", "error", "phase"]);

const SEGMENT_EVENT_PREFIXES = [
  "首帧完成",
  "首帧完成（承接尾帧）",
  "视频完成",
  "视频提示词完成",
  "人物图完成",
  "场景图完成",
];

type DisplayItem =
  | { kind: "single"; event: ProgressEvent }
  | { kind: "group"; event: ProgressEvent; count: number; label: string };

function eventStageLabel(event: ProgressEvent): string {
  if (event.phase === "done" && PRODUCE_EVENT_TYPES.has(event.type)) {
    return "生产";
  }
  if (event.phase === "failed") {
    return "裂变";
  }
  return phaseLabel[event.phase] || event.phase;
}

function segmentEventPrefix(message: string): string | null {
  for (const prefix of SEGMENT_EVENT_PREFIXES) {
    if (message.startsWith(prefix)) {
      return prefix;
    }
  }
  return null;
}

function collapseSegmentEvents(events: ProgressEvent[]): DisplayItem[] {
  const sorted = [...events].sort((a, b) => b.seq - a.seq);
  const items: DisplayItem[] = [];
  let i = 0;

  while (i < sorted.length) {
    const event = sorted[i];
    const prefix = segmentEventPrefix(event.message);
    if (!prefix) {
      items.push({ kind: "single", event });
      i += 1;
      continue;
    }

    let count = 1;
    let j = i + 1;
    while (j < sorted.length) {
      const next = sorted[j];
      if (next.type !== event.type || segmentEventPrefix(next.message) !== prefix) {
        break;
      }
      count += 1;
      j += 1;
    }

    if (count > 1) {
      items.push({
        kind: "group",
        event,
        count,
        label: prefix,
      });
      i = j;
      continue;
    }

    items.push({ kind: "single", event });
    i += 1;
  }

  return items;
}

function formatErrorMessage(message: string): string {
  return message.replace(/^生产失败[：:]\s*/, "");
}

function deriveStatus(meta: StoryMeta | null, events: ProgressEvent[]) {
  const errorEvents = events.filter((e) => e.type === "error");
  const produceErrors = errorEvents.filter((e) => e.message.includes("生产失败"));
  const latestProduceError = produceErrors.at(-1) ?? null;
  const fissionFailed = meta?.phase === "failed" || meta?.status === "failed";
  const produceFailed = meta?.produce_status === "failed";
  const fissionDone = meta?.phase === "done" && !fissionFailed;
  const produceReady = meta?.produce_status === "ready";
  const producePaused = meta?.produce_status === "paused";
  const produceRunning =
    meta?.produce_status !== undefined &&
    meta.produce_status !== "none" &&
    meta.produce_status !== "failed" &&
    meta.produce_status !== "ready" &&
    meta.produce_status !== "paused";

  return {
    errorEvents,
    latestError: produceFailed
      ? latestProduceError
      : fissionFailed
        ? errorEvents.at(-1) ?? null
        : null,
    fissionFailed,
    produceFailed,
    fissionDone,
    produceReady,
    producePaused,
    produceRunning,
  };
}

export function FissionProgress({
  meta,
  events,
}: {
  meta: StoryMeta | null;
  events: ProgressEvent[];
}) {
  const status = useMemo(() => deriveStatus(meta, events), [meta, events]);
  const displayItems = useMemo(() => collapseSegmentEvents(events), [events]);

  const phaseBadgeClass =
    status.fissionFailed
      ? "border-destructive/40 bg-destructive/10 text-destructive"
      : status.fissionDone
        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
        : "border-primary/30 bg-primary/10 text-primary";

  const produceBadgeClass = status.produceFailed
    ? "border-destructive/40 bg-destructive/10 text-destructive"
    : status.produceReady
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status.producePaused
        ? "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300"
        : "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300";

  const produceBadgeText = status.produceFailed
    ? "生产失败"
    : `生产 ${produceLabel[meta?.produce_status || "none"] || meta?.produce_status}`;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {(status.fissionFailed || status.produceFailed) && (
        <div
          role="alert"
          className="shrink-0 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
        >
          {status.fissionFailed ? (
            <p className="font-medium">裂变失败</p>
          ) : (
            <p className="font-medium">生产失败</p>
          )}
          {status.latestError ? (
            <p className="mt-1 text-xs leading-relaxed opacity-90">
              {formatErrorMessage(status.latestError.message)}
            </p>
          ) : null}
        </div>
      )}

      {status.fissionDone && !status.produceFailed && !status.produceReady && meta?.produce_status !== "none" ? (
        <div className="shrink-0 rounded-lg border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          裂变已完成；生产进行中或未完成（当前：
          {produceLabel[meta?.produce_status || "none"] || meta?.produce_status}）。
        </div>
      ) : null}

      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Badge className={phaseBadgeClass}>
          {status.fissionFailed
            ? "裂变失败"
            : status.fissionDone
              ? "裂变完成"
              : phaseLabel[meta?.phase || "idle"] || meta?.phase}
        </Badge>
        <Badge className="bg-secondary text-secondary-foreground">
          剧情线 {meta?.line_count ?? 0}
        </Badge>
        <Badge className="bg-secondary text-secondary-foreground">
          结局节点 {meta?.ending_count ?? 0}
        </Badge>
        {meta?.produce_status && meta.produce_status !== "none" ? (
          <Badge className={produceBadgeClass}>{produceBadgeText}</Badge>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border bg-card/70 p-4 backdrop-blur">
        <p className="mb-3 text-xs text-muted-foreground">最新事件在上（同类细项已合并）</p>
        <ul className="space-y-3 font-sans text-sm">
          {displayItems.length === 0 ? (
            <li className="text-muted-foreground">等待裂变事件…</li>
          ) : (
            displayItems.map((item) => {
              if (item.kind === "group") {
                return (
                  <li
                    key={`group-${item.event.seq}-${item.label}-${item.event.ts}`}
                    className="border-b border-border/60 pb-2 last:border-0"
                  >
                    <div className="text-xs text-muted-foreground">
                      #{item.event.seq} · {typeLabel[item.event.type] || item.event.type} ·{" "}
                      {eventStageLabel(item.event)}
                    </div>
                    <div className="mt-0.5 text-foreground">
                      {item.label}（合并 {item.count} 条，最新 #{item.event.seq}）
                    </div>
                  </li>
                );
              }

              const e = item.event;
              const isError = e.type === "error";
              return (
                <li
                  key={`${e.seq}-${e.ts}`}
                  className={
                    isError
                      ? "rounded-md border border-destructive/40 bg-destructive/10 px-2 py-2"
                      : "border-b border-border/60 pb-2 last:border-0"
                  }
                >
                  <div
                    className={
                      isError
                        ? "text-xs font-medium text-destructive"
                        : "text-xs text-muted-foreground"
                    }
                  >
                    #{e.seq} · {typeLabel[e.type] || e.type} · {eventStageLabel(e)}
                  </div>
                  <div
                    className={
                      isError
                        ? "mt-0.5 text-sm text-destructive"
                        : "mt-0.5 text-foreground"
                    }
                  >
                    {isError ? formatErrorMessage(e.message) : e.message}
                  </div>
                </li>
              );
            })
          )}
        </ul>
      </div>
    </div>
  );
}
