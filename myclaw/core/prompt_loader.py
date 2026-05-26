import os
import yaml
from typing import Dict, Optional
from dataclasses import dataclass

# prompts 目录路径
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# 占位符映射
PLACEHOLDER_SKILL_INDEX = "{{SKILL_INDEX}}"
PLACEHOLDER_USER_PROFILE = "{{USER_PROFILE}}"
PLACEHOLDER_CONTEXT_SUMMARY = "{{CONTEXT_SUMMARY}}"
PLACEHOLDER_KNOWLEDGE_CONTEXT = "{{KNOWLEDGE_CONTEXT}}"

# 全局指令（在所有模板末尾统一追加）
GLOBAL_APPENDIX = """
【任务目录规范 (TASK FOLDER)】
创建文档（Word、PPT 等）时，必须先调用 'start_task_folder' 创建任务目录，然后在任务目录下进行所有操作（解压、编辑、打包等）。这样可以保持 office 工位整洁，也便于后续清理中间文件。
- 任务目录格式：tasks/task-YYYY-MM-DD-NNN
- 所有中间文件和最终产物都放在任务目录下
- 不要在 office 根目录直接操作文件
"""


@dataclass
class PersonaMeta:
    """人设元数据"""
    name: str
    description: str
    language: str


def parse_frontmatter(content: str) -> tuple[Dict, str]:
    """
    解析 Markdown 文件的 YAML frontmatter。

    Returns:
        (metadata, body): 元数据字典 + 正文内容
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    yaml_content = parts[1].strip()
    body = parts[2].strip()

    try:
        metadata = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        metadata = {}

    return metadata, body


def load_persona(persona_name: str = "default") -> tuple[PersonaMeta, str]:
    """
    加载指定人设的模板内容。

    Args:
        persona_name: 人设名称（default/professional/friendly/custom）

    Returns:
        (meta, template): 人设元数据 + 模板正文

    Raises:
        FileNotFoundError: 人设文件不存在
    """
    file_path = os.path.join(PROMPTS_DIR, f"{persona_name}.md")

    if not os.path.exists(file_path):
        # 兜底：使用 default
        file_path = os.path.join(PROMPTS_DIR, "default.md")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"人设模板文件不存在: {persona_name}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    metadata, body = parse_frontmatter(content)

    meta = PersonaMeta(
        name=metadata.get("name", persona_name),
        description=metadata.get("description", "未描述"),
        language=metadata.get("language", "zh-CN")
    )

    return meta, body


def build_system_prompt(
    persona_name: str = "default",
    skill_index: str = "",
    user_profile: str = "",
    context_summary: str = "",
    knowledge_context: str = ""
) -> str:
    """
    构建完整的系统提示词。

    Args:
        persona_name: 人设名称
        skill_index: Skill 索引文本
        user_profile: 用户画像内容
        context_summary: 近期对话摘要
        knowledge_context: 知识库召回内容

    Returns:
        完整的系统提示词
    """
    _, template = load_persona(persona_name)

    # 替换占位符
    prompt = template.replace(PLACEHOLDER_SKILL_INDEX, skill_index)
    prompt = prompt.replace(PLACEHOLDER_USER_PROFILE, user_profile)
    prompt = prompt.replace(PLACEHOLDER_CONTEXT_SUMMARY, context_summary)
    prompt = prompt.replace(PLACEHOLDER_KNOWLEDGE_CONTEXT, knowledge_context)

    # 追加全局指令（所有模板共享）
    prompt += GLOBAL_APPENDIX

    return prompt


def list_available_personas() -> list[PersonaMeta]:
    """
    列出所有可用的人设。

    Returns:
        人设元数据列表
    """
    personas = []

    if not os.path.exists(PROMPTS_DIR):
        return personas

    for filename in os.listdir(PROMPTS_DIR):
        if not filename.endswith(".md"):
            continue

        persona_name = filename[:-3]  # 移除 .md
        try:
            meta, _ = load_persona(persona_name)
            personas.append(meta)
        except Exception:
            pass

    return personas


def get_default_persona() -> tuple[PersonaMeta, str]:
    """
    获取默认人设（兜底使用）。

    Returns:
        (meta, template): 默认人设元数据 + 模板正文
    """
    return load_persona("default")