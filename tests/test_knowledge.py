import unittest
import os
import sys
import tempfile
import shutil
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestKnowledgeBase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.knowledge_dir = os.path.join(self.temp_dir, "knowledge")
        os.makedirs(self.knowledge_dir, exist_ok=True)
        self.index_file = os.path.join(self.knowledge_dir, "index.json")

        import myclaw.core.tools.builtins as builtins
        self._orig_knowledge_dir = builtins.KNOWLEDGE_DIR
        self._orig_index_file = builtins.KNOWLEDGE_INDEX_FILE
        builtins.KNOWLEDGE_DIR = self.knowledge_dir
        builtins.KNOWLEDGE_INDEX_FILE = self.index_file

    def tearDown(self):
        import myclaw.core.tools.builtins as builtins
        builtins.KNOWLEDGE_DIR = self._orig_knowledge_dir
        builtins.KNOWLEDGE_INDEX_FILE = self._orig_index_file
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_memory_note(self):
        from myclaw.core.tools.builtins import save_memory_note
        result = save_memory_note.invoke({
            "title": "测试记忆",
            "content": "这是一条测试记忆内容",
            "tags": "测试,单元测试",
            "kind": "fact"
        })
        self.assertIn("已写入知识库记忆", result)
        self.assertIn("测试记忆", result)

        # 验证索引文件已创建
        with open(self.index_file, "r", encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["title"], "测试记忆")
        self.assertIn("测试", index[0]["tags"])

    def test_list_memory_notes_empty(self):
        from myclaw.core.tools.builtins import list_memory_notes
        result = list_memory_notes.invoke({})
        self.assertIn("知识库为空", result)

    def test_list_memory_notes_with_data(self):
        from myclaw.core.tools.builtins import save_memory_note, list_memory_notes
        save_memory_note.invoke({"title": "记忆A", "content": "内容A", "tags": "tag1"})
        save_memory_note.invoke({"title": "记忆B", "content": "内容B", "tags": "tag2"})

        result = list_memory_notes.invoke({})
        self.assertIn("记忆A", result)
        self.assertIn("记忆B", result)

    def test_read_memory_note(self):
        from myclaw.core.tools.builtins import save_memory_note, read_memory_note
        save_result = save_memory_note.invoke({
            "title": "可读记忆",
            "content": "详细内容在这里",
            "tags": "阅读",
            "kind": "fact"
        })
        note_id = save_result.split("[ID: ")[1].split("]")[0]

        result = read_memory_note.invoke({"note_id": note_id})
        self.assertIn("可读记忆", result)
        self.assertIn("详细内容在这里", result)
        self.assertIn("fact", result)

    def test_read_nonexistent_note(self):
        from myclaw.core.tools.builtins import read_memory_note
        result = read_memory_note.invoke({"note_id": "nonexistent"})
        self.assertIn("未找到", result)

    def test_search_memory_notes_by_keyword(self):
        from myclaw.core.tools.builtins import save_memory_note, search_memory_notes
        save_memory_note.invoke({"title": "Python技巧", "content": "列表推导式很强大", "tags": "编程"})
        save_memory_note.invoke({"title": "午餐偏好", "content": "喜欢吃辣", "tags": "饮食"})

        result = search_memory_notes.invoke({"query": "Python"})
        self.assertIn("Python技巧", result)
        self.assertNotIn("午餐偏好", result)

    def test_search_memory_notes_by_tag(self):
        from myclaw.core.tools.builtins import save_memory_note, search_memory_notes
        save_memory_note.invoke({"title": "项目A", "content": "前端重构", "tags": "工作,前端"})
        save_memory_note.invoke({"title": "读书笔记", "content": "毛选第一卷", "tags": "阅读"})

        result = search_memory_notes.invoke({"tag": "工作"})
        self.assertIn("项目A", result)
        self.assertNotIn("读书笔记", result)

    def test_search_empty_knowledge(self):
        from myclaw.core.tools.builtins import search_memory_notes
        result = search_memory_notes.invoke({"query": "anything"})
        self.assertIn("知识库为空", result)

    def test_update_memory_note(self):
        from myclaw.core.tools.builtins import save_memory_note, update_memory_note, read_memory_note
        save_result = save_memory_note.invoke({
            "title": "旧标题",
            "content": "旧内容",
            "tags": "旧标签"
        })
        note_id = save_result.split("[ID: ")[1].split("]")[0]

        update_result = update_memory_note.invoke({
            "note_id": note_id,
            "title": "新标题",
            "content": "新内容"
        })
        self.assertIn("已更新", update_result)

        read_result = read_memory_note.invoke({"note_id": note_id})
        self.assertIn("新标题", read_result)
        self.assertIn("新内容", read_result)

    def test_update_nonexistent_note(self):
        from myclaw.core.tools.builtins import update_memory_note
        result = update_memory_note.invoke({"note_id": "nonexistent", "title": "xxx"})
        self.assertIn("未找到", result)

    def test_delete_memory_note(self):
        from myclaw.core.tools.builtins import save_memory_note, delete_memory_note, list_memory_notes
        save_result = save_memory_note.invoke({
            "title": "待删除",
            "content": "即将被删除"
        })
        note_id = save_result.split("[ID: ")[1].split("]")[0]

        delete_result = delete_memory_note.invoke({"note_id": note_id})
        self.assertIn("已删除", delete_result)

        list_result = list_memory_notes.invoke({})
        self.assertNotIn("待删除", list_result)

    def test_delete_nonexistent_note(self):
        from myclaw.core.tools.builtins import delete_memory_note
        result = delete_memory_note.invoke({"note_id": "nonexistent"})
        self.assertIn("未找到", result)

    def test_get_relevant_memory_notes(self):
        from myclaw.core.tools.builtins import save_memory_note, get_relevant_memory_notes
        save_memory_note.invoke({"title": "数据库配置", "content": "MySQL连接字符串是xxx", "tags": "数据库"})
        save_memory_note.invoke({"title": "午餐偏好", "content": "喜欢吃火锅", "tags": "饮食"})

        results = get_relevant_memory_notes(query="数据库")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["title"], "数据库配置")

    def test_get_relevant_memory_notes_empty(self):
        from myclaw.core.tools.builtins import get_relevant_memory_notes
        results = get_relevant_memory_notes(query="anything")
        self.assertEqual(results, [])


class TestPromptLoaderKnowledgeContext(unittest.TestCase):

    def test_knowledge_context_placeholder_replaced(self):
        from myclaw.core.prompt_loader import build_system_prompt
        prompt = build_system_prompt(
            persona_name="default",
            skill_index="skill文本",
            user_profile="画像文本",
            context_summary="摘要文本",
            knowledge_context="知识库召回内容"
        )
        self.assertIn("知识库召回内容", prompt)
        self.assertNotIn("{{KNOWLEDGE_CONTEXT}}", prompt)

    def test_knowledge_context_empty_string(self):
        from myclaw.core.prompt_loader import build_system_prompt
        prompt = build_system_prompt(
            persona_name="default",
            knowledge_context=""
        )
        self.assertNotIn("{{KNOWLEDGE_CONTEXT}}", prompt)


class TestConfigKnowledgeConstants(unittest.TestCase):

    def test_knowledge_constants_exist(self):
        from myclaw.core.config import KNOWLEDGE_DIR, KNOWLEDGE_INDEX_FILE
        self.assertIsInstance(KNOWLEDGE_DIR, str)
        self.assertIsInstance(KNOWLEDGE_INDEX_FILE, str)
        self.assertTrue(KNOWLEDGE_DIR.endswith("knowledge"))
        self.assertTrue(KNOWLEDGE_INDEX_FILE.endswith("index.json"))


if __name__ == '__main__':
    unittest.main()
