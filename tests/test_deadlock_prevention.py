# tests/test_deadlock_prevention.py
import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from myclaw.core.context import AgentState
from langchain_core.messages import HumanMessage


class TestDeadlockPreventionState(unittest.TestCase):

    def test_agent_state_has_iteration_count(self):
        """AgentState 应包含 iteration_count 字段"""
        state = AgentState(
            messages=[],
            summary="",
            iteration_count=0,
            repeated_tool_name="",
            repeated_count=0,
            ask_resume=False
        )
        self.assertEqual(state["iteration_count"], 0)
        self.assertEqual(state["repeated_tool_name"], "")
        self.assertEqual(state["repeated_count"], 0)
        self.assertEqual(state["ask_resume"], False)

    def test_agent_state_iteration_count_increments(self):
        """iteration_count 可以正常自增"""
        state = AgentState(
            messages=[HumanMessage(content="test")],
            summary="",
            iteration_count=5,
            repeated_tool_name="",
            repeated_count=0,
            ask_resume=False
        )
        self.assertEqual(state["iteration_count"], 5)


if __name__ == '__main__':
    unittest.main()