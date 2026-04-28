import os
import re
import yaml
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from .config import SKILLS_DIR


@dataclass
class TriggerWords:
    """触发词配置"""
    exact: List[str] = field(default_factory=list)   # 精确触发词
    fuzzy: List[str] = field(default_factory=list)   # 模糊触发词


@dataclass
class SkillTool:
    """Skill 关联的工具定义"""
    type: str  # "script" 或 "builtin"
    name: str  # 工具名称或脚本文件名
    args: Dict[str, Any] = field(default_factory=dict)  # 默认参数


@dataclass
class SkillIndex:
    """轻量级 skill 索引，用于注入 System Prompt"""
    name: str
    description: str
    folder_name: str  # 文件夹名称，用于后续加载完整内容（必须放在有默认值的字段之前）
    trigger_words: TriggerWords = field(default_factory=TriggerWords)
    trigger_condition: Optional[str] = None  # TRIGGER when 条件
    skip_condition: Optional[str] = None     # SKIP 条件
    workflow: bool = False                   # 是否为工作流型 skill
    references: List[str] = field(default_factory=list)  # 引用的额外文档
    tools: List[SkillTool] = field(default_factory=list) # 关联的工具


def parse_frontmatter(content: str) -> dict:
    """
    解析 SKILL.md 的 YAML frontmatter。
    格式：--- 开头和结尾的 YAML 块
    """
    if not content.startswith("---"):
        return {}

    # 找到第二个 --- 的位置
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    yaml_content = parts[1].strip()
    try:
        return yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        return {}


def scan_skill_index() -> List[SkillIndex]:
    """
    第一阶段：扫描所有 skill，生成轻量索引。
    只读取 name、description、trigger_words、trigger_condition 等，用于注入 System Prompt。
    """
    skill_indices: List[SkillIndex] = []

    if not os.path.exists(SKILLS_DIR):
        return skill_indices

    for item in os.listdir(SKILLS_DIR):
        folder_path = os.path.join(SKILLS_DIR, item)
        if not os.path.isdir(folder_path):
            continue

        md_path = os.path.join(folder_path, "SKILL.md")
        if not os.path.exists(md_path):
            md_path = os.path.join(folder_path, "README.md")

        if not os.path.exists(md_path):
            continue

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            frontmatter = parse_frontmatter(content)

            # 解析 name
            raw_name = frontmatter.get("name", item)
            if isinstance(raw_name, str):
                name = raw_name.strip()
            else:
                name = item

            # 解析 description
            raw_desc = frontmatter.get("description", f"提供 {name} 相关功能")
            if isinstance(raw_desc, str):
                description = raw_desc.strip()
            else:
                description = str(raw_desc)

            # 解析 trigger_words（支持对象格式和简单列表格式）
            trigger_words = TriggerWords()
            tw_data = frontmatter.get("trigger_words", {})

            if isinstance(tw_data, dict):
                # 对象格式：{ exact: [...], fuzzy: [...] }
                trigger_words.exact = tw_data.get("exact", [])
                trigger_words.fuzzy = tw_data.get("fuzzy", [])
            elif isinstance(tw_data, list):
                # 简单列表格式：全部作为 fuzzy 触发词
                trigger_words.fuzzy = tw_data

            # 解析新增字段
            trigger_condition = frontmatter.get("trigger_condition", None)
            skip_condition = frontmatter.get("skip_condition", None)
            workflow = frontmatter.get("workflow", False)

            # 解析 references
            references = frontmatter.get("references", [])
            if isinstance(references, str):
                references = [references]

            # 解析 tools
            tools = []
            raw_tools = frontmatter.get("tools", [])
            if isinstance(raw_tools, list):
                for tool_def in raw_tools:
                    if isinstance(tool_def, dict):
                        tool_type = tool_def.get("type", "builtin")
                        tool_name = tool_def.get("name") or tool_def.get("script") or tool_def.get("builtin", "")
                        tool_args = tool_def.get("args", None)
                        tools.append(SkillTool(type=tool_type, name=tool_name, args=tool_args))
                    elif isinstance(tool_def, str):
                        # 简单格式：直接是脚本名
                        tools.append(SkillTool(type="script", name=tool_def))

            skill_indices.append(SkillIndex(
                name=name,
                description=description,
                trigger_words=trigger_words,
                trigger_condition=trigger_condition,
                skip_condition=skip_condition,
                workflow=workflow,
                references=references,
                tools=tools,
                folder_name=item
            ))

        except Exception as e:
            print(f" \033[38;5;196m[警告] 技能包 {item} 索引扫描失败: {e}\033[0m")

    return skill_indices


def load_skill_content(skill_name: str) -> str:
    """
    第二阶段：按需加载某个 skill 的完整 SKILL.md 内容。

    参数:
        skill_name: skill 的 name 字段（来自索引）

    返回:
        完整的 SKILL.md 内容（不截断）
    """
    if not os.path.exists(SKILLS_DIR):
        return f"错误：技能目录不存在。"

    # 先通过索引查找匹配的 folder_name
    skill_indices = scan_skill_index()
    matched_folder = None

    for idx in skill_indices:
        if idx.name == skill_name:
            matched_folder = idx.folder_name
            break

    if not matched_folder:
        # 尝试直接用 skill_name 作为文件夹名
        potential_path = os.path.join(SKILLS_DIR, skill_name)
        if os.path.isdir(potential_path):
            matched_folder = skill_name

    if not matched_folder:
        available_names = [idx.name for idx in skill_indices]
        return f"错误：未找到名为 '{skill_name}' 的 skill。可用的 skill：{', '.join(available_names)}"

    md_path = os.path.join(SKILLS_DIR, matched_folder, "SKILL.md")
    if not os.path.exists(md_path):
        md_path = os.path.join(SKILLS_DIR, matched_folder, "README.md")

    if not os.path.exists(md_path):
        return f"错误：skill '{skill_name}' 没有 SKILL.md 或 README.md 文件。"

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"错误：读取 skill '{skill_name}' 内容失败：{str(e)}"


def get_skill_index_text() -> str:
    """
    生成用于注入 System Prompt 的 skill 索引文本。
    格式化输出，方便 LLM 快速浏览。
    """
    skill_indices = scan_skill_index()

    if not skill_indices:
        return "当前没有加载任何外部 skill。"

    lines = []
    for idx in skill_indices:
        # 构建触发词展示
        triggers = []
        if idx.trigger_words.exact:
            triggers.append(f"精确: {', '.join(idx.trigger_words.exact[:3])}")
        if idx.trigger_words.fuzzy:
            triggers.append(f"模糊: {', '.join(idx.trigger_words.fuzzy[:3])}")
        trigger_text = " | ".join(triggers) if triggers else "无触发词"

        # 截断 description 到 80 字符
        short_desc = idx.description[:80] + "..." if len(idx.description) > 80 else idx.description

        # 标记工作流型
        workflow_tag = " [工作流]" if idx.workflow else ""

        lines.append(f"- **{idx.name}**{workflow_tag}: {short_desc} ({trigger_text})")

    return "\n".join(lines)


def get_skill_dir(skill_name: str) -> Optional[str]:
    """
    获取 skill 的目录路径。
    """
    skill_indices = scan_skill_index()
    for idx in skill_indices:
        if idx.name == skill_name:
            return os.path.join(SKILLS_DIR, idx.folder_name)
    return None


def load_skill_full(skill_name: str) -> str:
    """
    三段式加载：索引 → 内容 → 引用资源

    参数:
        skill_name: skill 的 name 字段

    返回:
        完整内容（SKILL.md + 引用的额外文档）
    """
    # 第二段：加载 SKILL.md
    main_content = load_skill_content(skill_name)

    if main_content.startswith("错误"):
        return main_content

    # 第三段：加载引用资源
    skill_indices = scan_skill_index()
    skill_index = None
    for idx in skill_indices:
        if idx.name == skill_name:
            skill_index = idx
            break

    if not skill_index:
        return main_content

    skill_dir = get_skill_dir(skill_name)
    if not skill_dir:
        return main_content

    references_content = ""
    for ref_file in skill_index.references:
        ref_path = os.path.join(skill_dir, ref_file)
        if os.path.exists(ref_path):
            try:
                with open(ref_path, "r", encoding="utf-8") as f:
                    ref_content = f.read()
                references_content += f"\n\n---\n## [{ref_file}]\n\n{ref_content}"
            except Exception as e:
                references_content += f"\n\n---\n## [{ref_file}]\n（加载失败: {str(e)}）"

    return main_content + references_content


def match_condition(condition: str, text: str) -> bool:
    """
    匹配 TRIGGER/SKILL 条件。

    支持的格式：
    - "TRIGGER when: 用户输入包含关键词 X"
    - "用户输入包含 X" → 检查文本是否包含 X
    - "TRIGGER when: 用户输入包含 天气 或 多少度 或 下雨" → 检查是否包含任一关键词
    - 正则表达式：r"pattern"

    Returns:
        True 表示条件匹配
    """
    if not condition:
        return False

    # 提取条件内容（去掉 "TRIGGER when:" 或 "SKIP:" 前缀）
    condition_clean = condition.strip()
    for prefix in ["TRIGGER when:", "TRIGGER:", "SKIP:", "when:"]:
        if condition_clean.startswith(prefix):
            condition_clean = condition_clean[len(prefix):].strip()
            break

    # 检查是否是正则表达式
    if condition_clean.startswith("r\"") or condition_clean.startswith("r'"):
        try:
            pattern = condition_clean[2:-1]  # 去掉 r" 和 "
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            pass

    # 解析 "用户输入包含 X 或 Y 或 Z" 格式
    # 提取关键词列表
    text_lower = text.lower()

    # 查找 "包含" 后面的内容
    if "包含" in condition_clean:
        # 提取关键词部分
        parts = condition_clean.split("包含")
        if len(parts) >= 2:
            keywords_part = parts[-1].strip()
            # 解析 "或" 分隔的关键词
            keywords = re.split(r'\s+或\s+', keywords_part)
            for keyword in keywords:
                keyword = keyword.strip()
                if keyword and keyword.lower() in text_lower:
                    return True

    # 直接关键词匹配
    if condition_clean.lower() in text_lower:
        return True

    # import 匹配
    if "import" in condition_clean.lower():
        if condition_clean.lower() in text_lower:
            return True

    return False


def match_trigger_words(trigger_words: TriggerWords, text: str) -> bool:
    """
    匹配触发词（兼容旧格式）。
    """
    text_lower = text.lower()

    # 精确触发词：必须完全匹配
    for exact_word in trigger_words.exact:
        if exact_word.lower() == text_lower.strip():
            return True

    # 模糊触发词：包含即可
    for fuzzy_word in trigger_words.fuzzy:
        if fuzzy_word.lower() in text_lower:
            return True

    return False


def detect_trigger_skills(user_input: str) -> List[SkillIndex]:
    """
    检测用户输入中触发的 skill。

    优先级：
    1. skip_condition 优先检查（如果匹配则跳过）
    2. trigger_condition 检查
    3. trigger_words 检查（兼容旧格式）

    Returns:
        触发的 skill 索引列表
    """
    triggered = []
    skill_indices = scan_skill_index()

    for skill in skill_indices:
        # 1. 检查 skip_condition（优先）
        if skill.skip_condition and match_condition(skill.skip_condition, user_input):
            continue  # 跳过此 skill

        # 2. 检查 trigger_condition
        if skill.trigger_condition:
            if match_condition(skill.trigger_condition, user_input):
                triggered.append(skill)
                continue

        # 3. 检查 trigger_words（兼容旧格式）
        if match_trigger_words(skill.trigger_words, user_input):
            triggered.append(skill)

    return triggered


def get_skill_by_name(skill_name: str) -> Optional[SkillIndex]:
    """
    通过 name 获取 skill 索引。
    """
    skill_indices = scan_skill_index()
    for idx in skill_indices:
        if idx.name == skill_name:
            return idx
    return None


def get_skill_tools(skill_name: str) -> List[SkillTool]:
    """
    获取 skill 关联的工具列表。
    """
    skill = get_skill_by_name(skill_name)
    if skill:
        return skill.tools
    return []