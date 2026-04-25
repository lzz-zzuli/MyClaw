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

        # 验证配置项存在
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
        from myclaw.core.skill_loader import scan_skill_index, load_skill_content, get_skill_index_text, SkillIndex, TriggerWords

        # 确保函数和类存在
        self.assertTrue(callable(scan_skill_index))
        self.assertTrue(callable(load_skill_content))
        self.assertTrue(callable(get_skill_index_text))
        self.assertTrue(hasattr(SkillIndex, '__dataclass_fields__'))
        self.assertTrue(hasattr(TriggerWords, '__dataclass_fields__'))

    def test_trigger_words_dataclass(self):
        """测试 TriggerWords 数据类"""
        from myclaw.core.skill_loader import TriggerWords

        # 测试默认值
        tw = TriggerWords()
        self.assertEqual(tw.exact, [])
        self.assertEqual(tw.fuzzy, [])

        # 测试自定义值
        tw = TriggerWords(exact=["测试", "触发"], fuzzy=["模糊匹配"])
        self.assertEqual(tw.exact, ["测试", "触发"])
        self.assertEqual(tw.fuzzy, ["模糊匹配"])

    def test_skill_index_dataclass(self):
        """测试 SkillIndex 数据类"""
        from myclaw.core.skill_loader import SkillIndex, TriggerWords

        tw = TriggerWords(exact=["test"], fuzzy=["testing"])
        si = SkillIndex(
            name="test-skill",
            description="测试技能",
            trigger_words=tw,
            folder_name="test"
        )

        self.assertEqual(si.name, "test-skill")
        self.assertEqual(si.description, "测试技能")
        self.assertEqual(si.trigger_words.exact, ["test"])
        self.assertEqual(si.trigger_words.fuzzy, ["testing"])
        self.assertEqual(si.folder_name, "test")

    def test_parse_frontmatter_valid(self):
        """测试 YAML frontmatter 解析 - 有效格式"""
        from myclaw.core.skill_loader import parse_frontmatter

        content = """---
name: test-skill
description: 这是一个测试技能
trigger_words:
  exact: [测试, 触发]
  fuzzy: [模糊, 匹配]
---
# Skill 内容
"""
        result = parse_frontmatter(content)

        self.assertEqual(result["name"], "test-skill")
        self.assertEqual(result["description"], "这是一个测试技能")
        self.assertEqual(result["trigger_words"]["exact"], ["测试", "触发"])
        self.assertEqual(result["trigger_words"]["fuzzy"], ["模糊", "匹配"])

    def test_parse_frontmatter_simple_trigger_words(self):
        """测试 YAML frontmatter 解析 - 简单列表格式 trigger_words"""
        from myclaw.core.skill_loader import parse_frontmatter

        content = """---
name: simple-skill
description: 简单技能
trigger_words: [触发, 关键词]
---
内容
"""
        result = parse_frontmatter(content)

        self.assertEqual(result["trigger_words"], ["触发", "关键词"])

    def test_parse_frontmatter_invalid(self):
        """测试 YAML frontmatter 解析 - 无效格式"""
        from myclaw.core.skill_loader import parse_frontmatter

        # 没有 frontmarker
        content = "没有 frontmarker 的内容"
        result = parse_frontmatter(content)
        self.assertEqual(result, {})

        # 不完整的 frontmarker
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

        # 创建测试 skill
        skill_dir = os.path.join(self.skills_dir, "test-skill")
        os.makedirs(skill_dir)
        skill_md = """---
name: my-test-skill
description: 测试技能描述
trigger_words:
  exact: [测试]
  fuzzy: [模糊测试]
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
            self.assertEqual(indices[0].trigger_words.exact, ["测试"])
            self.assertEqual(indices[0].trigger_words.fuzzy, ["模糊测试"])
            self.assertEqual(indices[0].folder_name, "test-skill")
        finally:
            self._restore_skills_dir()

    def test_load_skill_content_success(self):
        """测试加载 skill 完整内容 - 成功"""
        from myclaw.core.skill_loader import load_skill_content

        # 创建测试 skill
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

    def test_get_skill_index_text_with_skills(self):
        """测试索引文本生成 - 包含 skills"""
        from myclaw.core.skill_loader import get_skill_index_text

        # 创建测试 skill
        skill_dir = os.path.join(self.skills_dir, "text-test")
        os.makedirs(skill_dir)
        skill_md = """---
name: text-test-skill
description: 文本测试技能
trigger_words:
  exact: [精确]
  fuzzy: [模糊]
---
内容
"""
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_md)

        self._patch_skills_dir()
        try:
            text = get_skill_index_text()

            self.assertIn("text-test-skill", text)
            self.assertIn("文本测试技能", text)
            self.assertIn("精确", text)
            self.assertIn("模糊", text)
        finally:
            self._restore_skills_dir()


class TestLoadSkillTool(unittest.TestCase):

    def test_load_skill_tool_in_builtins(self):
        """测试 load_skill 工具是否注册在 BUILTIN_TOOLS"""
        from myclaw.core.tools.builtins import BUILTIN_TOOLS

        tool_names = [t.name for t in BUILTIN_TOOLS]
        self.assertIn("load_skill", tool_names)

    def test_load_skill_tool_callable(self):
        """测试 load_skill 工具可调用"""
        from myclaw.core.tools.builtins import load_skill

        # 验证工具存在
        self.assertIsNotNone(load_skill)
        self.assertEqual(load_skill.name, "load_skill")


if __name__ == '__main__':
    unittest.main()