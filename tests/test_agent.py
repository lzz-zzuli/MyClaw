import unittest
import os
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from myclaw.core.context import AgentState
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


class TestAgent(unittest.TestCase):

    def test_agent_source_mentions_description_first_skill_triggering(self):
        """测试 Agent 的 Skill 提示包含 description-first 触发机制和资源工具"""
        import inspect
        import myclaw.core.agent as agent_module

        source = inspect.getsource(agent_module.create_agent_app)
        self.assertIn("Skill 是否适用只由 name 和 description 判断", source)
        self.assertIn("list_skill_resources", source)
        self.assertIn("load_skill_resource", source)
        self.assertNotIn("detect_skill_candidates", source)

    def test_prompt_templates_mention_description_first_skill_triggering(self):
        """测试人设模板不再只依赖触发词"""
        prompt_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "myclaw", "core", "prompts"))
        for filename in ["default.md", "professional.md", "friendly.md"]:
            with open(os.path.join(prompt_dir, filename), "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("description", content)
            self.assertIn("load_skill", content)

    def test_agent_state_initialization(self):
        """测试 AgentState 的初始化"""
        from myclaw.core.context import AgentState

        initial_state = AgentState(
            messages=[],
            summary=""
        )

        self.assertEqual(initial_state["messages"], [])
        self.assertEqual(initial_state["summary"], "")

    @patch('myclaw.core.provider.get_provider')
    @patch('myclaw.core.skill_loader.get_skill_index_text')
    def test_create_agent_app_basic(self, mock_get_skill_index, mock_get_provider):
        """测试创建基础代理应用（带 Mock）"""
        from myclaw.core.agent import create_agent_app

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock skill 索引文本
        mock_get_skill_index.return_value = "当前没有加载任何外部 skill。"

        try:
            app = create_agent_app(provider_name="openai", model_name="gpt-4o-mini")
            self.assertIsNotNone(app)
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

    @patch('myclaw.core.provider.get_provider')
    @patch('myclaw.core.skill_loader.get_skill_index_text')
    def test_create_agent_app_with_custom_tools(self, mock_get_skill_index, mock_get_provider):
        """测试创建带有自定义工具的代理应用（带 Mock）"""
        from myclaw.core.agent import create_agent_app
        from langchain_core.tools import tool

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock skill 索引文本
        mock_get_skill_index.return_value = "当前没有加载任何外部 skill。"

        # 创建一个真正的 mock 工具（使用@tool 装饰器）
        @tool
        def mock_tool(test_param: str) -> str:
            """A mock tool for testing"""
            return f"mock result: {test_param}"

        try:
            app = create_agent_app(
                provider_name="openai",
                model_name="gpt-4o-mini",
                tools=[mock_tool]
            )
            self.assertIsNotNone(app)
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise

    @patch('myclaw.core.provider.get_provider')
    @patch('myclaw.core.skill_loader.get_skill_index_text')
    def test_create_agent_app_with_checkpointer(self, mock_get_skill_index, mock_get_provider):
        """测试创建带有检查点的代理应用（带 Mock）"""
        from myclaw.core.agent import create_agent_app
        from langgraph.checkpoint.memory import MemorySaver

        # Mock provider 返回值
        mock_provider = Mock()
        mock_provider.bind_tools.return_value = Mock()
        mock_get_provider.return_value = mock_provider

        # Mock skill 索引文本
        mock_get_skill_index.return_value = "当前没有加载任何外部 skill。"

        memory_saver = MemorySaver()
        try:
            app = create_agent_app(
                provider_name="openai",
                model_name="gpt-4o-mini",
                checkpointer=memory_saver
            )
            self.assertIsNotNone(app)
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise


if __name__ == '__main__':
    unittest.main()