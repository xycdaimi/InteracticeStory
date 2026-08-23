"use client";

import { useParams } from "next/navigation";
import { StoryPageClient } from "@/components/StoryPageClient";

export default function StoryPage() {
  const params = useParams();
  const storyId = typeof params.storyId === "string" ? params.storyId : "";
  if (!storyId) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-12 text-sm text-destructive">
        无效的故事 ID
      </main>
    );
  }
  return <StoryPageClient storyId={storyId} />;
}
