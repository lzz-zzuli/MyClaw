import os
import re
import urllib.parse
import yaml
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from .config import SKILLS_DIR


TEXT_RESOURCE_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".sh", ".html", ".css", ".xml"}
SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".ts"}
CONVENTIONAL_RESOURCE_DIRS = {"scripts", "references", "assets", "agents"}
IGNORED_RESOURCE_NAMES = {".DS_Store"}
MAX_AUTO_REFERENCE_FILES = 5
MAX_AUTO_REFERENCE_BYTES_PER_FILE = 80_000
MAX_AUTO_REFERENCE_TOTAL_BYTES = 200_000
MAX_RESOURCE_READ_BYTES = 200_000


@dataclass
class SkillTool:
    """Skill 关联的工具定义"""
    type: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResource:
    """Skill 附带资源索引"""
    path: str
    kind: str
    source: str
    size_bytes: int
    loadable: bool
    executable: bool


@dataclass
class SkillIndex:
    """轻量级 skill 索引，用于注入 System Prompt"""
    name: str
    description: str
    folder_name: str
    entry_file: str = "SKILL.md"
    references: List[str] = field(default_factory=list)
    tools: List[SkillTool] = field(default_factory=list)
    resources: List[SkillResource] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def parse_frontmatter(content: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter。"""
    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    yaml_content = parts[1].strip()
    try:
        return yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        return {}


def _normalize_resource_path(resource_path: str) -> Optional[str]:
    if not isinstance(resource_path, str):
        return None

    clean_path = resource_path.strip()
    if not clean_path or clean_path.startswith("#"):
        return None

    clean_path = urllib.parse.unquote(clean_path.split("#", 1)[0].strip())
    if not clean_path or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", clean_path):
        return None

    if clean_path.startswith("<") and clean_path.endswith(">"):
        clean_path = clean_path[1:-1]

    clean_path = clean_path.replace("\\", "/")
    if os.path.isabs(clean_path):
        return None

    normalized = os.path.normpath(clean_path).replace("\\", "/")
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        return None
    return normalized


def resolve_skill_resource_path(skill_dir: str, resource_path: str) -> Optional[str]:
    """安全解析 skill 内资源路径。"""
    normalized = _normalize_resource_path(resource_path)
    if not normalized:
        return None

    base = os.path.realpath(skill_dir)
    target = os.path.realpath(os.path.join(skill_dir, normalized))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:
        return None
    return target


def _relative_resource_path(skill_dir: str, absolute_path: str) -> str:
    return os.path.relpath(os.path.realpath(absolute_path), os.path.realpath(skill_dir)).replace(os.sep, "/")


def _classify_resource(relative_path: str) -> tuple[str, bool, bool]:
    lower_path = relative_path.lower()
    _, ext = os.path.splitext(lower_path)

    if os.path.basename(lower_path).startswith("license"):
        kind = "license"
    elif ext in {".md", ".markdown"}:
        kind = "markdown"
    elif ext in SCRIPT_EXTENSIONS:
        kind = "script"
    elif lower_path.startswith("assets/"):
        kind = "asset"
    else:
        kind = "other"

    loadable = ext in TEXT_RESOURCE_EXTENSIONS or kind in {"markdown", "license"}
    executable = ext in SCRIPT_EXTENSIONS
    return kind, loadable, executable


def _is_ignored_resource(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in IGNORED_RESOURCE_NAMES or part == "__pycache__" or part.startswith(".") for part in parts)


def _extract_markdown_links(content: str) -> List[str]:
    links = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", content):
        raw_link = match.group(1).strip()
        if not raw_link:
            continue
        if " " in raw_link and not os.path.exists(raw_link):
            raw_link = raw_link.split()[0]
        normalized = _normalize_resource_path(raw_link.strip('"\''))
        if normalized:
            links.append(normalized)
    return links


def discover_skill_resources(skill_dir: str, main_content: str, frontmatter: dict) -> List[SkillResource]:
    """发现官方 Claude Code Skill 的附带资源。"""
    resources: Dict[str, SkillResource] = {}

    def add_resource(relative_path: str, source: str):
        normalized = _normalize_resource_path(relative_path)
        if not normalized or _is_ignored_resource(normalized):
            return

        absolute_path = resolve_skill_resource_path(skill_dir, normalized)
        if not absolute_path or not os.path.isfile(absolute_path):
            return

        canonical_rel = _relative_resource_path(skill_dir, absolute_path)
        if _is_ignored_resource(canonical_rel) or canonical_rel in resources:
            return

        kind, loadable, executable = _classify_resource(canonical_rel)
        resources[canonical_rel] = SkillResource(
            path=canonical_rel,
            kind=kind,
            source=source,
            size_bytes=os.path.getsize(absolute_path),
            loadable=loadable,
            executable=executable
        )

    references = frontmatter.get("references", []) if isinstance(frontmatter, dict) else []
    if isinstance(references, str):
        references = [references]
    if isinstance(references, list):
        for ref in references:
            if isinstance(ref, str):
                add_resource(ref, "frontmatter")

    for link in _extract_markdown_links(main_content):
        add_resource(link, "markdown_link")

    for dirname in CONVENTIONAL_RESOURCE_DIRS:
        root = os.path.join(skill_dir, dirname)
        if not os.path.isdir(root):
            continue
        for current_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not _is_ignored_resource(d)]
            for filename in files:
                rel_path = _relative_resource_path(skill_dir, os.path.join(current_root, filename))
                add_resource(rel_path, "conventional_dir")

    try:
        for filename in os.listdir(skill_dir):
            if _is_ignored_resource(filename):
                continue
            file_path = os.path.join(skill_dir, filename)
            if not os.path.isfile(file_path):
                continue
            lower_name = filename.lower()
            if lower_name in {"skill.md", "readme.md"}:
                continue
            if lower_name.startswith("license") or lower_name.endswith((".md", ".markdown")):
                add_resource(filename, "root_file")
    except OSError:
        pass

    return sorted(resources.values(), key=lambda resource: resource.path)


def _parse_tools(frontmatter: dict) -> List[SkillTool]:
    tools = []
    raw_tools = frontmatter.get("tools", [])
    if not isinstance(raw_tools, list):
        return tools

    for tool_def in raw_tools:
        if isinstance(tool_def, dict):
            tool_type = str(tool_def.get("type", "builtin"))
            tool_name = tool_def.get("name") or tool_def.get("script") or tool_def.get("builtin", "")
            tool_args = tool_def.get("args", {})
            if tool_name:
                tools.append(SkillTool(type=tool_type, name=str(tool_name), args=tool_args if isinstance(tool_args, dict) else {}))
        elif isinstance(tool_def, str):
            tools.append(SkillTool(type="script", name=tool_def))
    return tools


def scan_skill_index() -> List[SkillIndex]:
    """第一阶段：扫描所有 skill，生成轻量索引。"""
    skill_indices: List[SkillIndex] = []

    if not os.path.exists(SKILLS_DIR):
        return skill_indices

    for item in os.listdir(SKILLS_DIR):
        folder_path = os.path.join(SKILLS_DIR, item)
        if not os.path.isdir(folder_path):
            continue

        entry_file = "SKILL.md"
        md_path = os.path.join(folder_path, entry_file)
        if not os.path.exists(md_path):
            entry_file = "README.md"
            md_path = os.path.join(folder_path, entry_file)

        if not os.path.exists(md_path):
            continue

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            frontmatter = parse_frontmatter(content)

            raw_name = frontmatter.get("name", item)
            name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else item

            raw_desc = frontmatter.get("description", f"提供 {name} 相关功能")
            description = raw_desc.strip() if isinstance(raw_desc, str) else str(raw_desc)

            references = frontmatter.get("references", [])
            if isinstance(references, str):
                references = [references]
            elif not isinstance(references, list):
                references = []
            references = [ref for ref in references if isinstance(ref, str)]

            standard_fields = {"name", "description", "references", "tools"}
            metadata = {key: value for key, value in frontmatter.items() if key not in standard_fields} if isinstance(frontmatter, dict) else {}

            skill_indices.append(SkillIndex(
                name=name,
                description=description,
                folder_name=item,
                entry_file=entry_file,
                references=references,
                tools=_parse_tools(frontmatter),
                resources=discover_skill_resources(folder_path, content, frontmatter),
                metadata=metadata
            ))

        except Exception as e:
            print(f" \033[38;5;196m[警告] 技能包 {item} 索引扫描失败: {e}\033[0m")

    return skill_indices


def _find_skill(skill_name: str) -> Optional[SkillIndex]:
    skill_indices = scan_skill_index()
    for idx in skill_indices:
        if idx.name == skill_name or idx.folder_name == skill_name:
            return idx
    return None


def load_skill_content(skill_name: str) -> str:
    """第二阶段：按需加载某个 skill 的完整 SKILL.md 内容。"""
    if not os.path.exists(SKILLS_DIR):
        return "错误：技能目录不存在。"

    skill_index = _find_skill(skill_name)
    if not skill_index:
        available_names = [idx.name for idx in scan_skill_index()]
        return f"错误：未找到名为 '{skill_name}' 的 skill。可用的 skill：{', '.join(available_names)}"

    md_path = os.path.join(SKILLS_DIR, skill_index.folder_name, skill_index.entry_file)
    if not os.path.exists(md_path):
        return f"错误：skill '{skill_name}' 没有 SKILL.md 或 README.md 文件。"

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"错误：读取 skill '{skill_name}' 内容失败：{str(e)}"


def _truncate_text(text: str, max_chars: int) -> str:
    single_line = " ".join(text.split())
    if len(single_line) <= max_chars:
        return single_line
    return single_line[:max_chars].rstrip() + "..."


def _format_resource_summary(resources: List[SkillResource]) -> str:
    if not resources:
        return "none"

    markdown = [resource.path for resource in resources if resource.kind == "markdown"]
    scripts = [resource.path for resource in resources if resource.kind == "script"]
    assets = [resource.path for resource in resources if resource.kind == "asset"]
    others = [resource.path for resource in resources if resource.kind not in {"markdown", "script", "asset"}]

    parts = []
    if markdown:
        parts.append("markdown: " + ", ".join(markdown[:5]) + ("..." if len(markdown) > 5 else ""))
    if scripts:
        parts.append("scripts: " + ", ".join(scripts[:5]) + ("..." if len(scripts) > 5 else ""))
    if assets:
        parts.append(f"assets: {len(assets)} file(s)")
    if others:
        parts.append("other: " + ", ".join(others[:3]) + ("..." if len(others) > 3 else ""))
    return "; ".join(parts) if parts else "none"


def get_skill_index_text(max_description_chars: int = 800, include_resources: bool = True) -> str:
    """生成用于注入 System Prompt 的 skill 索引文本。"""
    skill_indices = scan_skill_index()

    if not skill_indices:
        return "当前没有加载任何外部 skill。"

    lines = []
    for idx in skill_indices:
        lines.append(f"- Skill: {idx.name}")
        lines.append(f"  Description: {_truncate_text(idx.description, max_description_chars)}")

        if idx.tools:
            tool_text = ", ".join(f"{tool.type}: {tool.name}" for tool in idx.tools[:5])
            if len(idx.tools) > 5:
                tool_text += "..."
            lines.append(f"  Tools: {tool_text}")

        if include_resources:
            lines.append(f"  Resources: {_format_resource_summary(idx.resources)}")

    return "\n".join(lines)


def get_skill_dir(skill_name: str) -> Optional[str]:
    """获取 skill 的目录路径。"""
    skill = _find_skill(skill_name)
    if skill:
        return os.path.join(SKILLS_DIR, skill.folder_name)
    return None


def _format_resource_list(resources: List[SkillResource]) -> str:
    if not resources:
        return "无附带资源。"

    lines = ["Bundled Resources:"]
    for resource in resources:
        flags = []
        if resource.loadable:
            flags.append("loadable")
        if resource.executable:
            flags.append("executable")
        flag_text = f"; {', '.join(flags)}" if flags else ""
        lines.append(f"- {resource.path} ({resource.kind}; {resource.size_bytes} bytes; source={resource.source}{flag_text})")
    lines.append("To read a resource, call load_skill_resource(skill_name, resource_path).")
    lines.append("To execute a script, call execute_skill_script(skill_name, script_name, script_args).")
    return "\n".join(lines)


def _read_resource_text(skill_dir: str, resource: SkillResource) -> str:
    resource_path = resolve_skill_resource_path(skill_dir, resource.path)
    if not resource_path:
        raise ValueError("资源路径不安全")
    with open(resource_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def load_skill_full(skill_name: str) -> str:
    """三段式加载：索引 → 内容 → 资源清单与有限引用资源。"""
    main_content = load_skill_content(skill_name)

    if main_content.startswith("错误"):
        return main_content

    skill_index = _find_skill(skill_name)
    if not skill_index:
        return main_content

    skill_dir = get_skill_dir(skill_name)
    if not skill_dir:
        return main_content

    output_parts = [main_content, "\n\n---\n## Bundled Resources\n\n" + _format_resource_list(skill_index.resources)]

    auto_paths = []
    for ref in skill_index.references:
        normalized = _normalize_resource_path(ref)
        if normalized and normalized not in auto_paths:
            auto_paths.append(normalized)
    for resource in skill_index.resources:
        if resource.source == "markdown_link" and resource.kind == "markdown" and resource.path not in auto_paths:
            auto_paths.append(resource.path)

    loaded_count = 0
    loaded_bytes = 0
    skipped = []
    resource_map = {resource.path: resource for resource in skill_index.resources}

    for path in auto_paths:
        resource = resource_map.get(path)
        if not resource:
            resource_path = resolve_skill_resource_path(skill_dir, path)
            if not resource_path or not os.path.isfile(resource_path):
                continue
            kind, loadable, executable = _classify_resource(path)
            resource = SkillResource(path=path, kind=kind, source="frontmatter", size_bytes=os.path.getsize(resource_path), loadable=loadable, executable=executable)

        if resource.kind != "markdown" and resource.path not in skill_index.references:
            continue
        if not resource.loadable:
            skipped.append(f"{resource.path}: not a text resource")
            continue
        if loaded_count >= MAX_AUTO_REFERENCE_FILES:
            skipped.append(f"{resource.path}: auto-load file count limit reached")
            continue
        if resource.size_bytes > MAX_AUTO_REFERENCE_BYTES_PER_FILE:
            skipped.append(f"{resource.path}: too large for auto-load ({resource.size_bytes} bytes)")
            continue
        if loaded_bytes + resource.size_bytes > MAX_AUTO_REFERENCE_TOTAL_BYTES:
            skipped.append(f"{resource.path}: total auto-load size limit reached")
            continue

        try:
            ref_content = _read_resource_text(skill_dir, resource)
            output_parts.append(f"\n\n---\n## Auto-loaded resource: {resource.path}\n\n{ref_content}")
            loaded_count += 1
            loaded_bytes += resource.size_bytes
        except Exception as e:
            output_parts.append(f"\n\n---\n## Auto-loaded resource: {resource.path}\n（加载失败: {str(e)}）")

    if skipped:
        output_parts.append("\n\n---\n## Resources not auto-loaded\n\n" + "\n".join(f"- {item}. Use load_skill_resource to read it if needed." for item in skipped))

    return "".join(output_parts)


def list_skill_resources(skill_name: str) -> str:
    """列出某个 skill 的附带资源。"""
    skill = _find_skill(skill_name)
    if not skill:
        return f"错误：未找到 skill '{skill_name}'"
    return _format_resource_list(skill.resources)


def load_skill_resource(skill_name: str, resource_path: str) -> str:
    """读取 skill 目录内的指定资源。"""
    skill = _find_skill(skill_name)
    if not skill:
        return f"错误：未找到 skill '{skill_name}'"

    skill_dir = get_skill_dir(skill_name)
    if not skill_dir:
        return f"错误：未找到 skill '{skill_name}' 的目录"

    absolute_path = resolve_skill_resource_path(skill_dir, resource_path)
    if not absolute_path:
        return "错误：资源路径不安全。请使用 skill 目录内的相对路径。"
    if not os.path.exists(absolute_path):
        return f"错误：资源 '{resource_path}' 不存在。"
    if os.path.isdir(absolute_path):
        return f"错误：资源 '{resource_path}' 是目录，不能直接读取。"

    canonical_path = _relative_resource_path(skill_dir, absolute_path)
    size_bytes = os.path.getsize(absolute_path)
    kind, loadable, _ = _classify_resource(canonical_path)
    if not loadable:
        return f"资源 '{canonical_path}' 是 {kind} 类型，大小 {size_bytes} bytes，不适合以内联文本方式读取。"
    if size_bytes > MAX_RESOURCE_READ_BYTES:
        return f"错误：资源 '{canonical_path}' 过大（{size_bytes} bytes），超过单次读取上限 {MAX_RESOURCE_READ_BYTES} bytes。"

    try:
        with open(absolute_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"# Resource: {canonical_path}\n\n{content}"
    except Exception as e:
        return f"错误：读取资源 '{canonical_path}' 失败：{str(e)}"


def get_skill_by_name(skill_name: str) -> Optional[SkillIndex]:
    """通过 name 获取 skill 索引。"""
    return _find_skill(skill_name)


def get_skill_tools(skill_name: str) -> List[SkillTool]:
    """获取 skill 关联的工具列表。"""
    skill = get_skill_by_name(skill_name)
    if skill:
        return skill.tools
    return []
