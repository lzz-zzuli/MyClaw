<div align="center">

# MyClaw

### **当 AI 开始"黑箱操作"，你需要一双透视眼**

**下一代透明智能体架构** · Next-Gen Transparent Agent Architecture

[快速开始](#-快速开始) · [核心模块](#-核心模块) · [内置工具](#-内置工具)

</div>

---

> 🤖 **你的 AI 在背着你做什么？MyClaw 让所有行为无所遁形**
> 
> 🛡️ **安全已加固**：计算器采用 AST 白名单，沙盒实现符号链接防御、环境隔离、41 个危险命令黑名单

---

## 📖 简介

MyClaw 是一个**企业级透明可控智能体**，重新定义 AI 系统的可信边界：

- **🔍 白盒化决策** → 6 类事件审计 + JSONL 日志 + Rich 监控终端，所有行为可追溯
- **💾 对话归档** → 被裁剪的旧消息完整保存，不丢失任何历史细节
- **🛡️ 零信任执行** → 两段式调用（help → run）+ **安全沙盒加固**（AST 计算器 + 环境隔离 + 命令黑名单），事故率降低 80%
- **🧠 持续学习** → 双水位记忆系统（长期画像 + 短期摘要），越用越懂你
- **⚡ 复杂任务编排** → 心跳任务系统 + 可插拔技能，解放双手

---

## 🏗️ 核心模块

### 📦 模块概览

```
myclaw/core/
├── agent.py          # Agent 决策引擎（LangGraph 状态图）
├── context.py        # 上下文裁剪 + 状态定义
├── provider.py       # 多模型提供商适配器
├── session.py        # 多会话管理（元数据 + 命名）
├── bus.py            # 异步任务队列总线
├── heartbeat.py      # 心跳任务引擎
├── logger.py         # 审计日志系统
├── skill_loader.py   # 动态技能加载器
├── config.py         # 配置管理
└── tools/
    ├── base.py       # 工具装饰器 + thread_id 管理
    ├── builtins.py   # 内置工具集
    └── sandbox_tools.py  # 沙盒安全工具
```

---

### 1️⃣ agent.py - Agent 决策引擎

**核心大脑，使用 LangGraph 构建状态循环。**

#### 工作流程

```
用户输入 → agent_node (LLM决策) → tools_condition (判断是否调用工具)
                                        ↓ 是                    ↓ 否
                                   tool_node (执行)              END
                                        ↓
                                   agent_node (继续决策)
```

#### 关键函数

```python
from myclaw.core.agent import create_agent_app

# 创建 Agent 应用
app = create_agent_app(
    provider_name="openai",      # 模型提供商
    model_name="gpt-4o-mini",    # 模型名称
    checkpointer=memory          # 记忆存储
)

# 运行 Agent
result = app.invoke({"messages": [HumanMessage("你好")]})
```

#### 核心特性

- **双水位记忆注入**：长期画像 + 短期摘要自动注入系统提示词
- **上下文裁剪**：超过阈值自动压缩旧对话，归档完整历史，防止 Token 爆炸
- **审计埋点**：每步决策记录到日志，可追溯

---

### 2️⃣ context.py - 上下文管理

**管理对话状态和历史裁剪。**

#### 状态定义

```python
from myclaw.core.context import AgentState

state = AgentState(
    messages=[],     # 对话历史（自动累积）
    summary=""       # 上下文摘要
)
```

#### 上下文裁剪

```python
from myclaw.core.context import trim_context_messages

# 按回合裁剪，保证工具调用链完整
final_msgs, discarded_msgs = trim_context_messages(
    messages,
    trigger_turns=40,  # 超过 40 回合触发裁剪
    keep_turns=10      # 保留最近 10 回合
)
```

**裁剪逻辑：**
```
回合 1: HumanMessage → AIMessage → ToolMessage → AIMessage
        ↑ 整个回合要么全保留，要么全丢弃（保证完整性）
```

---

### 3️⃣ provider.py - 多模型适配器

**统一接口，支持多家 LLM 提供商。**

#### 支持的提供商

| 提供商 | 使用接口 |
|--------|----------|
| OpenAI | 原生 OpenAI API |
| Anthropic | 原生 Anthropic API |
| 阿里云、腾讯、Z.AI | OpenAI 兼容接口 |
| Ollama | 本地部署 |
| 其他 OpenAI 兼容 | 自定义 Base URL |

#### 使用方式

```python
from myclaw.core.provider import get_provider

# OpenAI
llm = get_provider(provider_name="openai", model_name="gpt-4o-mini")

# 阿里云（兼容接口）
llm = get_provider(provider_name="aliyun", model_name="qwen-max")

# Ollama 本地
llm = get_provider(provider_name="ollama", model_name="llama3")

# 自定义兼容接口
llm = get_provider(
    provider_name="other",
    model_name="custom-model",
    base_url="https://your-api.com/v1",
    api_key="your-key"
)
```

---

### 4️⃣ bus.py - 异步任务总线

**解耦用户输入和 Agent 处理。**

```python
from myclaw.core.bus import task_queue, emit_task

# 放入任务（不阻塞）
await emit_task("帮我查天气")

# 消费任务（Agent 工作循环）
user_input = await task_queue.get()
task_queue.task_done()  # 标记完成
```

**设计目的：**
- 用户输入和 Agent 处理并行运行
- 任务排队，不阻塞 UI
- 支持优雅退出（等待队列清空）

---

### 5️⃣ heartbeat.py - 心跳任务引擎

**后台自动触发定时任务。**

```python
from myclaw.core.heartbeat import pacemaker_loop

# 启动心跳协程（后台运行）
await pacemaker_loop(check_interval=10)  # 每 10 秒检查
```

**任务执行流程：**
```
每 10s 检查 tasks.json
    ↓
发现到期任务 → 放入 task_queue → Agent 自动执行
    ↓
循环任务 → 更新下次触发时间 → 继续等待
```

**支持的循环模式：**
- `hourly` - 每小时
- `daily` - 每天
- `weekly` - 每周

---

### 6️⃣ logger.py - 审计日志系统

**记录 Agent 的所有决策过程 + 对话归档。**

```python
from myclaw.core.logger import audit_logger

# 记录事件
audit_logger.log_event(
    thread_id="session_1",
    event="tool_call",
    tool="read_file",
    args={"filepath": "test.py"}
)

# 归档被裁剪的消息
audit_logger.log_archived_message(
    thread_id="session_1",
    message_type="human",
    message_id="msg_001",
    content="完整的消息内容",
    metadata={}
)
```

**记录的 6 类事件：**

| 事件 | 触发时机 | 记录内容 |
|------|----------|----------|
| `llm_input` | 发送给 LLM 前 | 消息数量 |
| `tool_call` | LLM 决定调用工具 | 工具名 + 参数 |
| `tool_result` | 工具执行完毕 | 结果摘要 |
| `ai_message` | LLM 直接回复 | 回复内容 |
| `system_action` | 系统操作 | 心跳任务等 |
| `message_archive` | 上下文裁剪时 | **完整消息归档** |

**日志格式：JSONL（每行一个 JSON）**
```bash
tail -f logs/session_1.jsonl  # 实时监控
grep "tool_call" logs/*.jsonl  # 搜索工具调用
grep "message_archive" logs/*.jsonl  # 查看归档消息
```

---

### 7️⃣ skill_loader.py - 动态技能加载

**自动扫描并加载可插拔技能。**

```python
from myclaw.core.skill_loader import load_dynamic_skills

# 加载 skills/ 目录下的所有技能
tools = load_dynamic_skills()
```

**两段式调用机制：**

```
用户: "帮我查北京天气"
    ↓
LLM: 调用 weather 技能，mode='help'  ← 先看说明书
    ↓
LLM: 看完说明书，决定调用 mode='run'，command="wttr.in Beijing"
    ↓
执行底层脚本 → 返回结果
```

**SKILL.md 格式：**
```markdown
---
name: weather
description: 获取天气预报
---

# Weather Skill

## 功能
获取全球城市的实时天气预报。

## 命令示例
curl "wttr.in/Beijing?format=3"
```

---

### 8️⃣ tools/sandbox_tools.py - 沙盒安全工具

**受限环境中的文件操作和 Shell 执行。**

#### 三大沙盒工具

```python
from myclaw.core.tools.sandbox_tools import (
    list_office_files,    # 列出文件
    read_office_file,     # 读取文件
    write_office_file,    # 写入文件
    execute_office_shell  # 执行 Shell 命令
)

# 列出文件
list_office_files("skills/")

# 读取文件（自动截断超长内容）
read_office_file("test.py")

# 写入文件（支持覆盖/追加）
write_office_file("output.txt", "内容", mode="w")

# 执行 Shell（受限）
execute_office_shell("python test.py")
```

#### 安全防御（2026-04 安全加固）

| 防御措施 | 说明 | 状态 |
|----------|------|------|
| **AST 白名单计算器** | 替换 `eval()`，只允许数字和数学运算符 | ✅ 已修复 |
| **符号链接防御** | `realpath()` 解析真实路径，防止 `ln -s` 绕过 | ✅ 已修复 |
| **环境变量隔离** | 白名单机制，API Key 等敏感信息不可访问 | ✅ 已修复 |
| **危险命令黑名单** | 拦截 41 个危险命令（curl/python/sudo 等） | ✅ 已修复 |
| 路径越权拦截 | 所有操作限制在 `workspace/office/` | ✅ 原有 |
| 五重正则拦截 | `../`、`/`、`~`、`\`、盘符全拦截 | ✅ 原有 |
| 超时熔断 | 命令执行 60 秒后强制终止 | ✅ 原有 |
| 输出截断 | 防止 Token 爆炸 | ✅ 原有 |

#### 详细安全说明

**计算器安全实现**：
```python
# 只允许：数字、加减乘除、幂、模、括号、正负号
# 拒绝：函数调用、属性访问、字符串、lambda 等
calculator("2 ** 10")      # ✅ 正常执行 → 1024
calculator("__import__")   # ❌ 已拦截 → 禁止的表达式类型
```

**沙盒环境隔离**：
```python
# 子进程只能访问白名单环境变量
_SAFE_ENV_WHITELIST = {
    "PATH": ...,
    "HOME": OFFICE_DIR,     # 强制指向沙盒，非真实 HOME
    "USER": "myclaw_sandbox",
    ...
}
# OPENAI_API_KEY 等敏感变量不可见
```

**危险命令拦截示例**：
```python
execute_office_shell("curl http://evil.com")  # ❌ 权限拒绝
execute_office_shell("python -c '...'")       # ❌ 权限拒绝
execute_office_shell("env")                   # ❌ 权限拒绝（防环境泄露）
execute_office_shell("ls")                    # ✅ 正常执行
```

---

## 🔧 内置工具

| 工具 | 功能 | 安全说明 | 示例 |
|------|------|----------|------|
| `get_current_time` | 获取当前时间 | 安全 | "现在几点了？" |
| `calculator` | 数学计算器 | **AST 白名单**，无 `eval` 风险 | "25 乘以 48 等于多少" |
| `schedule_task` | 创建定时任务 | 安全 | "每天早上 8 点提醒我喝水" |
| `list_scheduled_tasks` | 查看任务列表 | 安全 | "我都有哪些任务" |
| `delete_scheduled_task` | 删除任务 | 需确认（防误删） | "取消明天的会议提醒" |
| `save_user_profile` | 更新用户画像 | 安全 | "记住我喜欢喝冰美式" |
| `list_office_files` | 列出文件 | **符号链接防御** | "看看 office 里有什么" |
| `read_office_file` | 读取文件 | **符号链接防御** | "读取 readme.txt" |
| `write_office_file` | 写入文件 | **符号链接防御** | "创建 test.py" |
| `execute_office_shell` | 执行 Shell | **环境隔离 + 命令黑名单** | "运行 python test.py" |

---

## 🚀 快速开始

### 1️⃣ 安装

```bash
# 克隆项目
git clone https://github.com/your-repo/MyClaw.git
cd MyClaw

# 使用 uv 安装（推荐）
uv sync

# 或使用 pip
pip install -e .
```

### 2️⃣ 配置

```bash
# 启动交互式配置向导
myclaw config
```

配置向导会引导你：
1. 选择模型提供商（OpenAI / Anthropic / 阿里云 / Ollama 等）
2. 输入 API Key
3. 配置 Base URL（可选）
4. 自动测试连接

### 3️⃣ 运行

```bash
# 启动主程序（创建新会话）
myclaw run

# 启动监控终端（另一个终端）
myclaw monitor
```

---

## 📂 会话管理

MyClaw 支持**多会话隔离**，每个会话拥有独立的对话历史、日志和定时任务。

### 会话操作

| 命令 | 说明 |
|------|------|
| `myclaw run` | 创建新会话（自动生成 session_id） |
| `myclaw run -n "工作助手"` | 创建新会话并命名 |
| `myclaw run -l` | 显示历史会话列表（交互选择） |
| `myclaw run -r "会话名称"` | 恢复指定会话 |
| `/rename 新名字` | 在会话内重命名当前会话 |
| `/exit` | 退出当前会话（自动生成会话描述） |

### 会话数据存储

| 文件 | 说明 |
|------|------|
| `workspace/sessions.json` | 会话元数据（名称、描述、消息计数） |
| `workspace/state.sqlite3` | LangGraph 状态持久化（最近 10 轮对话 + 摘要） |
| `logs/{session_id}.jsonl` | 每个会话独立的审计日志 + **对话归档** |
| `workspace/tasks.json` | 定时任务（按 session_id 分离） |

### 上下文裁剪机制

当对话超过 40 覃时，自动触发裁剪：

```
对话超过 40 覃
    ↓
归档旧消息到 JSONL（完整保存）
    ↓
LLM 生成摘要（融合旧摘要 + 旧对话）
    ↓
删除 SQLite 中的旧消息
    ↓
保留最近 10 覃 + 摘要
```

**裁剪后数据分布：**
- `state.sqlite3`: 最近 10 覃对话 + 摘要（LLM 上下文使用）
- `logs/*.jsonl`: 被裁剪的完整消息（审计/恢复使用）

### 会话隔离机制

- **对话历史**：每个会话独立的 SQLite checkpoint
- **定时任务**：仅显示/触发当前会话的任务
- **审计日志**：每个会话独立 JSONL 文件
- **用户画像**：全局共享（所有会话可见）

---

## 📊 常用命令示例

| 类型 | 命令示例 | 说明 |
|------|----------|------|
| 🆕 新会话 | `myclaw run` | 创建新会话 |
| 📋 会话列表 | `myclaw run -l` | 显示历史会话 |
| 🔙 恢复会话 | `myclaw run -r "工作助手"` | 恢复指定会话 |
| ✏️ 重命名 | `/rename 项目讨论` | 重命名当前会话 |
| ⏰ 时间查询 | `现在几点了？` | 获取当前时间 |
| 🧮 数学计算 | `帮我算一下 25 乘以 48` | 调用计算器 |
| ⏲️ 定时任务 | `每天早上 8 点提醒我喝水` | 创建循环任务 |
| 📋 查看任务 | `我都有哪些任务` | 查看任务列表 |
| 📁 文件操作 | `看看 office 里有什么文件` | 列出工位文件 |
| 📖 读取文件 | `读取 readme.txt` | 读取文件内容 |
| 📝 创建文件 | `创建 test.py` | 写入新文件 |
| 💻 Shell | `运行 python test.py` | 执行命令 |
| 🚪 退出 | `/exit` | 退出程序 |

---

## 🏢 项目结构

```
MyClaw/
├── myclaw/                    # 核心包
│   └── core/
│       ├── agent.py           # Agent 决策引擎
│       ├── context.py         # 上下文裁剪
│       ├── provider.py        # 多模型适配
│       ├── session.py         # 会话管理
│       ├── bus.py             # 任务总线
│       ├── heartbeat.py       # 心跳引擎
│       ├── logger.py          # 审计日志
│       ├── skill_loader.py    # 技能加载
│       └── tools/
│           ├── builtins.py    # 内置工具
│           └── sandbox_tools.py  # 沙盒工具
├── entry/
│   ├── cli.py                 # 命令行入口
│   ├── main.py                # 主程序入口
│   └── monitor.py             # 监控终端
├── workspace/
│   ├── office/                # 沙盒工位
│   │   └── skills/            # 可插拔技能
│   ├── memory/
│   │   └── user_profile.md    # 用户画像
│   ├── sessions.json          # 会话元数据
│   ├── state.sqlite3          # LangGraph 状态持久化
│   └── tasks.json             # 定时任务队列
├── logs/
│   └── *.jsonl                # 审计日志 + 对话归档（每会话一个文件）
├── tests/                     # 测试套件
├── pyproject.toml             # 项目配置
└── README.md                  # 说明文档
```

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境

```bash
# 克隆项目
git clone https://github.com/your-repo/MyClaw.git
cd MyClaw

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装开发依赖
pip install -e ".[dev]"
```

### 提交规范

- `feat:` 新功能
- `fix:` 修复 bug
- `docs:` 文档更新
- `refactor:` 重构
- `test:` 测试相关

---

## 📄 许可证

MIT License

---

<div align="center">

**👾 MyClaw · 下一代透明智能体架构**

</div>