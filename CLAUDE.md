# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MyClaw — 基于 LangGraph 状态机的 AI Agent 框架，提供 REPL 交互式终端体验。核心卖点是"透明可控"：状态机可追溯 + 完整审计日志 + 安全沙盒 + 对话归档。

架构图与执行流程见 `docs/agent.png` / `docs/agent.svg`；组件级详细文档在 `docs/intro/`。

## 常用命令

### 安装与配置

```bash
uv sync                        # 推荐 (锁定在 uv.lock)
pip install -e ".[dev]"        # 传统方式

myclaw config                  # 交互式配置向导 (生成/更新 .env)
```

### 运行

```bash
myclaw run                                # 新会话，默认人设
myclaw run -p professional                # 指定人设 (default/professional/friendly/custom)
myclaw run -n "工作助手"                  # 命名当前会话
myclaw run -r "会话名称"                  # 恢复历史会话
myclaw run -l                             # 列出历史会话
myclaw monitor                            # 实时监控 logs/*.jsonl
```

### 测试

```bash
pytest tests/                                          # 全部测试
pytest tests/test_deadlock_prevention.py              # 单文件
pytest tests/test_deadlock_prevention.py::TestLoopDetection::test_no_loop_under_warn_threshold   # 单个用例
pytest -k "loop"                                      # 按关键字筛选
```

`tests/` 下的关键文件：`test_agent.py`（状态机）、`test_builtins.py`（工具集）、`test_sandbox_tools.py`（沙盒安全）、`test_deadlock_prevention.py`（循环检测）、`test_context_advanced.py`（上下文裁剪）、`test_two_phase_skills.py`（Skill 加载）、`test_knowledge.py`（知识库）。

测试用例不依赖外部 LLM——纯单元测试，不需要 API key。

## 核心架构

### 入口与 CLI

- `entry/cli.py` — Typer 入口，定义 `config` / `run` / `monitor` 三个子命令。
- `entry/main.py` — REPL 主循环（Rich UI + prompt_toolkit），处理 slash command（`/skill`、`/memory`、`/rename`、`/exit`），并把用户输入喂给 LangGraph app。
- `entry/monitor.py` — `tail -f` 风格的日志查看器。

### 状态机 (`myclaw/core/agent.py`)

LangGraph `StateGraph`：

```
START → agent → route_after_agent
                  ├─ last msg has tool_calls → tools → agent
                  ├─ state.ask_resume == True  → ask_resume → END
                  └─ else → END
```

`agent_node` 是核心，每轮执行：日志记录 → 上下文裁剪（>40 轮触发） → 摘要注入 → Skill 索引注入 → 用户画像注入 → 循环检测 → LLM 调用 → 状态写回。

### 关键模块 (`myclaw/core/`)

| 文件 | 职责 |
|------|------|
| `context.py` | `AgentState` TypedDict、上下文裁剪 `trim_context_messages`、循环检测 `detect_tool_loop` + 阈值常量 |
| `provider.py` | LLM 工厂 `get_provider()`，支持 OpenAI / Anthropic / 阿里云 / 腾讯 / Z.AI / Ollama / 自定义 |
| `embedding_provider.py` + `embedding_store.py` | Embedding 工厂 + sqlite-vec 向量存储（混合评分 `EMBEDDING_ALPHA` 默认 0.6） |
| `skill_loader.py` | Skill 两阶段加载：索引扫描 + `load_skill` 工具按需加载 |
| `prompt_loader.py` | 人设模板 + 占位符替换（`{{SKILL_INDEX}}` / `{{USER_PROFILE}}` / `{{CONTEXT_SUMMARY}}` / `{{KNOWLEDGE_CONTEXT}}`） |
| `session.py` | 会话元数据单例（名称/描述/消息计数），持久化到 `workspace/sessions.json` |
| `bus.py` + `heartbeat.py` | asyncio.Queue 任务队列 + 定时任务引擎（hourly/daily/weekly） |
| `logger.py` | 异步 JSONL 审计 + 对话归档（6 类事件：llm_input / tool_call / tool_result / ai_message / system_action / message_archive） |
| `tools/base.py` | `@my_tool` 装饰器 + thread_id 管理 |
| `tools/builtins.py` | 20 个内置工具（含 6 个知识库 CRUD + 3 个 Skill 加载 + 4 个沙盒文件 + 1 个 AST 安全计算器） |
| `tools/sandbox_tools.py` | 沙盒文件/Shell 工具 |
| `prompts/{default,professional,friendly,custom}.md` | 人设模板（YAML frontmatter + Markdown） |

### 三层记忆体系

| 层级 | 存储 | 注入 | 职责 |
|------|------|------|------|
| 长期画像 | `workspace/memory/user_profile.md` | 每轮全量 | 用户偏好等稳定属性 |
| 对话摘要 | `state.sqlite3` summary 字段 | 每轮全量 | 近期对话进展（>40 轮触发压缩） |
| 知识库 | `workspace/memory/knowledge/*.md` + `vec_index.sqlite3` | 被动召回 Top 5 + Agent 主动 CRUD | 显式事实、跨会话需要记住的内容 |

未配置 Embedding 时知识库自动降级为纯关键词检索。

### 循环检测 / 死锁防御（重要：近期重构）

Agent 单轮推理可能因 LLM 反复触发同一工具陷入死循环。当前实现三层防御：

1. **迭代计数 + 重复工具检测**（`agent.py` 内的 `agent_node`）：每轮自增 `iteration_count`，追踪 `repeated_tool_name` / `repeated_count`。
2. **阈值常量**（`context.py`）：`LOOP_WARN_THRESHOLD=20`、`LOOP_BREAK_THRESHOLD=35`、`REPEATED_TOOL_WARN_THRESHOLD=3`、`REPEATED_TOOL_BREAK_THRESHOLD=5`。
3. **LangGraph `recursion_limit=60`**（`entry/main.py:242`）— 兜底。

命中中断时 `state.ask_resume=True` → `route_after_agent` 路由到 `ask_resume_node` → END，REPL 层捕获后弹交互选择（继续/换思路/退出）。修改这些阈值或调整路由逻辑时，**务必同时跑 `tests/test_deadlock_prevention.py`**。

### 安全沙盒

- 文件操作严格限制在 `workspace/office/`（`realpath()` 解析，防 symlink 越权）。
- `execute_office_shell`：子进程仅暴露 `PATH/HOME/LANG` 环境变量（API Key 不可见）+ 41 命令黑名单 + 60s 超时 + 2000 字符输出截断 + 路径越权正则。
- `calculator` 工具用 `ast.parse` + `_SAFE_OPERATORS` 白名单替换 `eval()`。
- Skill 脚本在沙盒内执行；路径、symlink、env 隔离由 `sandbox_tools.py` 统一保证。

### Skill 格式

兼容 Claude Code 标准：`workspace/office/skills/<name>/SKILL.md` 只需 `name` + `description` frontmatter。**`description` 是唯一触发判断依据**，必须写清楚"做什么 / 何时用 / 何时不用"。**已废弃** `trigger_words` / `trigger_condition` / `skip_condition` / `workflow` 字段。

加载流程：阶段一扫描 frontmatter 注入索引；阶段二 Agent 根据 description 匹配后调用 `load_skill` 工具加载正文。附带资源在 `scripts/`、`references/`、`assets/`，可通过 `list_skill_resources` / `load_skill_resource` / `execute_skill_script` 访问。

### 运行时目录

| 路径 | 用途 |
|------|------|
| `workspace/state.sqlite3` | LangGraph checkpoint（最近 10 轮 + 摘要） |
| `workspace/sessions.json` | 会话元数据 |
| `workspace/tasks.json` | 定时任务（按 session_id 分离） |
| `workspace/memory/knowledge/` | 知识库（`*.md` + `index.json` + `vec_index.sqlite3`） |
| `workspace/office/` | **安全沙盒** — 唯一允许文件操作的空间；`office/skills/` 是 Skill 卡槽 |
| `logs/{session_id}.jsonl` | 审计日志 + 裁剪消息归档 |

## 添加工具

```python
# myclaw/core/tools/builtins.py
from .base import my_tool

@my_tool
def my_tool(arg: str) -> str:
    """描述（description 会被 LLM 用于决策）"""
    return "结果"

BUILTIN_TOOLS.append(my_tool)
```

## 环境变量

详见 `.env.example`。`DEFAULT_PROVIDER` 决定使用哪套 API key：`openai`/`aliyun`/`z.ai`/`tencent`/`other` 用 `OPENAI_API_KEY` + `OPENAI_API_BASE`；`anthropic` 用 `ANTHROPIC_API_KEY`；`ollama` 走本地无需 key。Embedding 独立配置（`EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` / `EMBEDDING_ALPHA`）。

## MCP 配置

`.mcp.json` 已声明两个 MCP server：`sqlite`（直接读 `workspace/state.sqlite3`）和 `github`（需要 `GITHUB_PERSONAL_ACCESS_TOKEN` 环境变量）。新增 MCP server 改这个文件即可。

## Git 工作流

主分支：`main`。近期 commit 见 `git log --oneline -20`——最近 5 个 commit 都在做循环检测重构（`feat(deadlock): ...`），相关设计文档在 `docs/superpowers/specs/2026-05-31-deadlock-prevention-design.md`。
