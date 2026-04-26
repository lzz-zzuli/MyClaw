# MyClaw

基于 LangGraph 的 AI Agent 框架，提供 REPL 交互式智能终端体验。

## 核心架构

```
myclaw/core/
├── agent.py          # LangGraph 状态机定义，agent_node 主逻辑
├── context.py        # AgentState 状态定义，上下文裁剪逻辑
├── provider.py       # 多厂商 LLM 适配工厂 (OpenAI/Anthropic/阿里/GLM/Ollama)
├── skill_loader.py   # Skill 两阶段加载：索引扫描 + 按需加载
├── bus.py            # asyncio.Queue 任务队列
├── heartbeat.py      # 定时任务心跳检测
├── logger.py         # 异步 JSONL 日志记录 + 消息归档
└── tools/
    ├── builtins.py   # 内置工具集
    └── base.py       # 工具基类和装饰器
```

**LangGraph 状态机流转**：
```
START -> agent_node -> tools_condition -> 有tool_call -> tools -> agent_node
                                      -> 无tool_call -> END
```

## 运行命令

```bash
# 配置模型提供商
myclaw config

# 启动 Agent REPL
myclaw run

# 运行测试
pytest tests/

# 安装依赖
pip install -r requirements.txt
```

## 开发约定

### 添加新工具
在 `myclaw/core/tools/builtins.py` 中使用 `@my_tool` 装饰器：
```python
from .base import my_tool

@my_tool
def my_new_tool(arg: str) -> str:
    """工具描述，会被自动注入到 LLM 的工具列表"""
    return "结果"
```

然后添加到 `BUILTIN_TOOLS` 列表。

### Skill 开发
放在 `workspace/office/skills/<skill_name>/` 目录，必须有 `SKILL.md` 文件：
```markdown
---
name: Skill名称
description: 简短描述
trigger_words:
  exact: [精确触发词]
  fuzzy: [模糊触发词]
---

## 知识内容
...
```

### 代码风格
- Python 3.10+ 兼容
- 使用 pydantic 进行数据验证
- 异步操作使用 asyncio

## 重要目录

| 目录 | 说明 |
|------|------|
| `workspace/` | 运行时数据目录 |
| `workspace/state.sqlite3` | LangGraph 状态机持久化 |
| `workspace/memory/` | 用户画像存储 (user_profile.md) |
| `workspace/office/` | **安全沙盒** - 唯一允许文件操作的空间 |
| `workspace/office/skills/` | Skill 卡槽目录 |
| `workspace/tasks.json` | 定时任务队列 |
| `logs/` | Agent 行为日志 + 对话归档 (JSONL 格式) |

## 环境变量配置

在 `.env` 文件中配置：

```bash
# 必须配置
DEFAULT_PROVIDER=aliyun     # openai, anthropic, aliyun, z.ai, ollama
DEFAULT_MODEL=glm-5         # 模型名称

# 对应 API Key
OPENAI_API_KEY=sk-xxx       # OpenAI 兼容接口使用
ANTHROPIC_API_KEY=sk-xxx    # 仅 Anthropic 时需要
```

参见 `.env.example` 了解完整配置选项。

## 注意事项

### 安全沙盒限制
- 所有文件读写操作必须限制在 `workspace/office/` 目录内
- Agent 会拒绝任何尝试突破沙盒的指令
- 这是核心安全协议，不可绕过

### 记忆系统
- **状态机记忆**: `state.sqlite3` - LangGraph 自动管理，保留最近 10 轮对话
- **对话摘要**: `state.sqlite3` (summary 字段) - 旧对话的压缩摘要，上下文裁剪时生成
- **对话归档**: `logs/*.jsonl` - 被裁剪的旧消息完整归档，便于审计和恢复
- **用户画像**: `memory/user_profile.md` - 通过 `save_user_profile` 工具更新

**上下文裁剪机制**：
```
对话超过 40 轮 → 归档旧消息到 JSONL → LLM 生成摘要 → 删除旧消息 → 保留最近 10 轮
```

### 多模型支持
通过 `provider.py` 支持多种 LLM：
- OpenAI (及兼容接口: 阿里云、腾讯云、GLM)
- Anthropic Claude
- Ollama (本地部署)