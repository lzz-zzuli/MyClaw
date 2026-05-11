from typing import List, Optional
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage
from .context import AgentState, trim_context_messages
from .provider import get_provider
from .tools.builtins import BUILTIN_TOOLS, get_relevant_memory_notes
from .logger import audit_logger
from .config import MEMORY_DIR
from .skill_loader import get_skill_index_text
from .prompt_loader import build_system_prompt
from langchain_core.runnables import RunnableConfig
import os
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI

def create_agent_app(
    provider_name: str = "openai",
    model_name: str = "gpt-4o-mini",
    tools: Optional[List[BaseTool]] = None,
    checkpointer = None,
    persona_name: str = "default"
):
    # 不再包装 dynamic_skills，所有 skill 通过 load_skill 工具按需加载
    if tools is None:
        actual_tools = BUILTIN_TOOLS
    else:
        actual_tools = tools


    tool_node = ToolNode(actual_tools)

    llm = get_provider(provider_name=provider_name, model_name=model_name)
    llm_with_tools = llm.bind_tools(actual_tools)

    def agent_node(state: AgentState, config: RunnableConfig) -> dict:
        """
        核心大脑：读取状态托盘里的历史消息，决定是直接回答，还是调用工具。
        """
        thread_id = config.get("configurable", {}).get("thread_id", "system_default")

        raw_messages = state["messages"]

        # 获取 skill 上下文（如果有）
        skill_context = state.get("skill_context", "")
        # 记录工具结果
        if raw_messages:
            recent_tool_msgs = []
            for msg in reversed(raw_messages):
                if msg.type == "tool":
                    recent_tool_msgs.append(msg)
                else:
                    break
            # 写入日志
            for msg in reversed(recent_tool_msgs):
                audit_logger.log_event(
                    thread_id=thread_id,
                    event="tool_result",
                    tool = msg.name,
                    result_summary = msg.content[:200]
                )
        # 上下文裁剪
        # 对话超过 40 轮 -> 调用 LLM 摘要旧对话 -> 生成 summary -> 删除旧消息 -> 保留最近 10 轮
        current_summary = state.get("summary", "")
        final_msgs, discarded_msgs = trim_context_messages(raw_messages, trigger_turns=40, keep_turns=10)
        state_updates = {}

        if discarded_msgs:
            import sys
            print_formatted_text(ANSI("\033[K \033[38;5;141m ● 正在更新上下文记忆... \033[0m"))
            discarded_text = "\n".join([f"{m.type}: {m.content}" for m in discarded_msgs if m.content])

            # 先归档被裁剪的消息（在删除前保存）
            for m in discarded_msgs:
                if m.content and isinstance(m.content, str):
                    metadata = {}
                    if hasattr(m, 'tool_calls') and m.tool_calls:
                        metadata['tool_calls'] = m.tool_calls
                    if m.type == 'tool':
                        metadata['tool_name'] = m.name

                    audit_logger.log_archived_message(
                        thread_id=thread_id,
                        message_type=m.type,
                        message_id=m.id,
                        content=m.content,
                        metadata=metadata
                    )

            summary_prompt = (
                    f"你是一个负责维护 AI 工作台上下文的后台模块。\n\n"
                    f"【现有的交接文档】\n{current_summary if current_summary else '暂无记录'}\n\n"
                    f"【刚刚过去的旧对话】\n{discarded_text}\n\n"
                    f"任务：请仔细阅读旧对话，提取出当前的对话语境和任务进度。\n"
                    f"动作：将新进展与【现有的交接文档】进行无缝融合，输出一份最新的上下文摘要。\n"
                    f"严格警告：只记录'我们在聊什么'、'解决了什么问题'、'得出了什么结论'等。绝对不要记录用户的静态偏好(如姓名、职业、爱好等)，这部分由其他模块负责！\n"
                    f"要求：客观、精简，不要输出任何解释性废话，直接返回最新的记忆文本，总字数不要超过150字"
                )

            # 这里可以用便宜模型
            new_summary_response = llm.invoke([HumanMessage(content=summary_prompt)], config={"callbacks":[]})
            active_summary = new_summary_response.content

            # 更新摘要
            state_updates["summary"] = active_summary

            # 从状态机中删除信息
            delete_cmds = [RemoveMessage(id=m.id) for m in discarded_msgs if m.id]
            state_updates["messages"] = delete_cmds
        else:
            active_summary = current_summary

        # 读取用户画像
        profile_path = os.path.join(MEMORY_DIR, "user_profile.md")
        profile_content = "暂无记录"
        if os.path.exists(profile_path):
            with open(profile_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read().strip()
                if content:
                    profile_content = content

        latest_user_text = ""
        for msg in reversed(final_msgs):
            if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
                latest_user_text = msg.content.strip()
                break

        # 获取 skill 索引
        skill_index_text = get_skill_index_text()

        # 构建用户画像文本
        profile_text = f"\n=============================\n【用户长期画像】\n{profile_content}\n=============================\n"

        # 构建知识库上下文
        memory_notes = get_relevant_memory_notes(
            query=latest_user_text,
            summary=active_summary,
            limit=5
        )
        knowledge_text = ""
        if memory_notes:
            memory_lines = []
            for note in memory_notes:
                tags_text = ", ".join(note.get("tags", [])) if note.get("tags") else "无标签"
                excerpt = " ".join(note.get("content", "").split())
                if len(excerpt) > 140:
                    excerpt = excerpt[:140] + "..."
                memory_lines.append(
                    f"- [{note.get('kind', 'fact')}] {note.get('title', '未命名记忆')} (ID: {note.get('id')}, tags: {tags_text})\n  {excerpt}"
                )
            knowledge_text = (
                "\n=============================\n"
                "【知识库记忆】\n"
                "以下是与当前问题相关的长期记忆，可用于跨会话保持事实一致性。\n"
                + "\n".join(memory_lines)
                + "\n=============================\n"
            )
        # 构建 Skill 索引文本
        skill_text = (
            "\n=============================\n"
            "【可用 Skill 索引】\n"
            "以下 skill 可按需加载完整内容。Skill 是否适用只由 name 和 description 判断；当用户任务匹配某个 skill 的 description 时，调用 load_skill 工具。\n"
            "加载 SKILL.md 后，如正文要求读取附加文档或资源（如 editing.md、references/*.md、scripts/*.py），按需调用 list_skill_resources、load_skill_resource 或 execute_skill_script。\n"
            f"{skill_index_text}\n"
            "=============================\n"
        )

        # 构建上下文摘要文本
        summary_text = ""
        if active_summary:
            summary_text = f"\n\n[近期对话上下文]\n{active_summary}\n\n(注：这是系统自动生成的近期沟通摘要)"

        # 使用模板加载器构建系统提示词
        sys_prompt = build_system_prompt(
            persona_name=persona_name,
            skill_index=skill_text,
            user_profile=profile_text,
            context_summary=summary_text,
            knowledge_context=knowledge_text
        )

        # 如果有 skill 上下文，附加到 System Prompt
        if skill_context:
            sys_prompt += f"\n\n=============================\n【Skill 上下文】\n{skill_context}\n=============================\n"

        msgs_for_llm = [SystemMessage(content=sys_prompt)] + \
        [m for m in final_msgs if not isinstance(m, SystemMessage)]

        for m in msgs_for_llm:
            if isinstance(m.content, str):
                m.content = m.content.encode('utf-8', 'ignore').decode('utf-8')

        # 记录即将发送给模型的消息
        audit_logger.log_event(
            thread_id=thread_id,
            event="llm_input",
            message_count=len(msgs_for_llm)
        )

        response = llm_with_tools.invoke(msgs_for_llm)

        # 解析大模型的回答并记录到日志
        if response.tool_calls:
            for tool_call in response.tool_calls:
                audit_logger.log_event(
                    thread_id=thread_id,
                    event="tool_call",
                    tool=tool_call["name"],
                    args=tool_call["args"]
                )
        elif response.content:
            audit_logger.log_event(
                thread_id=thread_id,
                event="ai_message",
                content=response.content
            )

        if "messages" not in state_updates:
            state_updates["messages"] = []
        state_updates["messages"].append(response)

        return state_updates

    workflow = StateGraph(AgentState)


    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)


    workflow.add_edge(START, "agent")

    # 每次 agent 思考完，检查它有没有发出工具调用指令。
    # tools_condition 会自动判断：有指令 -> 走向 "tools" 节点；没指令 -> 走向 END。
    workflow.add_conditional_edges("agent", tools_condition)

    workflow.add_edge("tools", "agent")

    app = workflow.compile(checkpointer=checkpointer)

    return app