"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { createStory, startFission } from "@/lib/api";

export function InspirationForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { story_id } = await createStory(text.trim());
      await startFission(story_id);
      router.push(`/stories/${story_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
      setLoading(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full max-w-2xl flex-col gap-4">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="输入故事灵感段落，例如：讲一个关于桃园三结义的故事"
        className="min-h-[180px] bg-card/80 text-base leading-relaxed backdrop-blur"
        required
      />
      {error ? <p className="text-sm text-accent">{error}</p> : null}
      <Button type="submit" size="lg" disabled={loading || !text.trim()}>
        {loading ? "正在起盘…" : "开始裂变"}
      </Button>
    </form>
  );
}
