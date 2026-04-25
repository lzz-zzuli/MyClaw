import os
import sys
import time
import asyncio
import random
import questionary
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.styles import Style
from prompt_toolkit.application import get_app

from myclaw.core.agent import create_agent_app
from myclaw.core.config import DB_PATH
from myclaw.core.session import session_manager
from myclaw.core.bus import task_queue
from myclaw.core.heartbeat import pacemaker_loop
from myclaw.core.provider import get_provider
from myclaw.core.tools.base import set_current_thread_id
from langchain_core.messages import HumanMessage

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def type_line(text: str, delay: float = 0.008):
    for ch in text:
        print(ch, end='', flush=True)
        time.sleep(delay)
    print()

def print_banner():
    clear_screen()

    CYAN = '\033[38;5;51m'
    PURPLE = '\033[38;5;141m'
    SILVER = '\033[38;5;250m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    WHITE = '\033[37m'

    logo = f"""{CYAN}{BOLD}
███╗   ███╗██╗  ██╗ ██████╗██╗      █████╗ ██╗    ██╗
████╗ ████║╚██╗ ██╔╝██╔════╝██║     ██╔══██╗██║    ██║
██╔████╔██║ ╚████╔╝ ██║     ██║     ███████║██║ █╗ ██║
██║╚██╔╝██║  ╚██╔╝  ██║     ██║     ██╔══██║██║███╗██║
██║ ╚═╝ ██║   ██║   ╚██████╗███████╗██║  ██║╚███╔███╔╝
╚═╝     ╚═╝   ╚═╝    ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
{RESET}"""

    sub_title = f"{WHITE}{BOLD} 👾 Welcome to the {PURPLE}{BOLD}MyClaw{RESET}{WHITE}{BOLD} !  {RESET}"

    quotes = [
        "It works on my machine.",
        "It compiles! Ship it.",
        "Git commit, push, pray.",
        "There's no place like 127.0.0.1.",
        "sudo make me a sandwich.",
        "Works fine in dev.",
        "May the source be with you.",
        "Ctrl+C, Ctrl+V, Deploy.",
        "Hello, World."
    ]
    quote = random.choice(quotes)
    meta = f" {SILVER}✦{RESET} {CYAN}{quote}{RESET}"

    tip = (
        f"{PURPLE} ✦ {RESET}"
        f"{SILVER}{PURPLE}{BOLD}MyClaw{RESET} 已完成启动。输入命令开始，输入 {PURPLE}/exit{RESET}{SILVER} 退出。{RESET}\n"
    )

    print(logo)
    print(sub_title)
    print() 
    time.sleep(0.12)
    print(meta)
    print() 
    type_line(tip, delay=0.004)


def cprint(text="", end="\n"):
    print_formatted_text(ANSI(str(text)), end=end)


async def async_main(session_id: str = None, session_name: str = None):
    print_banner()

    # 设置当前 thread_id 供工具模块使用
    set_current_thread_id(session_id)

    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    load_dotenv(env_path)

    current_provider = os.getenv("DEFAULT_PROVIDER", "aliyun")
    current_model = os.getenv("DEFAULT_MODEL", "glm-5")

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as memory:
        app = create_agent_app(provider_name=current_provider, model_name=current_model, checkpointer=memory)
        config = {"configurable": {"thread_id": session_id}}

        class SpinnerState:
            action_words = [
                "Thinking...",              
                "Working...",               
                "Beep boop...",             
                "Eating bugs...",           
                "Charging battery...",      
                "Brewing coffee...",        
                "Blinking lights...",       
                "Polishing pixels...",      
                "Scanning matrix...",       
                "Warming up circuits...",   
                "Syncing data...",          
                "Pinging server..."         
            ]
            current_words = [] 
            is_spinning = False
            start_time = 0
            frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
            is_tool_calling = False 
            tool_msg = ""           

        spinner = SpinnerState()


        def get_bottom_toolbar():
            if not spinner.is_spinning:
                return ANSI("") 
            
            elapsed = time.time() - spinner.start_time
            if spinner.is_tool_calling:
                display_msg = spinner.tool_msg
            else:
                idx_word = int(elapsed) % len(spinner.current_words)
                display_msg = f"👾 {spinner.current_words[idx_word]}"

            idx_frame = int(elapsed * 12) % len(spinner.frames)
            frame = spinner.frames[idx_frame]
            

            return ANSI(f"  \033[38;5;51m{frame}\033[0m \033[38;5;250m{display_msg}\033[0m \033[38;5;141m[{elapsed:.1f}s]\033[0m")

        prompt_message = ANSI("  \033[38;5;51m❯\033[0m ")
        placeholder_text = ANSI("\033[3m\033[38;5;242minput...\033[0m")

        async def agent_worker():
            while True:
                user_input = await task_queue.get()
                if user_input.lower() in ["/exit", "/quit"]:
                    task_queue.task_done()
                    break
                
                spinner.current_words = spinner.action_words.copy()
                random.shuffle(spinner.current_words)
                
                spinner.start_time = time.time()
                spinner.is_spinning = True
                spinner.is_tool_calling = False
                
                inputs = {"messages": [HumanMessage(content=user_input)]}
                try:
                    async for event in app.astream(inputs, config=config, stream_mode="updates"):
                        for node_name, node_data in event.items():
                            if node_name == "agent":
                                last_msg = node_data["messages"][-1]
                                
                                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                                    for tc in last_msg.tool_calls:
                                        spinner.is_tool_calling = True
                                        spinner.tool_msg = f"唤醒内置工具 : {tc['name']}..."
                                        cprint(f"  ●\033[38;5;51m Tool Call: \033[0m{tc['name']}")
                                        cprint('')
                                        
                                elif last_msg.content:
                                    spinner.is_spinning = False
                                    
                                    lines = last_msg.content.strip().split('\n')
                                    if lines:
                                        formatted_out = f"  \033[38;5;141m❯\033[0m \033[38;5;250m{lines[0]}"
                                        for line in lines[1:]:
                                            formatted_out += f"\n    {line}"
                                        formatted_out += "\033[0m" 
                                        cprint(formatted_out)
                                    
                            elif node_name != "agent": 
                                spinner.is_tool_calling = False 
                                
                except Exception as e:
                    spinner.is_spinning = False
                    cprint(f"  \033[31m[ ⚠️ 引擎异常 : {e} ]\033[0m")

                spinner.is_spinning = False
                cprint() # 空出舒适的行距
                task_queue.task_done()

        async def user_input_loop():
            custom_style = Style.from_dict({
                'bottom-toolbar': 'bg:default fg:default noreverse',
            })
            
            session = PromptSession(
                bottom_toolbar=get_bottom_toolbar,
                style=custom_style,
                erase_when_done=True,
                reserve_space_for_menu=0  
            )
            
            async def redraw_timer():
                while True:
                    if spinner.is_spinning:
                        try:
                            get_app().invalidate()
                        except Exception:
                            pass
                    await asyncio.sleep(0.08)
                    
            redraw_task = asyncio.create_task(redraw_timer())
            
            while True:
                try:
                    user_input = await session.prompt_async(prompt_message, placeholder=placeholder_text)

                    user_input = user_input.strip()
                    if not user_input:
                        continue

                    # 处理 /rename 命令
                    if user_input.startswith("/rename "):
                        new_name = user_input[8:].strip()
                        if new_name:
                            session_manager.rename_session(session_id, new_name)
                            cprint(f"  \033[38;5;51m✦ 会话已重命名为: {new_name}\033[0m\n")
                            continue
                        else:
                            cprint(f"  \033[31m[ 请输入新名称，如 /rename 工作助手 ]\033[0m\n")
                            continue

                    padded_bubble = f"  ❯ {user_input}    "
                    cprint(f"\033[48;2;38;38;38m\033[38;5;255m{padded_bubble}\033[0m\n")

                    # 增加消息计数
                    session_manager.increment_message_count(session_id)

                    await task_queue.put(user_input)
                    if user_input.lower() in ["/exit", "/quit"]:
                        cprint("  \033[38;5;141m✦ 记忆已固化，MyClaw 进入休眠。\033[0m")
                        break
                        
                except (KeyboardInterrupt, EOFError):
                    cprint("\n  \033[38;5;141m✦ 强制中断，CyClaw 进入休眠。\033[0m")
                    await task_queue.put("/exit")
                    break

            redraw_task.cancel() 

        with patch_stdout():
            worker = asyncio.create_task(agent_worker())
            heartbeat_worker = asyncio.create_task(pacemaker_loop(check_interval=10, thread_id=session_id))
            await user_input_loop()
            await task_queue.join()
            worker.cancel()
            heartbeat_worker.cancel()

            # 会话退出时生成描述
            await generate_session_description(app, config, session_id)

def main(resume: str = None, session_name: str = None):
    """主入口函数

    Args:
        resume: 会话名称或 session_id，用于恢复历史会话。空字符串表示显示历史列表
        session_name: 新会话命名或重命名现有会话
    """
    # 决定 session_id
    if resume == "":
        # -l 显示历史列表交互选择
        sessions = session_manager.list_sessions()
        if not sessions:
            # 没有历史会话，询问是否创建新会话
            confirm = questionary.confirm(
                "暂无历史会话，是否创建新会话?",
                default=True,
                style=questionary.Style([
                    ('qmark', 'fg:#8d52ff bold'),
                    ('question', 'fg:#00ffff bold'),
                ])
            ).ask()
            if not confirm:
                print("  \033[38;5;141m✦ 已取消\033[0m")
                return
            session = session_manager.create_session(name=session_name)
            session_id = session["session_id"]
            print(f"  \033[38;5;51m✦ 新会话已创建: {session.get('name', session_id)}\033[0m")
        else:
            choices = [
                questionary.Choice(f"{s['name']} ({s['message_count']} 条消息)", value=s['session_id'])
                for s in sessions
            ]
            choices.append(questionary.Choice("➕ 创建新会话", value="new"))
            choices.append(questionary.Choice("❌ 退出", value="exit"))

            selected = questionary.select(
                "选择要恢复的会话:",
                choices=choices,
                style=questionary.Style([
                    ('qmark', 'fg:#8d52ff bold'),
                    ('question', 'fg:#00ffff bold'),
                    ('answer', 'fg:#8d52ff bold'),
                    ('pointer', 'fg:#00ffff bold'),
                ])
            ).ask()

            if selected == "exit":
                print("  \033[38;5;141m✦ 已取消\033[0m")
                return
            elif selected == "new":
                session = session_manager.create_session(name=session_name)
                session_id = session["session_id"]
                print(f"  \033[38;5;51m✦ 新会话已创建: {session.get('name', session_id)}\033[0m")
            else:
                session = session_manager.get_session(selected)
                session_id = selected
                if session_name:
                    session_manager.rename_session(session_id, session_name)
                print(f"  \033[38;5;51m✦ 已恢复会话: {session.get('name', session_id)}\033[0m")
    elif resume:
        # -r <name> → 恢复指定会话
        session = session_manager.find_session(resume)
        if session:
            session_id = session["session_id"]
            if session_name:
                session_manager.rename_session(session_id, session_name)
                session["name"] = session_name
            print(f"  \033[38;5;51m✦ 已恢复会话: {session.get('name', session_id)}\033[0m")
        else:
            print(f"  \033[31m[ 会话 '{resume}' 不存在 ]\033[0m")
            return
    else:
        # 无参数 → 创建新会话
        session = session_manager.create_session(name=session_name)
        session_id = session["session_id"]
        if session_name:
            print(f"  \033[38;5;51m✦ 新会话已创建: {session_name}\033[0m")
        else:
            print(f"  \033[38;5;51m✦ 新会话已创建: {session_id}\033[0m")

    asyncio.run(async_main(session_id=session_id, session_name=session.get("name") if session else None))


async def generate_session_description(app, config, session_id: str):
    """会话退出时生成描述"""
    try:
        # 获取当前会话状态
        state = await app.aget_state(config)
        messages = state.values.get("messages", [])

        if len(messages) < 3:
            return

        # 取最近的消息生成摘要
        recent_msgs = messages[-10:] if len(messages) > 10 else messages
        msg_text = "\n".join([
            f"{m.type}: {m.content[:200] if isinstance(m.content, str) else str(m.content)[:200]}"
            for m in recent_msgs[-6:]
            if m.content
        ])

        prompt = (
            f"请根据以下对话内容，生成一个简短的会话描述（不超过30字），"
            f"描述本次对话的主要话题或目的。\n\n"
            f"对话内容:\n{msg_text}\n\n"
            f"直接输出描述，不要加任何解释。"
        )

        provider = os.getenv("DEFAULT_PROVIDER", "aliyun")
        model = os.getenv("DEFAULT_MODEL", "glm-5")
        llm = get_provider(provider_name=provider, model_name=model)

        response = llm.invoke([HumanMessage(content=prompt)], config={"callbacks": []})
        description = response.content.strip()[:50]

        session_manager.update_description(session_id, description)
    except Exception as e:
        pass


if __name__ == "__main__":
    main()