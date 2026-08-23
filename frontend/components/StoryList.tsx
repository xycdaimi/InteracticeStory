"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  createStory,
  deleteStory,
  listStories,
  startFission,
  type StoryMeta,
} from "@/lib/api";

const phaseLabel: Record<string, string> = {
  idle: "待启动",
  collect: "收集中",
  mainline: "主线",
  expand: "裂变中",
  converge: "收束",
  compliance: "合规",
  persist: "入库",
  done: "完成",
  failed: "失败",
};

function formatTime(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function StoryList() {
  const router = useRouter();
  const [stories, setStories] = useState<StoryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newInspiration, setNewInspiration] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const data = await listStories();
      setStories(data.stories);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onCreate(andStartFission: boolean) {
    const text = newInspiration.trim() || "新故事";
    setCreating(true);
    setError(null);
    try {
      const { story_id } = await createStory(text);
      if (andStartFission) {
        await startFission(story_id);
      }
      setShowNewForm(false);
      setNewInspiration("");
      router.push(`/stories/${story_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
      setCreating(false);
    }
  }

  async function onDelete(storyId: string, inspiration: string) {
    const preview = inspiration.slice(0, 40);
    if (!window.confirm(`确定删除项目「${preview}」？此操作不可恢复。`)) {
      return;
    }
    setDeletingId(storyId);
    setError(null);
    try {
      await deleteStory(storyId);
      setStories((prev) => prev.filter((s) => s.story_id !== storyId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-display text-4xl tracking-tight text-foreground md:text-5xl">
            裂变剧场
          </p>
          <p className="mt-2 text-muted-foreground">管理故事项目，创建灵感并启动裂变</p>
        </div>
        <Button
          size="lg"
          onClick={() => setShowNewForm((v) => !v)}
          disabled={creating}
        >
          {showNewForm ? "取消" : "新建项目"}
        </Button>
      </div>

      {showNewForm ? (
        <Card className="border-primary/30 bg-card/80 backdrop-blur">
          <CardHeader>
            <CardTitle>新建故事项目</CardTitle>
            <CardDescription>填写灵感后可立即裂变，或进入项目页再编辑</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Textarea
              value={newInspiration}
              onChange={(e) => setNewInspiration(e.target.value)}
              placeholder="输入故事灵感，例如：讲一个桃园三结义的故事"
              className="min-h-[120px] bg-background/60"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={creating}
                onClick={() => void onCreate(true)}
              >
                {creating ? "创建中…" : "创建并开始裂变"}
              </Button>
              <Button
                variant="secondary"
                disabled={creating}
                onClick={() => void onCreate(false)}
              >
                仅创建
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {error ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">加载项目列表…</p>
      ) : stories.length === 0 ? (
        <Card className="border-dashed bg-card/40">
          <CardContent className="py-12 text-center text-muted-foreground">
            还没有项目，点击「新建项目」开始
          </CardContent>
        </Card>
      ) : (
        <ul className="grid gap-3">
          {stories.map((story) => (
            <li key={story.story_id}>
              <Card className="bg-card/70 transition-colors hover:bg-card">
                <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <Link
                      href={`/stories/${story.story_id}`}
                      className="block font-medium text-foreground hover:underline"
                    >
                      {story.inspiration || "未命名项目"}
                    </Link>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {story.story_id.slice(0, 8)}… · 更新 {formatTime(story.updated_at)}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge className="bg-secondary text-secondary-foreground">
                        {phaseLabel[story.phase] || story.phase}
                      </Badge>
                      {story.phase === "done" ? (
                        <Badge className="border border-border bg-transparent">
                          线 {story.line_count}
                        </Badge>
                      ) : null}
                      {story.produce_status && story.produce_status !== "none" ? (
                        <Badge className="border border-border bg-transparent">
                          生产 {story.produce_status}
                        </Badge>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button asChild variant="secondary" size="sm">
                      <Link href={`/stories/${story.story_id}`}>打开</Link>
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="border-destructive/50 text-destructive hover:bg-destructive/10"
                      disabled={deletingId === story.story_id}
                      onClick={() => void onDelete(story.story_id, story.inspiration)}
                    >
                      {deletingId === story.story_id ? "删除中…" : "删除"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
