from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # 存储对话历史。
    messages: Annotated[list[BaseMessage], add_messages]

    # 摘要压缩
    summary: str

    # Skill 上下文（激活的 skill 内容）
    skill_context: str

    # 迭代计数（用于死锁预防）
    iteration_count: int

    # 重复工具名追踪
    repeated_tool_name: str

    # 连续重复次数
    repeated_count: int

    # 中断续接标记
    ask_resume: bool

def trim_context_messages(messages: list[BaseMessage], trigger_turns: int = 8, keep_turns: int = 4) -> tuple[list[BaseMessage], list[BaseMessage]]:
    # 按照完整‘用户回合’来裁剪上下文：即 一个会从从HumanMessage开始，直到下一个HumanMessage结束，会把AIMessage、tool_calls、ToolMessage一并保留
    # 每个回合以 humanMessage开始，包含后面的ai恢复和工具调用
    # messages 示例
    #     messages = [
    #     SystemMessage("你是 MyClaw"),       # 系统提示词
    #     HumanMessage("你好"),                  # 用户消息
    #     AIMessage("你好！"),                   # AI 回复
    #     HumanMessage("查天气"),                # 用户消息
    #     AIMessage(tool_call),                  # AI 调用工具
    #     ToolMessage("晴天 25°C"),              # 工具结果
    # ]

    first_system = next((m for m in messages if isinstance(m, SystemMessage)), None) # next() 函数用于从迭代器中获取下一个元素，如果没有元素可供获取，则返回默认值 None
    non_system_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

    if not non_system_msgs:
        return ([first_system] if first_system else []), []
    
    turns: list[list[BaseMessage]] = []
    current_turn: list[BaseMessage] = []

    # 遍历非系统信息，按回合进行分组
    for msg in non_system_msgs:
        if isinstance(msg, HumanMessage):
            if current_turn:
                turns.append(current_turn)
            current_turn = [msg]
        else:
            if current_turn:
                current_turn.append(msg)
    
    # 保存最后一个回合
    if current_turn:
        turns.append(current_turn)

    total_turns = len(turns)

    if total_turns < trigger_turns:
        final_messages = ([first_system] if first_system else []) + non_system_msgs
        return final_messages, []
    
    recent_turns = turns[-keep_turns:]
    discarded_turns = turns[:-keep_turns]

    final_messages: list[BaseMessage] = []
    if first_system:
        final_messages.append(first_system)
    for turn in recent_turns:
        final_messages.extend(turn)

    discarded_messages: list[BaseMessage] = []
    for turn in discarded_turns:
        discarded_messages.extend(turn)

    return final_messages, discarded_messages

    
