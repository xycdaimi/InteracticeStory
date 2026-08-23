const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export type StoryMeta = {
  story_id: string;
  inspiration: string;
  phase: string;
  line_count: number;
  ending_count: number;
  status: string;
  produce_status?: string;
  produce_paused_from?: string | null;
  produce_pause_reason?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type StoryNode = {
  id: string;
  kind: "root" | "main" | "branch" | "ending";
  title: string;
  summary: string;
  canvas_x: number;
  canvas_y: number;
  parent_id?: string | null;
  script?: NodeScript | null;
};

export type DialogueLine = {
  speaker: string;
  line: string;
};

export type ScriptBeat = {
  t_start: number;
  t_end: number;
  shot?: string;
  action?: string;
  dialogue: DialogueLine[];
  pov?: string | null;
};

export type VisualPlan = {
  first_frame: {
    required: boolean;
    depicts: string;
    covers_character_ids?: string[];
  };
  character_refs: { character_id: string; reason?: string }[];
  scene_ref?: string | null;
  hidden_or_pov_only_ids?: string[];
};

export type NodeScript = {
  duration_seconds: number;
  dramatic_state_in: string;
  dramatic_state_out: string;
  beats: ScriptBeat[];
  visual_plan: VisualPlan;
};

export type StoryGraph = {
  story_id: string;
  root_id: string;
  nodes: Record<string, StoryNode>;
  edges: { id: string; source: string; target: string; option_id?: string | null }[];
  options: { id: string; from_node_id: string; to_node_id: string; label: string }[];
};

export type ProgressEvent = {
  seq: number;
  ts: string;
  phase: string;
  type: string;
  message: string;
  payload?: Record<string, unknown>;
};

export type ProductionBlueprint = {
  story_id?: string;
  characters?: Array<{
    character_id: string;
    name?: string;
    status?: string;
    image_path?: string | null;
  }>;
  scenes?: Array<{
    scene_id: string;
    name?: string;
    status?: string;
    image_path?: string | null;
  }>;
};

export type ProduceSummary = {
  story_id: string;
  produce_status: string;
  produce_paused_from?: string | null;
  produce_pause_reason?: string | null;
  active_job?: { job_id: string; status: string } | null;
  characters: { total: number; ready: number };
  scenes: { total: number; ready: number };
  shot_prompts: { total: number; ready: number };
  segments: { total: number; synthetic?: number; prev_last_frame?: number };
  frames: { total: number; ready: number };
  synthetic_frames?: { total: number; ready: number };
  chain_frames?: { total: number; ready: number };
  videos: { total: number; ready: number };
  on_demand?: { total: number; ready: number };
  qc: { pass: number; fail: number; pending: number };
};

function formatApiError(text: string, status: number): string {
  const trimmed = text.trim();
  if (!trimmed) {
    return status === 409
      ? "请求冲突，任务可能已在运行"
      : `请求失败（${status}）`;
  }
  try {
    const data = JSON.parse(trimmed) as { detail?: unknown };
    const detail = data.detail;
    if (typeof detail === "string") {
      if (detail.includes("produce already running")) {
        return "生产任务已在运行，请勿重复点击";
      }
      if (detail.includes("produce paused")) {
        return "生产已暂停，请点「继续生产」";
      }
      if (detail.includes("assets ready")) {
        return "素材已就绪，请点「生成视频」";
      }
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.map((item) => JSON.stringify(item)).join("; ");
    }
  } catch {
    /* 非 JSON */
  }
  return trimmed;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(formatApiError(text, res.status));
  }
  return res.json() as Promise<T>;
}

export function listStories() {
  return request<{ stories: StoryMeta[] }>("/api/v1/stories");
}

export function createStory(inspiration = "新故事") {
  return request<{ story_id: string; status: string; phase: string }>("/api/v1/stories", {
    method: "POST",
    body: JSON.stringify({ inspiration }),
  });
}

export function updateStory(storyId: string, inspiration: string) {
  return request<{ meta: StoryMeta; graph: StoryGraph }>(`/api/v1/stories/${storyId}`, {
    method: "PATCH",
    body: JSON.stringify({ inspiration }),
  });
}

export function deleteStory(storyId: string) {
  return request<{ ok: boolean }>(`/api/v1/stories/${storyId}`, { method: "DELETE" });
}

export function startFission(storyId: string) {
  return request<{ job_id: string; status: string }>(`/api/v1/stories/${storyId}/fission`, {
    method: "POST",
  });
}

export function getStory(storyId: string) {
  return request<{ meta: StoryMeta; graph: StoryGraph }>(`/api/v1/stories/${storyId}`);
}

export function updateNodeLayout(
  storyId: string,
  nodeId: string,
  body: { canvas_x: number; canvas_y: number }
) {
  return request<{
    ok: boolean;
    node_id: string;
    canvas_x: number;
    canvas_y: number;
  }>(`/api/v1/stories/${storyId}/nodes/${nodeId}/layout`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function getEvents(storyId: string, since = 0) {
  return request<{ events: ProgressEvent[]; next_since: number }>(
    `/api/v1/stories/${storyId}/events?since=${since}`
  );
}

export function startProduce(storyId: string) {
  return request<{ job_id: string; status: string }>(`/api/v1/stories/${storyId}/produce`, {
    method: "POST",
  });
}

export function startVideoProduce(storyId: string) {
  return request<{ job_id: string; status: string }>(
    `/api/v1/stories/${storyId}/produce/videos`,
    { method: "POST" }
  );
}

export function resumeProduce(storyId: string) {
  return request<{ job_id: string; status: string }>(
    `/api/v1/stories/${storyId}/produce/resume`,
    { method: "POST" }
  );
}

export function getProduceStatus(storyId: string) {
  return request<ProduceSummary>(`/api/v1/stories/${storyId}/produce`);
}

export function getProductionBlueprint(storyId: string) {
  return request<{ blueprint: ProductionBlueprint }>(
    `/api/v1/stories/${storyId}/production-blueprint`
  );
}

export function storyAssetUrl(storyId: string, relPath: string) {
  const normalized = relPath.replace(/^\//, "");
  return `${API_BASE}/api/v1/stories/${storyId}/media/${normalized}`;
}
