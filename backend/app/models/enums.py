from __future__ import annotations

from enum import Enum


class StoryStatus(str, Enum):
    planning = "planning"
    producing = "producing"
    playable = "playable"
    completed = "completed"
    failed = "failed"


class NodeKind(str, Enum):
    root = "root"
    main = "main"
    branch = "branch"
    ending = "ending"


class FissionPhase(str, Enum):
    idle = "idle"
    collect = "collect"
    bible = "bible"
    mainline = "mainline"
    plot_tree = "plot_tree"
    branch_script = "branch_script"
    consistency = "consistency"
    # 旧 meta 兼容（ReAct 流水线）
    expand = "expand"
    converge = "converge"
    compliance = "compliance"
    persist = "persist"
    done = "done"
    failed = "failed"


class ComplianceStatus(str, Enum):
    pending = "pending"
    passed = "pass"
    rejected = "reject"


class ProduceStatus(str, Enum):
    none = "none"
    cast = "cast"
    scenes = "scenes"
    prompts = "prompts"
    frames = "frames"
    awaiting_video = "awaiting_video"
    videos = "videos"
    qc = "qc"
    ready = "ready"
    paused = "paused"
    failed = "failed"


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"


class JobType(str, Enum):
    fission = "fission"
    assets = "assets"
    produce = "produce"
