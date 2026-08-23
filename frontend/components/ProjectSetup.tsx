"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { startFission, updateStory } from "@/lib/api";

export function ProjectSetup({
  storyId,
  initialInspiration,
  onStarted,
}: {
  storyId: string;
  initialInspiration: string;
  onStarted: () => void;
}) {
  const [text, setText] = useState(initialInspiration);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const inspiration = text.trim();
    if (!inspiration) return;
    setLoading(true);
    setError(null);
    try {
      await updateStory(storyId, inspiration);
      await startFission(storyId);
      onStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-primary/30 bg-primary/5 p-4"
    >
      <p className="font-medium text-foreground">填写灵感并启动裂变</p>
      <p className="mt-1 text-xs text-muted-foreground">
        项目已创建，编辑灵感后点击下方按钮开始 Agent 裂变流程
      </p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="mt-3 min-h-[140px] bg-background/80"
        placeholder="输入故事灵感段落…"
        required
      />
      {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
      <Button type="submit" className="mt-3" disabled={loading || !text.trim()}>
        {loading ? "正在启动…" : "开始裂变"}
      </Button>
    </form>
  );
}
