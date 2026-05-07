from datetime import datetime, timezone
from .base import my_tool, MyClawBaseTool, get_current_thread_id
import os
import json
import uuid
import threading
import yaml
from ..config import MEMORY_DIR, KNOWLEDGE_DIR, KNOWLEDGE_INDEX_FILE, TASKS_FILE
from ..skill_loader import load_skill_content, load_skill_full, get_skill_dir, get_skill_by_name
from .sandbox_tools import (
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell
)


tasks_lock = threading.Lock()
knowledge_lock = threading.Lock()
PROFILE_PATH = os.path.join(MEMORY_DIR, "user_profile.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_memory_id(note_id: str) -> str:
    safe = "".join(c for c in note_id.lower() if c.isalnum() or c in "-_")
    return safe[:32] or str(uuid.uuid4())[:8]


def _normalize_tags(tags) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw_tags = tags.replace("，", ",").split(",")
    elif isinstance(tags, list):
        raw_tags = tags
    else:
        raw_tags = [str(tags)]

    normalized = []
    for tag in raw_tags:
        value = str(tag).strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _knowledge_note_path(note_id: str) -> str:
    return os.path.join(KNOWLEDGE_DIR, f"{_normalize_memory_id(note_id)}.md")


def _ensure_knowledge_store():
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    if not os.path.exists(KNOWLEDGE_INDEX_FILE):
        with open(KNOWLEDGE_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def _load_knowledge_index() -> list[dict]:
    _ensure_knowledge_store()
    try:
        with open(KNOWLEDGE_INDEX_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_knowledge_index(index_items: list[dict]):
    _ensure_knowledge_store()
    with open(KNOWLEDGE_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_items, f, ensure_ascii=False, indent=2)


def _split_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content.strip()

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content.strip()

    try:
        metadata = yaml.safe_load(parts[1].strip()) or {}
    except yaml.YAMLError:
        metadata = {}

    return metadata, parts[2].strip()


def _dump_memory_note(metadata: dict, body: str) -> str:
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    body_text = body.strip()
    return f"---\n{frontmatter}\n---\n\n{body_text}\n"


def _load_memory_note_record(note_id: str) -> dict | None:
    note_path = _knowledge_note_path(note_id)
    if not os.path.exists(note_path):
        return None

    with open(note_path, "r", encoding="utf-8") as f:
        raw = f.read()

    metadata, body = _split_frontmatter(raw)
    return {
        "id": metadata.get("id", _normalize_memory_id(note_id)),
        "title": metadata.get("title", "未命名记忆"),
        "tags": _normalize_tags(metadata.get("tags", [])),
        "source": metadata.get("source", "user"),
        "created_at": metadata.get("created_at", ""),
        "updated_at": metadata.get("updated_at", ""),
        "kind": metadata.get("kind", "fact"),
        "content": body,
        "path": note_path,
    }


def _build_memory_excerpt(content: str, limit: int = 80) -> str:
    single_line = " ".join(content.split())
    if len(single_line) <= limit:
        return single_line
    return single_line[:limit] + "..."


def _upsert_knowledge_index_entry(record: dict):
    index_items = _load_knowledge_index()
    entry = {
        "id": record["id"],
        "title": record["title"],
        "tags": record["tags"],
        "source": record["source"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "kind": record["kind"],
        "excerpt": _build_memory_excerpt(record["content"]),
    }

    replaced = False
    for i, item in enumerate(index_items):
        if item.get("id") == record["id"]:
            index_items[i] = entry
            replaced = True
            break

    if not replaced:
        index_items.append(entry)

    index_items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    _save_knowledge_index(index_items)


def _remove_knowledge_index_entry(note_id: str):
    index_items = _load_knowledge_index()
    new_items = [item for item in index_items if item.get("id") != note_id]
    _save_knowledge_index(new_items)


def _score_memory_record(record: dict, query: str = "", tag: str = None, kind: str = None) -> int:
    score = 0
    text_parts = [record.get("title", ""), record.get("content", ""), " ".join(record.get("tags", []))]
    text = "\n".join(text_parts).lower()

    if kind and record.get("kind") != kind:
        return -1

    if tag:
        tag_value = tag.strip().lower()
        tags = [t.lower() for t in record.get("tags", [])]
        if tag_value in tags:
            score += 5
        else:
            return -1

    if query:
        tokens = [token.strip().lower() for token in query.replace("，", " ").replace(",", " ").split() if token.strip()]
        if not tokens:
            tokens = [query.strip().lower()]
        token_hits = 0
        for token in tokens:
            if token and token in text:
                token_hits += 1
                score += 3 if token in record.get("title", "").lower() else 1
        if token_hits == 0:
            return -1

    if not query and not tag and not kind:
        score = 1

    return score


def _hybrid_score_memory_record(
    record: dict,
    query: str = "",
    tag: str = None,
    kind: str = None,
    semantic_scores: dict | None = None,
    alpha: float = 0.6,
) -> float:
    """
    混合评分: 关键词 + 语义。
    alpha=0.6 时语义优先但关键词保底; alpha=0 退化为纯关键词。
    """
    keyword_raw = _score_memory_record(record, query=query, tag=tag, kind=kind)

    # kind/tag 硬过滤: 关键词因 kind/tag 不匹配返回 -1, 直接淘汰
    if keyword_raw < 0 and (kind or tag):
        return -1.0

    # 关键词归一化到 [0, 1]
    MAX_KEYWORD_SCORE = 20.0
    keyword_norm = min(max(keyword_raw, 0) / MAX_KEYWORD_SCORE, 1.0)

    # 语义评分
    note_id = record.get("id", "")
    semantic = 0.0
    if semantic_scores and note_id in semantic_scores:
        semantic = semantic_scores[note_id]

    # 无语义分数时 alpha 自动为 0
    effective_alpha = alpha if semantic_scores else 0.0

    # 混合评分
    final_score = effective_alpha * semantic + (1 - effective_alpha) * keyword_norm

    # 淘汰: 两个分数都是 0 且有查询条件
    if query and final_score == 0.0 and keyword_raw < 0:
        return -1.0

    return final_score


def get_relevant_memory_notes(query: str = "", summary: str = "", limit: int = 5) -> list[dict]:
    with knowledge_lock:
        index_items = _load_knowledge_index()

    if not index_items:
        return []

    query_text = (query or "").strip()
    summary_text = (summary or "").strip()
    combined_query = query_text if query_text else summary_text

    # 语义检索
    semantic_scores: dict[str, float] = {}
    alpha = 0.6

    if combined_query:
        try:
            from ..embedding_store import get_embedding_store
            store = get_embedding_store()
            if store.is_available():
                alpha = float(os.environ.get("EMBEDDING_ALPHA", "0.6"))
                semantic_results = store.search(combined_query, top_k=limit * 4)
                semantic_scores = {note_id: score for note_id, score in semantic_results}
        except Exception:
            pass

    # 混合评分
    scored = []
    for item in index_items:
        record = _load_memory_note_record(item.get("id", ""))
        if not record:
            continue
        score = _hybrid_score_memory_record(
            record, query=combined_query,
            semantic_scores=semantic_scores if semantic_scores else None,
            alpha=alpha,
        )
        if score >= 0:
            if query_text and summary_text and summary_text.lower() in record.get("content", "").lower():
                score += 0.05
            scored.append((score, record))

    scored.sort(key=lambda pair: (pair[0], pair[1].get("updated_at", "")), reverse=True)
    return [record for _, record in scored[:limit]]


@my_tool
def get_system_model_info() -> str:
    """
    获取当前 MyClaw 正在运行的底层大模型（LLM）型号和提供商信息。
    当用户询问"你是基于什么模型"、"你的底层大模型是什么"、"你是GPT还是GLM"、"现在用的什么模型"等身份问题时，调用此工具。
    """
    provider = os.getenv("DEFAULT_PROVIDER", "unknown")
    model = os.getenv("DEFAULT_MODEL", "unknown")
    
    if provider == "unknown" or model == "unknown":
        return "无法获取当前的系统模型配置，可能是环境变量未正确加载。"
        
    return f"当前使用的模型提供商(Provider)是: {provider}，具体型号(Model)是: {model}。"


@my_tool
def save_user_profile(new_content: str) -> str:
    """
    更新用户的全局显性记忆档案。
    当你发现用户的偏好发生改变，或者有新的重要事实需要记录时：
    1.请先调用 read_user_profile 获取当前的完整档案。
    2.在你的上下文中，将新信息融入档案，并删去冲突或过时的旧信息。
    3.将修改后的一整篇完整 Markdown 文本作为 new_content 参数传入此工具。
    注意：此操作将完全覆盖旧文件！请确保传入的是完整的最新档案。
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    return "记忆档案已成功覆写更新。新的人设画像已生效。"


@my_tool
def get_current_time() -> str:
    """
    获取当前的系统时间和日期。
    当用户询问"现在几点"、"今天星期几"、"今天几号"等与当前时间相关的问题时，调用此工具。
    """
    now = datetime.now()
    return f"当前本地系统时间是: {now.strftime('%Y-%m-%d %H:%M:%S')}"


import ast
import operator

# 安全数学运算符映射表（AST 白名单）
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,      # 负号
    ast.UAdd: operator.pos,      # 正号
}


def _safe_eval_math(expression: str) -> float:
    """
    基于 AST 白名单的安全数学表达式计算器。
    只允许：数字、加减乘除幂模、括号、正负号。
    拒绝：函数调用、属性访问、导入、字符串、列表等任何危险操作。
    """
    tree = ast.parse(expression, mode='eval')

    def _eval_node(node):
        if isinstance(node, ast.Constant):
            # Python 3.8+ 的常量节点
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value)}")

        elif isinstance(node, ast.Num):
            # Python 3.7 兼容的数字节点
            return node.n

        elif isinstance(node, ast.BinOp):
            # 二元运算：如 1 + 2
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](left, right)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")

        elif isinstance(node, ast.UnaryOp):
            # 一元运算：如 -5, +3
            operand = _eval_node(node.operand)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](operand)
            raise ValueError(f"不支持的一元运算符: {op_type.__name__}")

        elif isinstance(node, ast.Expression):
            # 顶层表达式节点
            return _eval_node(node.body)

        else:
            # 拒绝所有其他节点类型（函数调用、属性访问等）
            raise ValueError(f"禁止的表达式类型: {type(node).__name__}")

    return _eval_node(tree)


@my_tool
def calculator(expression: str) -> str:
    """
    一个安全的数学计算器。
    用于计算基础的数学表达式，例如: '3 * 5' 或 '100 / 4'。
    支持：加减乘除、幂运算、模运算、括号、正负号。
    不支持：函数调用、变量、字符串等（这是安全限制）。
    """
    try:
        result = _safe_eval_math(expression)
        return f"表达式 '{expression}' 的计算结果是: {result}"
    except ValueError as e:
        return f"计算出错：{str(e)}。请检查表达式是否只包含数字和数学运算符。"
    except SyntaxError:
        return f"计算出错：表达式语法无效。"
    except Exception as e:
        return f"计算出错：{str(e)}"


@my_tool
def save_memory_note(title: str, content: str, tags: str = "", kind: str = "fact", source: str = "user") -> str:
    """
    向知识库新增一条长期记忆。
    适用于需要跨会话保留的事实、偏好、项目背景，不适用于临时对话上下文。
    """
    with knowledge_lock:
        _ensure_knowledge_store()
        note_id = str(uuid.uuid4())[:8]
        normalized_tags = _normalize_tags(tags)
        now = _now_iso()
        record = {
            "id": note_id,
            "title": title.strip() or "未命名记忆",
            "tags": normalized_tags,
            "source": source.strip() or "user",
            "created_at": now,
            "updated_at": now,
            "kind": kind.strip() or "fact",
            "content": content.strip(),
        }
        note_path = _knowledge_note_path(note_id)
        metadata = {k: record[k] for k in ["id", "title", "tags", "source", "created_at", "updated_at", "kind"]}
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(_dump_memory_note(metadata, record["content"]))
        _upsert_knowledge_index_entry(record)

    # 增量嵌入 (锁外执行, 失败不影响写入)
    try:
        from ..embedding_store import get_embedding_store
        store = get_embedding_store()
        if store.is_available():
            store.embed_and_upsert(note_id, record["title"], record["content"], record["tags"])
    except Exception:
        pass

    return f"已写入知识库记忆 [ID: {note_id}] {record['title']}"


@my_tool
def list_memory_notes(kind: str = "", tag: str = "", limit: int = 20) -> str:
    """
    列出知识库中的记忆条目，可按 kind 或 tag 过滤。
    """
    with knowledge_lock:
        index_items = _load_knowledge_index()

    if not index_items:
        return "当前知识库为空。"

    filtered = []
    for item in index_items:
        if kind and item.get("kind") != kind:
            continue
        if tag:
            tags = [t.lower() for t in item.get("tags", [])]
            if tag.strip().lower() not in tags:
                continue
        filtered.append(item)

    if not filtered:
        return "没有符合条件的知识库记忆。"

    lines = ["当前知识库记忆："]
    for item in filtered[:max(1, limit)]:
        tags_text = ", ".join(item.get("tags", [])) if item.get("tags") else "无标签"
        lines.append(
            f"- [ID: {item.get('id')}] {item.get('title')} | kind: {item.get('kind')} | tags: {tags_text}"
        )
    return "\n".join(lines)


@my_tool
def read_memory_note(note_id: str) -> str:
    """
    按 ID 读取一条知识库记忆的完整内容。
    """
    with knowledge_lock:
        record = _load_memory_note_record(note_id)

    if not record:
        return f"未找到 ID 为 {note_id} 的知识库记忆。"

    tags_text = ", ".join(record.get("tags", [])) if record.get("tags") else "无标签"
    return (
        f"[ID: {record['id']}] {record['title']}\n"
        f"kind: {record['kind']}\n"
        f"source: {record['source']}\n"
        f"tags: {tags_text}\n"
        f"created_at: {record['created_at']}\n"
        f"updated_at: {record['updated_at']}\n\n"
        f"{record['content']}"
    )


@my_tool
def search_memory_notes(query: str = "", tag: str = "", kind: str = "", limit: int = 5) -> str:
    """
    按关键词、tag 或 kind 搜索知识库记忆 (支持语义检索)。
    """
    with knowledge_lock:
        index_items = _load_knowledge_index()

    if not index_items:
        return "当前知识库为空。"

    # 语义检索
    semantic_scores: dict[str, float] = {}
    alpha = 0.6

    if query.strip():
        try:
            from ..embedding_store import get_embedding_store
            store = get_embedding_store()
            if store.is_available():
                alpha = float(os.environ.get("EMBEDDING_ALPHA", "0.6"))
                semantic_results = store.search(query.strip(), top_k=limit * 4)
                semantic_scores = {note_id: score for note_id, score in semantic_results}
        except Exception:
            pass

    scored = []
    for item in index_items:
        record = _load_memory_note_record(item.get("id", ""))
        if not record:
            continue
        score = _hybrid_score_memory_record(
            record, query=query,
            tag=tag or None, kind=kind or None,
            semantic_scores=semantic_scores if semantic_scores else None,
            alpha=alpha,
        )
        if score >= 0:
            scored.append((score, record))

    if not scored:
        return "没有找到相关的知识库记忆。"

    scored.sort(key=lambda pair: (pair[0], pair[1].get("updated_at", "")), reverse=True)
    lines = ["搜索到的知识库记忆："]
    for score, record in scored[:max(1, limit)]:
        tags_text = ", ".join(record.get("tags", [])) if record.get("tags") else "无标签"
        lines.append(
            f"- [ID: {record['id']}] {record['title']} | score: {score:.3f} | kind: {record['kind']} | tags: {tags_text}"
        )
        lines.append(f"  摘要: {_build_memory_excerpt(record['content'], limit=120)}")
    return "\n".join(lines)


@my_tool
def update_memory_note(note_id: str, title: str = "", content: str = "", tags: str = "", kind: str = "", source: str = "") -> str:
    """
    更新一条已有的知识库记忆。
    未提供的字段会保留原值。
    """
    with knowledge_lock:
        record = _load_memory_note_record(note_id)
        if not record:
            return f"未找到 ID 为 {note_id} 的知识库记忆。"

        if title.strip():
            record["title"] = title.strip()
        if content.strip():
            record["content"] = content.strip()
        if tags.strip():
            record["tags"] = _normalize_tags(tags)
        if kind.strip():
            record["kind"] = kind.strip()
        if source.strip():
            record["source"] = source.strip()
        record["updated_at"] = _now_iso()

        metadata = {k: record[k] for k in ["id", "title", "tags", "source", "created_at", "updated_at", "kind"]}
        with open(record["path"], "w", encoding="utf-8") as f:
            f.write(_dump_memory_note(metadata, record["content"]))
        _upsert_knowledge_index_entry(record)

    # 增量重嵌入 (锁外执行, content_hash 变更时才重新调用 API)
    try:
        from ..embedding_store import get_embedding_store
        store = get_embedding_store()
        if store.is_available():
            store.embed_and_upsert(record["id"], record["title"], record["content"], record["tags"])
    except Exception:
        pass

    return f"知识库记忆 [ID: {record['id']}] 已更新。"


@my_tool
def delete_memory_note(note_id: str) -> str:
    """
    按 ID 删除一条知识库记忆。
    """
    with knowledge_lock:
        record = _load_memory_note_record(note_id)
        if not record:
            return f"未找到 ID 为 {note_id} 的知识库记忆。"
        if os.path.exists(record["path"]):
            os.remove(record["path"])
        _remove_knowledge_index_entry(record["id"])

    # 清理向量 (锁外执行)
    try:
        from ..embedding_store import get_embedding_store
        store = get_embedding_store()
        if store.is_available():
            store.remove(record["id"])
    except Exception:
        pass

    return f"知识库记忆 [ID: {record['id']}] 已删除。"


@my_tool
def schedule_task(target_time: str, description: str, repeat: str = None, repeat_count: int = None) -> str:
    """
    参数 target_time 必须是严格的格式："YYYY-MM-DD HH:MM:SS"（请先调用 get_current_time 获取当前时间，并在其基础上推算）。
    参数 description 是需要执行的动作或要说的话。
    
    【高级循环功能】：
    - repeat (可选): 设置重复频率。可选值为 "hourly", "daily", "weekly"。如果不重复请留空。
    - repeat_count (可选): 结合 repeat 使用，表示一共需要触发几次。
    
    【案例教学】：
    1. 用户说："以后每天8点提醒我喝牛奶" -> repeat="daily", repeat_count=None (无限循环)
    2. 用户说："接下来的3天，每天提醒我吃药" -> repeat="daily", repeat_count=3 (有限循环)
    3. 用户说："明早8点叫我起床" -> repeat=None, repeat_count=None (单次任务)

    【时间歧义严格确认协议 (AM/PM Ambiguity CRITICAL)】：
    当用户说出的时间存在 12 小时制的模糊性时（例如：只说了"7点"，没明确说早上还是晚上）：
    1. 你必须向用户提问确认是上午还是下午。
    2. 【死命令】：在用户明确回复"上午"或"下午"（或改为24小时制）之前，本工具处于【绝对锁定状态】！
    3. 就算用户发省略号（如"。。"）、发脾气、或者说无关内容，你也【绝对禁止】为了讨好用户而自行猜测时间！
    4. 严禁出现"抱歉多问了"、"默认早上"这种妥协行为。
    5. 如果用户不明确回答，你必须坚定地回复："抱歉，没有明确上下午，我无权为您设置闹钟。请明确告知时间段。"并立即中止工具调用。
    """
    try:
        datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "设定失败：时间格式错误，必须严格遵循 'YYYY-MM-DD HH:MM:SS' 格式。"

    with tasks_lock:
        tasks = []
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        tasks = json.loads(content)
            except Exception as e:
                return f"设定失败：读取任务队列异常 {str(e)}"

        new_task = {
            "id": str(uuid.uuid4())[:8],
            "thread_id": get_current_thread_id(),
            "target_time": target_time,
            "description": description,
            "repeat": repeat,
            "repeat_count": repeat_count
        }
        tasks.append(new_task)

        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"设定失败：写入任务队列异常 {str(e)}"

    msg = f" 任务已成功加入队列。首发时间：{target_time} | 任务：{description}"
    if repeat:
        msg += f" | 循环模式：{repeat} (共 {repeat_count if repeat_count else '无限'} 次)"
    return msg


@my_tool
def list_scheduled_tasks() -> str:
    """
    查看当前所有待处理的定时任务列表。
    当用户询问"我都有哪些任务"、"查一下闹钟"、"刚才定了什么"时调用此工具。
    """
    current_thread = get_current_thread_id()

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "当前没有任何定时任务。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return "任务列表为空。"
                tasks = json.loads(content)

            if not tasks:
                return "当前没有任何定时任务。"

            # 只显示当前会话的任务
            if current_thread:
                tasks = [t for t in tasks if t.get("thread_id") == current_thread]

            if not tasks:
                return "当前会话没有定时任务。"

            tasks.sort(key=lambda x: x['target_time'])

            res = " 当前待执行任务列表：\n"
            for t in tasks:
                res += f"- [ID: {t['id']}] 时间: {t['target_time']} | 任务: {t['description']}\n"
            return res
        except Exception as e:
            return f"查询失败：{str(e)}"
    

@my_tool
def delete_scheduled_task(task_id: str) -> str:
    """
    根据任务 ID 取消或删除一个定时任务。
    
    【强制性风险控制协议 (CRITICAL)】：
    删除操作具有不可逆性。
    1. 只要匹配到符合描述的任务数量 > 1。
    2. 无论用户语气多么确定，只要他没提供具体的任务 ID。
    
    【你必须执行的动作】：
    【禁止】在单次回复中针对同一个模糊描述发起多个删除工具调用。
    你必须先列出所有匹配的任务（1. 2. 3.），并询问用户：
    "发现了多个符合条件的提醒（列出列表），为了安全起见，请问是要全部删除，还是只删除其中几个？"
    必须要用户明确给出编号或者说确定全部删除，才能调用此工具！！
    严禁自作主张执行批量删除。
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "删除失败：任务列表文件不存在。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            new_tasks = [t for t in tasks if t['id'] != task_id]
            
            if len(new_tasks) == len(tasks):
                return f"删除失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(new_tasks, f, ensure_ascii=False, indent=2)
            
            return f" 任务 [ID: {task_id}] 已成功取消。"
        except Exception as e:
            return f"操作异常：{str(e)}"
    

@my_tool
def modify_scheduled_task(task_id: str, new_time: str = None, new_description: str = None) -> str:
    """
    修改现有定时任务的时间或内容。
    
    【强制性风险控制协议 (CRITICAL)】：
    1. 只要用户通过"模糊描述"（如：那个5天的任务、洗澡的任务）来要求修改，而没有直接提供 ID。
    2. 无论用户的话语看起来是单数还是复数（如："把5天的任务全改了"）。
    3. 只要系统中匹配到的任务数量 > 1。
    
    【你必须执行的动作】：
    禁止直接调用本工具！你必须向用户展示匹配到的所有任务列表，并强制询问：
    "我发现有 [N] 个任务符合描述（列出列表），请问你是要【全部修改】，还是修改其中【某几个】？（请告诉我编号或确认全部）"
    
    必须在用户回复"全部"或者指定了具体编号后，你才能继续操作！修改任务并非小事,这是为了安全！！
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "修改失败：任务列表为空。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            found = False
            for t in tasks:
                if t['id'] == task_id:
                    if new_time:
                        datetime.strptime(new_time, "%Y-%m-%d %H:%M:%S")
                        t['target_time'] = new_time
                    if new_description:
                        t['description'] = new_description
                    found = True
                    break
            
            if not found:
                return f"修改失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
                
            return f" 任务 [ID: {task_id}] 已成功更新。"
        except ValueError:
            return "修改失败：时间格式错误。"
        except Exception as e:
            return f"操作异常：{str(e)}"


@my_tool
def load_skill(skill_name: str, full: bool = True) -> str:
    """
    按需加载某个 skill 的内容。

    使用场景：
    1. 你已从 System Prompt 中的 skill 索引看到可用的 skill 列表
    2. 用户的问题与某个 skill 的触发词相关（如提到"毛泽东"、"毛选"等）
    3. 你判断需要深入了解该 skill 的方法论或工具

    参数:
        skill_name: skill 的 name 字段（来自索引列表）
        full: 是否加载完整内容（包含引用资源）。默认 True。

    返回:
        skill 的完整内容（SKILL.md + 引用的额外文档）
    """
    if full:
        return load_skill_full(skill_name)
    else:
        # 只加载 SKILL.md，不加载引用资源
        return load_skill_content(skill_name)


import subprocess


@my_tool
def execute_skill_script(skill_name: str, script_name: str, script_args: str = "") -> str:
    """
    执行 skill 目录下的脚本。

    使用场景：
    1. 工作流型 skill 定义了关联的脚本工具
    2. SKILL.md 中指定了如何使用脚本
    3. 你需要执行脚本来完成任务

    参数:
        skill_name: skill 的 name 字段
        script_name: 脚本文件名（如 weather_query.py）
        script_args: 传递给脚本的参数（如 "北京"）

    返回:
        脚本的执行结果
    """
    skill_dir = get_skill_dir(skill_name)
    if not skill_dir:
        return f"错误：未找到 skill '{skill_name}'"

    script_path = os.path.join(skill_dir, script_name)
    if not os.path.exists(script_path):
        return f"错误：skill '{skill_name}' 下不存在脚本 '{script_name}'"

    # skill 脚本在 office/skills 目录下，是受信任的沙盒内容
    # 直接执行，不通过 execute_office_shell（它有 python 黑名单）
    try:
        if script_name.endswith(".py"):
            # 使用 Python 解释器执行
            cmd = ["python", script_name]
            if script_args:
                # 将参数按空格分割
                cmd.extend(script_args.split())
        elif script_name.endswith(".sh"):
            cmd = ["./" + script_name]
            if script_args:
                cmd.extend(script_args.split())
        else:
            cmd = [script_name]
            if script_args:
                cmd.extend(script_args.split())

        result = subprocess.run(
            cmd,
            cwd=skill_dir,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )

        output = f"执行脚本: {script_name}\n"
        output += f"参数: {script_args}\n"
        output += f"退出码: {result.returncode}\n"

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            output += f"\n[输出]\n{stdout}"
        if stderr:
            output += f"\n[错误]\n{stderr}"

        if not stdout and not stderr and result.returncode == 0:
            output += "\n(执行成功，无输出)"

        return output

    except subprocess.TimeoutExpired:
        return f"错误：脚本执行超时（30s）"
    except Exception as e:
        return f"执行异常：{str(e)}"


BUILTIN_TOOLS = [
    get_current_time,
    calculator,
    save_user_profile,
    save_memory_note,
    list_memory_notes,
    read_memory_note,
    search_memory_notes,
    update_memory_note,
    delete_memory_note,
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell,
    get_system_model_info,
    schedule_task,
    list_scheduled_tasks,
    delete_scheduled_task,
    modify_scheduled_task,
    load_skill,
    execute_skill_script
]