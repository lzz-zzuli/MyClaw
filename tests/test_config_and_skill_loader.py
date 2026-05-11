import unittest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestConfig(unittest.TestCase):

    def test_config_import(self):
        """测试配置模块导入"""
        from myclaw.core.config import WORKSPACE_DIR, MEMORY_DIR, PERSONAS_DIR, SCRIPTS_DIR, OFFICE_DIR, SKILLS_DIR, DB_PATH, TASKS_FILE

        self.assertIsInstance(WORKSPACE_DIR, str)
        self.assertIsInstance(MEMORY_DIR, str)
        self.assertIsInstance(PERSONAS_DIR, str)
        self.assertIsInstance(SCRIPTS_DIR, str)
        self.assertIsInstance(OFFICE_DIR, str)
        self.assertIsInstance(SKILLS_DIR, str)
        self.assertIsInstance(DB_PATH, str)
        self.assertIsInstance(TASKS_FILE, str)


class TestSkillLoader(unittest.TestCase):

    def setUp(self):
        """创建临时 skill 目录用于测试"""
        self.test_dir = tempfile.mkdtemp()
        self.skills_dir = os.path.join(self.test_dir, "skills")
        os.makedirs(self.skills_dir, exist_ok=True)

    def tearDown(self):
        """清理临时目录"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _patch_skills_dir(self):
        """临时替换 skill_loader 模块中的 SKILLS_DIR"""
        import myclaw.core.skill_loader as skill_loader
        import myclaw.core.config as config
        self._original_config_dir = config.SKILLS_DIR
        self._original_loader_dir = skill_loader.SKILLS_DIR
        config.SKILLS_DIR = self.skills_dir
        skill_loader.SKILLS_DIR = self.skills_dir

    def _restore_skills_dir(self):
        """恢复原始 SKILLS_DIR"""
        import myclaw.core.skill_loader as skill_loader
        import myclaw.core.config as config
        if hasattr(self, '_original_config_dir'):
            config.SKILLS_DIR = self._original_config_dir
            skill_loader.SKILLS_DIR = self._original_loader_dir

    def test_skill_loader_import(self):
        """测试技能加载器模块导入"""
        from myclaw.core.skill_loader import scan_skill_index, load_skill_content, get_skill_index_text, SkillIndex, SkillTool, SkillResource

        self.assertTrue(callable(scan_skill_index))
        self.assertTrue(callable(load_skill_content))
        self.assertTrue(callable(get_skill_index_text))
        self.assertTrue(hasattr(SkillIndex, '__dataclass_fields__'))
        self.assertTrue(hasattr(SkillTool, '__dataclass_fields__'))
        self.assertTrue(hasattr(SkillResource, '__dataclass_fields__'))

    def test_skill_index_dataclass(self):
        """测试 SkillIndex 数据类"""
        from myclaw.core.skill_loader import SkillIndex

        si = SkillIndex(
            name="test-skill",
            description="测试技能",
            folder_name="test"
        )

        self.assertEqual(si.name, "test-skill")
        self.assertEqual(si.description, "测试技能")
        self.assertEqual(si.folder_name, "test")
        self.assertEqual(si.entry_file, "SKILL.md")
        self.assertEqual(si.tools, [])
        self.assertEqual(si.resources, [])

    def test_parse_frontmatter_valid(self):
        """测试 YAML frontmatter 解析 - 有效格式"""
        from myclaw.core.skill_loader import parse_frontmatter

        content = """---
name: test-skill
description: 这是一个测试技能
tools:
  - type: script
    name: run.py
---
# Skill 内容
"""
        result = parse_frontmatter(content)

        self.assertEqual(result["name"], "test-skill")
        self.assertEqual(result["description"], "这是一个测试技能")
        self.assertEqual(result["tools"][0]["name"], "run.py")

    def test_parse_frontmatter_invalid(self):
        """测试 YAML frontmatter 解析 - 无效格式"""
        from myclaw.core.skill_loader import parse_frontmatter

        content = "没有 frontmarker 的内容"
        result = parse_frontmatter(content)
        self.assertEqual(result, {})

        content = "---\nname: test\n没有结束 marker"
        result = parse_frontmatter(content)
        self.assertEqual(result, {})

    def test_scan_skill_index_empty_directory(self):
        """测试索引扫描 - 空目录"""
        from myclaw.core.skill_loader import scan_skill_index

        self._patch_skills_dir()
        try:
            indices = scan_skill_index()
            self.assertEqual(indices, [])
        finally:
            self._restore_skills_dir()

    def test_scan_skill_index_with_skill(self):
        """测试索引扫描 - 包含 skill"""
        from myclaw.core.skill_loader import scan_skill_index

        skill_dir = os.path.join(self.skills_dir, "test-skill")
        os.makedirs(skill_dir)
        skill_md = """---
name: my-test-skill
description: 测试技能描述
tools:
  - type: script
    name: run.py
---
# 内容
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)

        self._patch_skills_dir()
        try:
            indices = scan_skill_index()

            self.assertEqual(len(indices), 1)
            self.assertEqual(indices[0].name, "my-test-skill")
            self.assertEqual(indices[0].description, "测试技能描述")
            self.assertEqual(indices[0].folder_name, "test-skill")
            self.assertEqual(indices[0].tools[0].name, "run.py")
        finally:
            self._restore_skills_dir()

    def test_scan_official_skill_minimal_frontmatter_and_metadata(self):
        """测试官方 Claude Code Skill 的最小 frontmatter 和未知字段"""
        from myclaw.core.skill_loader import scan_skill_index

        skill_dir = os.path.join(self.skills_dir, "pptx")
        os.makedirs(skill_dir)
        skill_md = """---
name: pptx
description: Use this skill any time a .pptx file is involved. Do NOT use for PDFs.
license: Proprietary
compatibility: claude-code
---
# PPTX Skill
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)

        self._patch_skills_dir()
        try:
            indices = scan_skill_index()

            self.assertEqual(len(indices), 1)
            self.assertEqual(indices[0].name, "pptx")
            self.assertEqual(indices[0].description, "Use this skill any time a .pptx file is involved. Do NOT use for PDFs.")
            self.assertEqual(indices[0].metadata["license"], "Proprietary")
            self.assertEqual(indices[0].metadata["compatibility"], "claude-code")
        finally:
            self._restore_skills_dir()

    def test_scan_keeps_legacy_trigger_fields_only_as_metadata(self):
        """测试旧触发字段不再参与索引模型，只作为未知元数据保留"""
        from myclaw.core.skill_loader import scan_skill_index

        skill_dir = os.path.join(self.skills_dir, "legacy")
        os.makedirs(skill_dir)
        skill_md = """---
name: legacy
description: Use this skill by description.
trigger_words: [旧触发词]
trigger_condition: old condition
skip_condition: old skip
workflow: true
---
# Legacy
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)

        self._patch_skills_dir()
        try:
            index = scan_skill_index()[0]

            self.assertFalse(hasattr(index, "trigger_words"))
            self.assertFalse(hasattr(index, "trigger_condition"))
            self.assertFalse(hasattr(index, "skip_condition"))
            self.assertFalse(hasattr(index, "workflow"))
            self.assertEqual(index.metadata["trigger_words"], ["旧触发词"])
            self.assertEqual(index.metadata["workflow"], True)
        finally:
            self._restore_skills_dir()

    def test_discover_official_skill_resources(self):
        """测试官方 Skill 的 scripts/references/assets 和 Markdown 链接资源发现"""
        from myclaw.core.skill_loader import scan_skill_index

        skill_dir = os.path.join(self.skills_dir, "pptx")
        os.makedirs(os.path.join(skill_dir, "scripts"))
        os.makedirs(os.path.join(skill_dir, "references"))
        os.makedirs(os.path.join(skill_dir, "assets"))
        os.makedirs(os.path.join(skill_dir, "__pycache__"))

        skill_md = """---
name: pptx
description: Use this skill any time a .pptx file is involved.
---
# PPTX Skill
Read [editing.md](editing.md) and [schema](references/schema.md).
"""
        files = {
            "SKILL.md": skill_md,
            "editing.md": "# Editing\nInstructions",
            "pptxgenjs.md": "# PPTXGenJS",
            "scripts/thumbnail.py": "print('thumb')",
            "references/schema.md": "# Schema",
            "assets/template.pptx": "binary-ish",
            "LICENSE.txt": "license",
            ".DS_Store": "ignored",
            "__pycache__/x.pyc": "ignored",
        }
        for rel_path, content in files.items():
            path = os.path.join(skill_dir, rel_path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        self._patch_skills_dir()
        try:
            indices = scan_skill_index()
            resources = {resource.path: resource for resource in indices[0].resources}

            self.assertIn("editing.md", resources)
            self.assertEqual(resources["editing.md"].source, "markdown_link")
            self.assertIn("pptxgenjs.md", resources)
            self.assertIn("scripts/thumbnail.py", resources)
            self.assertTrue(resources["scripts/thumbnail.py"].executable)
            self.assertIn("references/schema.md", resources)
            self.assertIn("assets/template.pptx", resources)
            self.assertEqual(resources["assets/template.pptx"].kind, "asset")
            self.assertIn("LICENSE.txt", resources)
            self.assertNotIn(".DS_Store", resources)
            self.assertNotIn("__pycache__/x.pyc", resources)
        finally:
            self._restore_skills_dir()

    def test_load_skill_content_success(self):
        """测试加载 skill 完整内容 - 成功"""
        from myclaw.core.skill_loader import load_skill_content

        skill_dir = os.path.join(self.skills_dir, "load-test")
        os.makedirs(skill_dir)
        skill_content = """---
name: load-test-skill
description: 加载测试
---
# 详细内容
这是完整的 skill 内容。
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)

        self._patch_skills_dir()
        try:
            result = load_skill_content("load-test-skill")

            self.assertIn("name: load-test-skill", result)
            self.assertIn("详细内容", result)
            self.assertIn("这是完整的 skill 内容", result)
        finally:
            self._restore_skills_dir()

    def test_load_skill_full_auto_loads_markdown_links_and_lists_resources(self):
        """测试完整加载会返回资源清单并自动加载正文链接的 Markdown"""
        from myclaw.core.skill_loader import load_skill_full

        skill_dir = os.path.join(self.skills_dir, "pptx")
        os.makedirs(os.path.join(skill_dir, "scripts"))
        skill_content = """---
name: pptx
description: Use this skill any time a .pptx file is involved.
---
# PPTX Skill
Read [editing.md](editing.md).
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)
        with open(os.path.join(skill_dir, "editing.md"), "w", encoding="utf-8") as f:
            f.write("# Editing\nDetailed workflow")
        with open(os.path.join(skill_dir, "scripts", "thumbnail.py"), "w", encoding="utf-8") as f:
            f.write("print('thumb')")

        self._patch_skills_dir()
        try:
            result = load_skill_full("pptx")

            self.assertIn("## Bundled Resources", result)
            self.assertIn("editing.md", result)
            self.assertIn("scripts/thumbnail.py", result)
            self.assertIn("## Auto-loaded resource: editing.md", result)
            self.assertIn("Detailed workflow", result)
        finally:
            self._restore_skills_dir()

    def test_load_skill_resource_rejects_path_escape(self):
        """测试 skill resource 读取与路径逃逸防护"""
        from myclaw.core.skill_loader import load_skill_resource

        skill_dir = os.path.join(self.skills_dir, "docx")
        os.makedirs(os.path.join(skill_dir, "references"))
        skill_content = """---
name: docx
description: Use this skill for Word documents.
---
# DOCX Skill
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)
        with open(os.path.join(skill_dir, "references", "schema.md"), "w", encoding="utf-8") as f:
            f.write("# Schema")

        self._patch_skills_dir()
        try:
            ok = load_skill_resource("docx", "references/schema.md")
            blocked_parent = load_skill_resource("docx", "../secret.md")
            blocked_abs = load_skill_resource("docx", "/etc/passwd")

            self.assertIn("# Resource: references/schema.md", ok)
            self.assertIn("# Schema", ok)
            self.assertIn("路径不安全", blocked_parent)
            self.assertIn("路径不安全", blocked_abs)
        finally:
            self._restore_skills_dir()

    def test_load_skill_content_not_found(self):
        """测试加载 skill 完整内容 - skill 不存在"""
        from myclaw.core.skill_loader import load_skill_content

        self._patch_skills_dir()
        try:
            result = load_skill_content("non-existent-skill")

            self.assertIn("错误", result)
            self.assertIn("未找到", result)
        finally:
            self._restore_skills_dir()

    def test_get_skill_index_text_empty(self):
        """测试索引文本生成 - 空目录"""
        from myclaw.core.skill_loader import get_skill_index_text

        self._patch_skills_dir()
        try:
            text = get_skill_index_text()
            self.assertIn("没有加载任何外部 skill", text)
        finally:
            self._restore_skills_dir()

    def test_get_skill_index_text_description_only(self):
        """测试索引文本只展示 description、tools 和 resources"""
        from myclaw.core.skill_loader import get_skill_index_text

        skill_dir = os.path.join(self.skills_dir, "docx")
        os.makedirs(skill_dir)
        long_description = "Use this skill whenever the user wants to create, read, edit, or manipulate Word documents. Triggers include .docx and Word document requests. Do NOT use for PDFs."
        skill_md = f"""---
name: docx
description: "{long_description}"
trigger_words: [legacy]
---
# DOCX
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)

        self._patch_skills_dir()
        try:
            text = get_skill_index_text()

            self.assertIn("Skill: docx", text)
            self.assertIn("Do NOT use for PDFs", text)
            self.assertIn("Resources:", text)
            self.assertNotIn("Triggering", text)
            self.assertNotIn("trigger_words", text)
            self.assertNotIn("无触发词", text)
        finally:
            self._restore_skills_dir()


class TestLoadSkillTool(unittest.TestCase):

    def test_load_skill_tool_in_builtins(self):
        """测试 skill 工具是否注册在 BUILTIN_TOOLS"""
        from myclaw.core.tools.builtins import BUILTIN_TOOLS

        tool_names = [t.name for t in BUILTIN_TOOLS]
        self.assertIn("load_skill", tool_names)
        self.assertIn("list_skill_resources", tool_names)
        self.assertIn("load_skill_resource", tool_names)

    def test_load_skill_tool_callable(self):
        """测试 load_skill 工具可调用"""
        from myclaw.core.tools.builtins import load_skill

        self.assertIsNotNone(load_skill)
        self.assertEqual(load_skill.name, "load_skill")


if __name__ == '__main__':
    unittest.main()
