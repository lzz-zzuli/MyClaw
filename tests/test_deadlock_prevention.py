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


class TestLoopDetection(unittest.TestCase):

    def test_no_loop_under_warn_threshold(self):
        """低于警告阈值时返回正常"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=10, repeated_tool_name="", repeated_count=0)
        self.assertEqual(result, "normal")

    def test_warn_at_warn_threshold(self):
        """达到警告阈值时返回 warn"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=20, repeated_tool_name="", repeated_count=0)
        self.assertEqual(result, "warn")

    def test_break_at_break_threshold(self):
        """达到中断阈值时返回 break"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=35, repeated_tool_name="", repeated_count=0)
        self.assertEqual(result, "break")

    def test_break_on_repeated_tool(self):
        """连续5次调用同一工具时返回 break"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=5, repeated_tool_name="load_skill", repeated_count=5)
        self.assertEqual(result, "break")

    def test_suspicious_on_repeated_tool_below_break(self):
        """连续3次调用同一工具（未达中断）时返回 warn"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=5, repeated_tool_name="load_skill", repeated_count=3)
        self.assertEqual(result, "warn")

    def test_normal_when_no_repetition(self):
        """无工具重复且迭代少时返回 normal"""
        from myclaw.core.context import detect_tool_loop, LOOP_WARN_THRESHOLD, LOOP_BREAK_THRESHOLD, REPEATED_TOOL_BREAK_THRESHOLD
        result = detect_tool_loop(iteration_count=5, repeated_tool_name="read_file", repeated_count=1)
        self.assertEqual(result, "normal")


if __name__ == '__main__':
    unittest.main()