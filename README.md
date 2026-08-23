# Interactive Story（裂变剧场）

灵感 → LangGraph 裂变（故事图 + 可拍剧本）→ Web 进度面板 + React Flow 画布 → **手动**生产定妆/场景/首帧/视频。

远期：游玩引擎、RAG 选片、剧情预测补片（尚未实现）。

文档：`docs/流程.md`、`docs/业务流程.md`、`docs/需求文档.md`、`docs/方案设计.md`、`docs/模型调用.md`。

---

## 环境要求

- **Python 3.11+**（仅用仓库虚拟环境，**禁止系统 `python`** 跑业务）
- **Node.js 18+**（前端）
- 各 API 密钥见 `backend/.env.example`（缺密钥时真实调用会失败，无 mock）

---

## 首次安装

```bash
cd /path/to/interactive_story

# Python 虚拟环境（若尚未创建）
python3 -m venv venv
venv/bin/pip install -r backend/requirements.txt

# 后端配置
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少填写：
#   GEEKAI_API_KEY、EXA_API_KEY（裂变）
#   EPHONE_API_KEY、DASHSCOPE_API_KEY（出片与质检，生产阶段需要）

# 前端
cd frontend
npm install
cp .env.local.example .env.local
# 默认 NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
cd ..
```

数据目录默认 `DATA_DIR=./data`（相对仓库根目录），故事与媒体在 `data/stories/{story_id}/`。

---

## 运行

需要 **两个终端**（仓库根目录）：

```bash
# 终端 1：后端 API（127.0.0.1:8000）
make api

# 终端 2：前端 Web（127.0.0.1:3000）
make web
```

| 服务 | 地址 |
| --- | --- |
| API 健康检查 | http://127.0.0.1:8000/health |
| Web | http://127.0.0.1:3000 |

**注意**

- 素材图 URL 走 API：`/api/v1/stories/{id}/media/assets/...`。只开 `make web` 不开 `make api` 会导致图片加载失败。
- 前端通过 `NEXT_PUBLIC_API_BASE` 访问 API；与 `make api` 的 host/port 须一致。

---

## 使用流程（Web）

1. 打开 http://127.0.0.1:3000 ，创建故事并输入灵感。
2. 在故事页点击「开始裂变」。
3. **左侧**：裂变日志（阶段、事件）；裂变完成后可切「素材图」预览定妆/场景（需先生产）。
4. **右侧**：React Flow 画布；点击节点可在侧栏查看 **时码剧本**（`script.beats`）。
5. 裂变 `phase=done` 后，点击 **「开始生产」**（不会自动开始）：
   - 定妆图 → 场景图 → 首帧 → 拼装视频提示词；
   - 汇总显示进度后，点 **「生成视频」** 进入 MiniMax 出片与质检。
6. 生产 paused 时可点「继续生产」；失败可「重试生产」。

---

## 测试

```bash
# 后端单测
make test

# CLI：仅裂变（与 Web 一致，不自动生产）
PYTHONPATH=. venv/bin/python -m backend.scripts.run_fission_cli --inspiration "桃园三结义"

# CLI：裂变 + 自动串联生产（include_produce=True）
PYTHONPATH=. venv/bin/python -m backend.scripts.run_pipeline_cli --inspiration "测试"
```

---

## 仓库结构（简要）

```text
backend/app/          # FastAPI、LangGraph、生产流水线
frontend/             # Next.js 故事列表与故事页
data/stories/         # 运行时故事数据（gitignore）
venv/                 # Python 虚拟环境
Makefile              # api / web / test
```

---

## 生产流水线（当前实现）

```text
手动 POST /produce
  → 定妆图 (cast)
  → 场景图 (scenes)
  → 同步 segments
  → 合成首帧 (frames)
  → 拼装视频提示词（script 【参考图】+ beats，无 LLM）
  → awaiting_video

手动 POST /produce/videos
  → MiniMax-H3 出片
  → Qwen3-Omni-Flash 质检
  → regeneration（若不合格）
  → ready
```

视频提示词来源：节点 `script.visual_plan`（参考图说明）+ `script.beats`（时码正文）；首帧出图使用 `visual_plan.first_frame.depicts`，与最终视频 prompt 中的首帧描述一致。

---

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 素材图不显示 | 确认 `make api` 已启动；浏览器 Network 看 media 请求是否 200 |
| `produce already running` | 等待 JOB 结束或查 DB/日志；勿重复点击 |
| 裂变卡在 compliance | 大故事 DAG 合规可能较慢；勿恢复「逐条审剧情线」 |
| Console `[object Event]`（Next dev） | 多为 Next 15.1.0 overlay 误报或资源加载事件；先查 Network |

---

## 许可证

见仓库约定（若未单独声明则以项目维护者为准）。
