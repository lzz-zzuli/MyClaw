# MyClaw

基于 LangGraph 的 AI Agent 框架，提供 REPL 交互式智能终端体验。

## 架构

```
myclaw/core/
├── agent.py           # LangGraph 状态机 + agent_node 主逻辑
├── context.py         # AgentState 定义 + 上下文裁剪
├── provider.py        # 多厂商 LLM 适配工厂 (OpenAI/Anthropic/阿里/GLM/Ollama)
├── skill_loader.py    # Skill 两阶段加载：索引扫描 + 按需加载
├── embedding_store.py # sqlite-vec 向量存储，语义检索
├── embedding_provider.py # Embedding 提供者 (Ollama/阿里云/OpenAI)
├── config.py         # 路径配置
├── bus.py            # asyncio.Queue 任务队列
├── heartbeat.py      # 定时任务心跳
├── logger.py         # JSONL 日志 + 消息归档
└── tools/
    ├── builtins.py   # 内置工具集
    ├── base.py       # 工具基类和 @my_tool 装饰器
    └── sandbox_tools.py # 沙盒工具
```

**状态机流转**：`START → agent_node → tools_condition → [有tool_call] → tools → agent_node → ... → END`

## 运行

```bash
myclaw config   # 配置模型
myclaw run       # 启动 REPL
pytest tests/    # 测试
```

## 添加工具

```python
from .base import my_tool

@my_tool
def my_tool(arg: str) -> str:
    """描述"""
    return "结果"
```

## Skill 开发

放在 `workspace/office/skills/<skill_name>/`，必须有 `SKILL.md`：
```markdown
---
name: 名称
description: 描述
trigger_words:
  exact: [精确触发词]
  fuzzy: [模糊触发词]
---
## 内容
```

## 核心目录

| 目录 | 说明 |
|------|------|
| `workspace/` | 运行时数据 |
| `workspace/state.sqlite3` | LangGraph 状态持久化 |
| `workspace/memory/` | 用户画像 + 知识库 |
| `workspace/office/` | **安全沙盒** - 唯一允许文件操作的空间 |
| `workspace/office/skills/` | Skill 卡槽 |
| `logs/` | JSONL 日志 |

## 记忆系统

- **状态机记忆**：`state.sqlite3` - 保留最近对话
- **对话摘要**：上下文超过阈值时压缩
- **知识库**：`vec_index.sqlite3` - Embedding 语义检索
- **对话归档**：`logs/*.jsonl`

## 环境变量

```bash
DEFAULT_PROVIDER=aliyun   # openai, anthropic, aliyun, z.ai, ollama
DEFAULT_MODEL=glm-5
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx
```

详见 `.env.example`。

## 安全沙盒

- 所有文件读写限制在 `workspace/office/` 内
- Agent 拒绝任何突破沙盒的指令