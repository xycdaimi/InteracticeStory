"use client";

import { useState } from "react";
import { storyAssetUrl } from "@/lib/api";

type BlueprintCharacter = {
  character_id: string;
  name?: string;
  status?: string;
  image_path?: string | null;
};

type BlueprintScene = {
  scene_id: string;
  name?: string;
  status?: string;
  image_path?: string | null;
};

type ProductionBlueprint = {
  characters?: BlueprintCharacter[];
  scenes?: BlueprintScene[];
};

function AssetThumb({
  src,
  alt,
  aspectClass,
  fallbackLabel,
}: {
  src: string;
  alt: string;
  aspectClass: string;
  fallbackLabel: string;
}) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div
        className={`flex ${aspectClass} items-center justify-center bg-muted/50 text-[10px] text-muted-foreground`}
      >
        {fallbackLabel}
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={`${aspectClass} w-full object-cover`}
      onError={(e) => {
        e.currentTarget.onerror = null;
        setFailed(true);
      }}
    />
  );
}

export function ProduceAssetsPanel({
  storyId,
  blueprint,
}: {
  storyId: string;
  blueprint: ProductionBlueprint | null;
}) {
  if (!blueprint) {
    return (
      <p className="text-sm text-muted-foreground">
        定稿入库后此处展示人物定妆图与场景图；须点「开始生产」后才会生成。
      </p>
    );
  }

  const characters = blueprint.characters ?? [];
  const scenes = blueprint.scenes ?? [];
  const readyChars = characters.filter((c) => c.image_path && c.status === "ready");
  const readyScenes = scenes.filter((s) => s.image_path && s.status === "ready");

  if (!characters.length && !scenes.length) {
    return (
      <p className="text-sm text-muted-foreground">蓝图暂无人物/场景条目，等待 persist 写入。</p>
    );
  }

  return (
    <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
      {characters.length > 0 ? (
        <section>
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">
            人物定妆 ({readyChars.length}/{characters.length})
          </h3>
          <ul className="grid grid-cols-2 gap-2">
            {characters.map((c) => (
              <li
                key={c.character_id}
                className="overflow-hidden rounded-md border border-border/60 bg-muted/30"
              >
                {c.image_path ? (
                  <AssetThumb
                    src={storyAssetUrl(storyId, c.image_path)}
                    alt={c.name || c.character_id}
                    aspectClass="aspect-square"
                    fallbackLabel="加载失败"
                  />
                ) : (
                  <div
                    className="flex aspect-square items-center justify-center bg-muted/50 text-[10px] text-muted-foreground"
                  >
                    {c.status === "ready" ? "无图" : "生成中…"}
                  </div>
                )}
                <p className="truncate px-2 py-1 text-xs">{c.name || c.character_id}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {scenes.length > 0 ? (
        <section>
          <h3 className="mb-2 text-xs font-medium text-muted-foreground">
            场景图 ({readyScenes.length}/{scenes.length})
          </h3>
          <ul className="grid grid-cols-2 gap-2">
            {scenes.map((s) => (
              <li
                key={s.scene_id}
                className="overflow-hidden rounded-md border border-border/60 bg-muted/30"
              >
                {s.image_path ? (
                  <AssetThumb
                    src={storyAssetUrl(storyId, s.image_path)}
                    alt={s.name || s.scene_id}
                    aspectClass="aspect-video"
                    fallbackLabel="加载失败"
                  />
                ) : (
                  <div
                    className="flex aspect-video items-center justify-center bg-muted/50 text-[10px] text-muted-foreground"
                  >
                    {s.status === "ready" ? "无图" : "生成中…"}
                  </div>
                )}
                <p className="truncate px-2 py-1 text-xs">{s.name || s.scene_id}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
