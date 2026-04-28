from datetime import datetime
from .base import my_tool, MyClawBaseTool, get_current_thread_id
import os
import json
import uuid
import threading
from ..config import MEMORY_DIR, TASKS_FILE
from ..skill_loader import load_skill_content, load_skill_full, get_skill_dir, get_skill_by_name
from .sandbox_tools import (
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell
)


tasks_lock = threading.Lock()
PROFILE_PATH = os.path.join(MEMORY_DIR, "user_profile.md")


@my_tool
def get_system_model_info() -> str:
    """
    获取当前 MyClaw 正在运行的底层大模型（LLM）型号和提供商信息。
    当用户询问"你是基于什么模型"、"你的底层大模型是什么"、"你是GPT还是GLM"、"现在用的什么模型"等身份问题时，调用此工具。
    """
    provider = os.getenv("DEFAULT_PROVIDER", "unknown")
    model = os.getenv("DEFAULT_MODEL", "unknown")
    
    if provider == "unknown" or model == "unknown":
        return "无法获取当前的系统模型配置，可能是环境变量未正确加载。"
        
    return f"当前使用的模型提供商(Provider)是: {provider}，具体型号(Model)是: {model}。"


@my_tool
def save_user_profile(new_content: str) -> str:
    """
    更新用户的全局显性记忆档案。
    当你发现用户的偏好发生改变，或者有新的重要事实需要记录时：
    1.请先调用 read_user_profile 获取当前的完整档案。
    2.在你的上下文中，将新信息融入档案，并删去冲突或过时的旧信息。
    3.将修改后的一整篇完整 Markdown 文本作为 new_content 参数传入此工具。
    注意：此操作将完全覆盖旧文件！请确保传入的是完整的最新档案。
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    return "记忆档案已成功覆写更新。新的人设画像已生效。"


@my_tool
def get_current_time() -> str:
    """
    获取当前的系统时间和日期。
    当用户询问"现在几点"、"今天星期几"、"今天几号"等与当前时间相关的问题时，调用此工具。
    """
    now = datetime.now()
    return f"当前本地系统时间是: {now.strftime('%Y-%m-%d %H:%M:%S')}"


import ast
import operator

# 安全数学运算符映射表（AST 白名单）
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,      # 负号
    ast.UAdd: operator.pos,      # 正号
}


def _safe_eval_math(expression: str) -> float:
    """
    基于 AST 白名单的安全数学表达式计算器。
    只允许：数字、加减乘除幂模、括号、正负号。
    拒绝：函数调用、属性访问、导入、字符串、列表等任何危险操作。
    """
    tree = ast.parse(expression, mode='eval')

    def _eval_node(node):
        if isinstance(node, ast.Constant):
            # Python 3.8+ 的常量节点
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value)}")

        elif isinstance(node, ast.Num):
            # Python 3.7 兼容的数字节点
            return node.n

        elif isinstance(node, ast.BinOp):
            # 二元运算：如 1 + 2
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](left, right)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")

        elif isinstance(node, ast.UnaryOp):
            # 一元运算：如 -5, +3
            operand = _eval_node(node.operand)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](operand)
            raise ValueError(f"不支持的一元运算符: {op_type.__name__}")

        elif isinstance(node, ast.Expression):
            # 顶层表达式节点
            return _eval_node(node.body)

        else:
            # 拒绝所有其他节点类型（函数调用、属性访问等）
            raise ValueError(f"禁止的表达式类型: {type(node).__name__}")

    return _eval_node(tree)


@my_tool
def calculator(expression: str) -> str:
    """
    一个安全的数学计算器。
    用于计算基础的数学表达式，例如: '3 * 5' 或 '100 / 4'。
    支持：加减乘除、幂运算、模运算、括号、正负号。
    不支持：函数调用、变量、字符串等（这是安全限制）。
    """
    try:
        result = _safe_eval_math(expression)
        return f"表达式 '{expression}' 的计算结果是: {result}"
    except ValueError as e:
        return f"计算出错：{str(e)}。请检查表达式是否只包含数字和数学运算符。"
    except SyntaxError:
        return f"计算出错：表达式语法无效。"
    except Exception as e:
        return f"计算出错：{str(e)}"


@my_tool
def schedule_task(target_time: str, description: str, repeat: str = None, repeat_count: int = None) -> str:
    """
    为一个未来的任务设定闹钟或提醒。
    参数 target_time 必须是严格的格式："YYYY-MM-DD HH:MM:SS"（请先调用 get_current_time 获取当前时间，并在其基础上推算）。
    参数 description 是需要执行的动作或要说的话。
    
    【高级循环功能】：
    - repeat (可选): 设置重复频率。可选值为 "hourly", "daily", "weekly"。如果不重复请留空。
    - repeat_count (可选): 结合 repeat 使用，表示一共需要触发几次。
    
    【案例教学】：
    1. 用户说："以后每天8点提醒我喝牛奶" -> repeat="daily", repeat_count=None (无限循环)
    2. 用户说："接下来的3天，每天提醒我吃药" -> repeat="daily", repeat_count=3 (有限循环)
    3. 用户说："明早8点叫我起床" -> repeat=None, repeat_count=None (单次任务)

    【时间歧义严格确认协议 (AM/PM Ambiguity CRITICAL)】：
    当用户说出的时间存在 12 小时制的模糊性时（例如：只说了"7点"，没明确说早上还是晚上）：
    1. 你必须向用户提问确认是上午还是下午。
    2. 【死命令】：在用户明确回复"上午"或"下午"（或改为24小时制）之前，本工具处于【绝对锁定状态】！
    3. 就算用户发省略号（如"。。"）、发脾气、或者说无关内容，你也【绝对禁止】为了讨好用户而自行猜测时间！
    4. 严禁出现"抱歉多问了"、"默认早上"这种妥协行为。
    5. 如果用户不明确回答，你必须坚定地回复："抱歉，没有明确上下午，我无权为您设置闹钟。请明确告知时间段。"并立即中止工具调用。
    """
    try:
        datetime.strptime(target_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "设定失败：时间格式错误，必须严格遵循 'YYYY-MM-DD HH:MM:SS' 格式。"

    with tasks_lock:
        tasks = []
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        tasks = json.loads(content)
            except Exception as e:
                return f"设定失败：读取任务队列异常 {str(e)}"

        new_task = {
            "id": str(uuid.uuid4())[:8],
            "thread_id": get_current_thread_id(),
            "target_time": target_time,
            "description": description,
            "repeat": repeat,
            "repeat_count": repeat_count
        }
        tasks.append(new_task)

        try:
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"设定失败：写入任务队列异常 {str(e)}"

    msg = f" 任务已成功加入队列。首发时间：{target_time} | 任务：{description}"
    if repeat:
        msg += f" | 循环模式：{repeat} (共 {repeat_count if repeat_count else '无限'} 次)"
    return msg


@my_tool
def list_scheduled_tasks() -> str:
    """
    查看当前所有待处理的定时任务列表。
    当用户询问"我都有哪些任务"、"查一下闹钟"、"刚才定了什么"时调用此工具。
    """
    current_thread = get_current_thread_id()

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "当前没有任何定时任务。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return "任务列表为空。"
                tasks = json.loads(content)

            if not tasks:
                return "当前没有任何定时任务。"

            # 只显示当前会话的任务
            if current_thread:
                tasks = [t for t in tasks if t.get("thread_id") == current_thread]

            if not tasks:
                return "当前会话没有定时任务。"

            tasks.sort(key=lambda x: x['target_time'])

            res = " 当前待执行任务列表：\n"
            for t in tasks:
                res += f"- [ID: {t['id']}] 时间: {t['target_time']} | 任务: {t['description']}\n"
            return res
        except Exception as e:
            return f"查询失败：{str(e)}"
    

@my_tool
def delete_scheduled_task(task_id: str) -> str:
    """
    根据任务 ID 取消或删除一个定时任务。
    
    【强制性风险控制协议 (CRITICAL)】：
    删除操作具有不可逆性。
    1. 只要匹配到符合描述的任务数量 > 1。
    2. 无论用户语气多么确定，只要他没提供具体的任务 ID。
    
    【你必须执行的动作】：
    【禁止】在单次回复中针对同一个模糊描述发起多个删除工具调用。
    你必须先列出所有匹配的任务（1. 2. 3.），并询问用户：
    "发现了多个符合条件的提醒（列出列表），为了安全起见，请问是要全部删除，还是只删除其中几个？"
    必须要用户明确给出编号或者说确定全部删除，才能调用此工具！！
    严禁自作主张执行批量删除。
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "删除失败：任务列表文件不存在。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            new_tasks = [t for t in tasks if t['id'] != task_id]
            
            if len(new_tasks) == len(tasks):
                return f"删除失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(new_tasks, f, ensure_ascii=False, indent=2)
            
            return f" 任务 [ID: {task_id}] 已成功取消。"
        except Exception as e:
            return f"操作异常：{str(e)}"
    

@my_tool
def modify_scheduled_task(task_id: str, new_time: str = None, new_description: str = None) -> str:
    """
    修改现有定时任务的时间或内容。
    
    【强制性风险控制协议 (CRITICAL)】：
    1. 只要用户通过"模糊描述"（如：那个5天的任务、洗澡的任务）来要求修改，而没有直接提供 ID。
    2. 无论用户的话语看起来是单数还是复数（如："把5天的任务全改了"）。
    3. 只要系统中匹配到的任务数量 > 1。
    
    【你必须执行的动作】：
    禁止直接调用本工具！你必须向用户展示匹配到的所有任务列表，并强制询问：
    "我发现有 [N] 个任务符合描述（列出列表），请问你是要【全部修改】，还是修改其中【某几个】？（请告诉我编号或确认全部）"
    
    必须在用户回复"全部"或者指定了具体编号后，你才能继续操作！修改任务并非小事,这是为了安全！！
    """

    with tasks_lock:
        if not os.path.exists(TASKS_FILE):
            return "修改失败：任务列表为空。"

        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                tasks = json.loads(content) if content else []
            
            found = False
            for t in tasks:
                if t['id'] == task_id:
                    if new_time:
                        datetime.strptime(new_time, "%Y-%m-%d %H:%M:%S")
                        t['target_time'] = new_time
                    if new_description:
                        t['description'] = new_description
                    found = True
                    break
            
            if not found:
                return f"修改失败：未找到 ID 为 {task_id} 的任务。"
            
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
                
            return f" 任务 [ID: {task_id}] 已成功更新。"
        except ValueError:
            return "修改失败：时间格式错误。"
        except Exception as e:
            return f"操作异常：{str(e)}"


@my_tool
def load_skill(skill_name: str, full: bool = True) -> str:
    """
    按需加载某个 skill 的内容。

    使用场景：
    1. 你已从 System Prompt 中的 skill 索引看到可用的 skill 列表
    2. 用户的问题与某个 skill 的触发词相关（如提到"毛泽东"、"毛选"等）
    3. 你判断需要深入了解该 skill 的方法论或工具

    参数:
        skill_name: skill 的 name 字段（来自索引列表）
        full: 是否加载完整内容（包含引用资源）。默认 True。

    返回:
        skill 的完整内容（SKILL.md + 引用的额外文档）
    """
    if full:
        return load_skill_full(skill_name)
    else:
        # 只加载 SKILL.md，不加载引用资源
        return load_skill_content(skill_name)


import subprocess


@my_tool
def execute_skill_script(skill_name: str, script_name: str, script_args: str = "") -> str:
    """
    执行 skill 目录下的脚本。

    使用场景：
    1. 工作流型 skill 定义了关联的脚本工具
    2. SKILL.md 中指定了如何使用脚本
    3. 你需要执行脚本来完成任务

    参数:
        skill_name: skill 的 name 字段
        script_name: 脚本文件名（如 weather_query.py）
        script_args: 传递给脚本的参数（如 "北京"）

    返回:
        脚本的执行结果
    """
    skill_dir = get_skill_dir(skill_name)
    if not skill_dir:
        return f"错误：未找到 skill '{skill_name}'"

    script_path = os.path.join(skill_dir, script_name)
    if not os.path.exists(script_path):
        return f"错误：skill '{skill_name}' 下不存在脚本 '{script_name}'"

    # skill 脚本在 office/skills 目录下，是受信任的沙盒内容
    # 直接执行，不通过 execute_office_shell（它有 python 黑名单）
    try:
        if script_name.endswith(".py"):
            # 使用 Python 解释器执行
            cmd = ["python", script_name]
            if script_args:
                # 将参数按空格分割
                cmd.extend(script_args.split())
        elif script_name.endswith(".sh"):
            cmd = ["./" + script_name]
            if script_args:
                cmd.extend(script_args.split())
        else:
            cmd = [script_name]
            if script_args:
                cmd.extend(script_args.split())

        result = subprocess.run(
            cmd,
            cwd=skill_dir,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )

        output = f"执行脚本: {script_name}\n"
        output += f"参数: {script_args}\n"
        output += f"退出码: {result.returncode}\n"

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            output += f"\n[输出]\n{stdout}"
        if stderr:
            output += f"\n[错误]\n{stderr}"

        if not stdout and not stderr and result.returncode == 0:
            output += "\n(执行成功，无输出)"

        return output

    except subprocess.TimeoutExpired:
        return f"错误：脚本执行超时（30s）"
    except Exception as e:
        return f"执行异常：{str(e)}"


BUILTIN_TOOLS = [
    get_current_time,
    calculator,
    save_user_profile,
    list_office_files,
    read_office_file,
    write_office_file,
    execute_office_shell,
    get_system_model_info,
    schedule_task,
    list_scheduled_tasks,
    delete_scheduled_task,
    modify_scheduled_task,
    load_skill,
    execute_skill_script
]