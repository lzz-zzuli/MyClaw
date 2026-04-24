import os
import yaml
from typing import List, Optional
from dataclasses import dataclass, field

from .config import SKILLS_DIR


@dataclass
class TriggerWords:
    """触发词配置"""
    exact: List[str] = field(default_factory=list)   # 精确触发词
    fuzzy: List[str] = field(default_factory=list)   # 模糊触发词


@dataclass
class SkillIndex:
    """轻量级 skill 索引，用于注入 System Prompt"""
    name: str
    description: str
    trigger_words: TriggerWords
    folder_name: str  # 文件夹名称，用于后续加载完整内容


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
    只读取 name、description、trigger_words，用于注入 System Prompt。
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

            skill_indices.append(SkillIndex(
                name=name,
                description=description,
                trigger_words=trigger_words,
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

        lines.append(f"- **{idx.name}**: {short_desc} ({trigger_text})")

    return "\n".join(lines)