"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ProduceAssetsPanel } from "@/components/ProduceAssetsPanel";
import { FissionProgress } from "@/components/FissionProgress";
import { ProjectSetup } from "@/components/ProjectSetup";
import { StoryGraphCanvas } from "@/components/StoryGraphCanvas";
import { Button } from "@/components/ui/button";
import {
  getEvents,
  getProductionBlueprint,
  getProduceStatus,
  getStory,
  resumeProduce,
  startProduce,
  startVideoProduce,
  type ProductionBlueprint,
  type ProduceSummary,
  type ProgressEvent,
  type StoryGraph,
  type StoryMeta,
} from "@/lib/api";

type Notice = {
  kind: "success" | "error" | "info";
  text: string;
};

function isProduceRunning(summary: ProduceSummary | null) {
  const status = summary?.active_job?.status;
  return status === "pending" || status === "running";
}

function shouldStopPolling(phase: string, summary: ProduceSummary | null) {
  if (phase === "failed") return true;
  if (phase !== "done") return false;
  if (isProduceRunning(summary)) return false;
  return summary?.produce_status === "ready";
}

function mergeProgressEvents(
  prev: ProgressEvent[],
  incoming: ProgressEvent[],
): ProgressEvent[] {
  const bySeq = new Map<number, ProgressEvent>();
  for (const e of prev) {
    bySeq.set(e.seq, e);
  }
  for (const e of incoming) {
    bySeq.set(e.seq, e);
  }
  return Array.from(bySeq.values()).sort((a, b) => a.seq - b.seq);
}

export function StoryPageClient({ storyId }: { storyId: string }) {
  const [meta, setMeta] = useState<StoryMeta | null>(null);
  const [graph, setGraph] = useState<StoryGraph | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [produceSummary, setProduceSummary] = useState<ProduceSummary | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [produceNotice, setProduceNotice] = useState<Notice | null>(null);
  const [produceSubmitting, setProduceSubmitting] = useState(false);
  const [pollEpoch, setPollEpoch] = useState(0);
  const [graphRevision, setGraphRevision] = useState(0);
  const [blueprint, setBlueprint] = useState<ProductionBlueprint | null>(null);
  const [sidebarTab, setSidebarTab] = useState<"log" | "assets">("log");
  const sinceRef = useRef(0);
  const submitLockRef = useRef(false);
  const tickingRef = useRef(false);

  const refreshProduceSummary = useCallback(async () => {
    const summary = await getProduceStatus(storyId);
    setProduceSummary(summary);
    setMeta((m) =>
      m
        ? {
            ...m,
            produce_status: summary.produce_status,
            produce_paused_from: summary.produce_paused_from,
            produce_pause_reason: summary.produce_pause_reason,
          }
        : m
    );
    return summary;
  }, [storyId]);

  useEffect(() => {
    let cancelled = false;
    sinceRef.current = 0;
    setEvents([]);

    async function tick() {
      if (tickingRef.current) return;
      tickingRef.current = true;
      try {
        const [story, ev] = await Promise.all([
          getStory(storyId),
          getEvents(storyId, sinceRef.current),
        ]);
        if (cancelled) return;

        let nextMeta = story.meta;
        let summary: ProduceSummary | null = null;
        const produceStarted =
          story.meta.produce_status !== undefined &&
          story.meta.produce_status !== "none";
        const shouldLoadProduce =
          story.meta.phase === "done" || produceStarted;
        if (shouldLoadProduce) {
          try {
            summary = await getProduceStatus(storyId);
            if (!cancelled) {
              nextMeta = {
                ...story.meta,
                produce_status: summary.produce_status,
                produce_paused_from: summary.produce_paused_from,
                produce_pause_reason: summary.produce_pause_reason,
              };
              setProduceSummary(summary);
            }
          } catch {
            /* blueprint 可能尚未生成 */
          }
          try {
            const bp = await getProductionBlueprint(storyId);
            if (!cancelled) {
              setBlueprint(bp.blueprint);
            }
          } catch {
            if (!cancelled) {
              setBlueprint(null);
            }
          }
        }

        setMeta(nextMeta);
        setGraph(story.graph);
        if (ev.events.length) {
          setEvents((prev) => mergeProgressEvents(prev, ev.events));
          sinceRef.current = ev.next_since;
          const latestSeq = ev.events[ev.events.length - 1]?.seq ?? 0;
          setGraphRevision(latestSeq);

          // 新日志写入后补拉图，避免与 getEvents 并行时画布仍是旧节点
          try {
            const fresh = await getStory(storyId);
            if (!cancelled) {
              setGraph(fresh.graph);
              setMeta((m) =>
                m
                  ? {
                      ...m,
                      line_count: fresh.meta.line_count,
                      ending_count: fresh.meta.ending_count,
                      phase: fresh.meta.phase,
                      status: fresh.meta.status,
                      updated_at: fresh.meta.updated_at,
                    }
                  : fresh.meta
              );
            }
          } catch {
            /* 保留本轮已拉到的图 */
          }
        }
        if (shouldStopPolling(nextMeta.phase, summary)) {
          clearInterval(timer);
        }
      } catch (err) {
        if (!cancelled) {
          setPageError(err instanceof Error ? err.message : "加载失败");
        }
      } finally {
        tickingRef.current = false;
      }
    }

    void tick();
    const timer = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [storyId, pollEpoch]);

  async function onProduce(resume = false) {
    if (submitLockRef.current || produceSubmitting || isProduceRunning(produceSummary)) {
      setProduceNotice({
        kind: "info",
        text: "生产任务已在运行，请勿重复点击",
      });
      return;
    }

    submitLockRef.current = true;
    setProduceSubmitting(true);
    setPageError(null);
    setProduceNotice({
      kind: "info",
      text: resume ? "正在恢复生产任务…" : "正在提交生产任务…",
    });

    try {
      const result = resume ? await resumeProduce(storyId) : await startProduce(storyId);
      const summary = await refreshProduceSummary();
      setProduceNotice({
        kind: "success",
        text: `生产任务已启动（任务 ${result.job_id.slice(0, 8)}…），后台执行中`,
      });
      setProduceSummary({
        ...summary,
        active_job: { job_id: result.job_id, status: result.status || "pending" },
      });
      setPollEpoch((n) => n + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : "启动生产失败";
      setProduceNotice({ kind: "error", text: message });
      setPageError(message);
    } finally {
      setProduceSubmitting(false);
      submitLockRef.current = false;
    }
  }

  async function onStartVideos() {
    if (submitLockRef.current || produceSubmitting || isProduceRunning(produceSummary)) {
      setProduceNotice({
        kind: "info",
        text: "生产任务已在运行，请勿重复点击",
      });
      return;
    }

    submitLockRef.current = true;
    setProduceSubmitting(true);
    setPageError(null);
    setProduceNotice({ kind: "info", text: "正在提交视频生成任务…" });

    try {
      const result = await startVideoProduce(storyId);
      const summary = await refreshProduceSummary();
      setProduceNotice({
        kind: "success",
        text: `视频生成已启动（任务 ${result.job_id.slice(0, 8)}…）`,
      });
      setProduceSummary({
        ...summary,
        active_job: { job_id: result.job_id, status: result.status || "pending" },
      });
      setPollEpoch((n) => n + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : "启动视频生成失败";
      setProduceNotice({ kind: "error", text: message });
      setPageError(message);
    } finally {
      setProduceSubmitting(false);
      submitLockRef.current = false;
    }
  }

  const canProduce =
    meta?.phase === "done" ||
    (meta?.produce_status !== undefined && meta.produce_status !== "none");
  const isPaused = meta?.produce_status === "paused";
  const awaitingVideo = meta?.produce_status === "awaiting_video";
  const produceFailed = meta?.produce_status === "failed";
  const produceRunning = produceSubmitting || isProduceRunning(produceSummary);
  const isIdle = meta?.phase === "idle";
  const inVideoPhase =
    awaitingVideo ||
    meta?.produce_status === "videos" ||
    meta?.produce_status === "qc";

  async function reloadStory() {
    const story = await getStory(storyId);
    setMeta(story.meta);
    setGraph(story.graph);
    sinceRef.current = 0;
    setEvents([]);
    setGraphRevision(0);
    setPollEpoch((n) => n + 1);
  }

  const assetsButtonLabel = produceSubmitting
    ? "提交中…"
    : isProduceRunning(produceSummary)
      ? "生产中…"
      : isPaused
        ? "继续生产"
        : produceFailed
          ? "重试生产"
          : "开始生产";

  const videoButtonLabel = produceSubmitting
    ? "提交中…"
    : isProduceRunning(produceSummary)
      ? "出片中…"
      : "生成视频";

  return (
    <main className="mx-auto flex h-[100dvh] w-full max-w-[1600px] flex-col gap-4 overflow-hidden px-4 py-4 md:px-6 md:py-6">
      <header className="flex shrink-0 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Button asChild variant="outline" size="sm" className="shrink-0">
            <Link href="/">← 返回列表</Link>
          </Button>
          <div className="min-w-0">
            <p className="font-display text-xl text-foreground md:text-2xl">裂变剧场</p>
            <p className="truncate text-sm text-muted-foreground">
              故事 {storyId.slice(0, 8)}…
            </p>
          </div>
        </div>
        <div className="shrink-0 text-sm text-muted-foreground">
          节点 {graph ? Object.keys(graph.nodes).length : 0}
        </div>
      </header>

      {pageError ? (
        <p className="shrink-0 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {pageError}
        </p>
      ) : null}

      {isIdle ? (
        <ProjectSetup
          storyId={storyId}
          initialInspiration={meta?.inspiration || ""}
          onStarted={() => void reloadStory()}
        />
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-card/50 p-4 backdrop-blur">
          <div className="mb-3 shrink-0 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-display text-lg">裂变过程</h2>
              {canProduce ? (
                <div className="flex shrink-0 items-center gap-2">
                  {inVideoPhase && !produceFailed && !isPaused ? (
                    <Button
                      size="sm"
                      disabled={
                        produceRunning ||
                        meta?.produce_status === "ready" ||
                        !awaitingVideo
                      }
                      onClick={() => void onStartVideos()}
                    >
                      {videoButtonLabel}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="secondary"
                      className={
                        produceFailed && !produceRunning
                          ? "border border-destructive/50 text-destructive hover:bg-destructive/10"
                          : undefined
                      }
                      disabled={produceRunning || meta?.produce_status === "ready"}
                      onClick={() => void onProduce(isPaused)}
                    >
                      {assetsButtonLabel}
                    </Button>
                  )}
                </div>
              ) : null}
            </div>
            {produceNotice ? (
              <p
                role="status"
                className={
                  produceNotice.kind === "success"
                    ? "rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-2 text-xs text-emerald-800 dark:text-emerald-200"
                    : produceNotice.kind === "error"
                      ? "rounded-md border border-destructive/40 bg-destructive/10 px-2.5 py-2 text-xs text-destructive"
                      : "rounded-md border border-primary/30 bg-primary/10 px-2.5 py-2 text-xs text-primary"
                }
              >
                {produceNotice.text}
              </p>
            ) : null}
            {produceSummary && canProduce ? (
              <p className="text-xs text-muted-foreground">
                人物 {produceSummary.characters.ready}/{produceSummary.characters.total} ·
                场景 {produceSummary.scenes.ready}/{produceSummary.scenes.total} ·
                提示词 {produceSummary.shot_prompts.ready}/{produceSummary.shot_prompts.total} ·
                合成首帧{" "}
                {(produceSummary.synthetic_frames ?? produceSummary.frames).ready}/
                {(produceSummary.synthetic_frames ?? produceSummary.frames).total} ·
                承接尾帧 {produceSummary.chain_frames?.ready ?? 0}/
                {produceSummary.chain_frames?.total ?? 0} ·
                预生产视频 {produceSummary.videos.ready}/{produceSummary.videos.total}
                {produceSummary.on_demand
                  ? ` · 按需 ${produceSummary.on_demand.ready}/${produceSummary.on_demand.total}`
                  : ""}
              </p>
            ) : canProduce && meta?.produce_status === "none" ? (
              <p className="text-xs text-muted-foreground">
                裂变已完成，请点「开始生产」生成人物定妆图与场景图。
              </p>
            ) : meta?.phase === "compliance" || meta?.phase === "persist" ? (
              <p className="text-xs text-muted-foreground">
                合规/定稿进行中…完成后可手动点「开始生产」。
              </p>
            ) : null}
          </div>
          {canProduce ? (
            <div className="mb-2 flex shrink-0 gap-1">
              <Button
                type="button"
                size="sm"
                variant={sidebarTab === "log" ? "secondary" : "ghost"}
                className="h-7 text-xs"
                onClick={() => setSidebarTab("log")}
              >
                裂变日志
              </Button>
              <Button
                type="button"
                size="sm"
                variant={sidebarTab === "assets" ? "secondary" : "ghost"}
                className="h-7 text-xs"
                onClick={() => setSidebarTab("assets")}
              >
                素材图
              </Button>
            </div>
          ) : null}
          <div className="min-h-0 flex-1 overflow-hidden">
            {sidebarTab === "assets" && canProduce ? (
              <ProduceAssetsPanel storyId={storyId} blueprint={blueprint} />
            ) : (
              <FissionProgress meta={meta} events={events} />
            )}
          </div>
        </section>
        <section className="relative min-h-0 overflow-hidden rounded-xl border bg-[#1a1d23] shadow-inner">
          <StoryGraphCanvas
            storyId={storyId}
            graph={graph}
            graphRevision={graphRevision}
          />
        </section>
      </div>
    </main>
  );
}
