import os
import subprocess
from .base import my_tool
from ..config import OFFICE_DIR
import re
import platform
from datetime import datetime

SYS_OS = platform.system()

# 安全的环境变量白名单（只保留必要的环境变量，不包含敏感信息）
_SAFE_ENV_WHITELIST = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": OFFICE_DIR,  # 强制 HOME 指向沙盒
    "USER": "myclaw_sandbox",
    "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    "TERM": os.environ.get("TERM", "xterm"),
    "SHELL": "/bin/sh",  # 限制为最基础的 shell
}

# 允许在沙盒内执行脚本的解释器（有条件放行）
_SAFE_INTERPRETERS = {"python", "python3", "node"}

# 危险命令黑名单（禁止执行的命令）
_DANGEROUS_COMMANDS = [
    "curl", "wget", "nc", "netcat",     # 网络外联
    "ssh", "scp", "sftp", "rsync",      # 远程连接
    "ruby", "perl",                     # 非 skill 所需的解释器
    "env", "printenv", "set",           # 环境变量泄露
    "kill", "pkill", "killall",         # 进程操作
    "chmod", "chown", "chgrp",          # 权限篡改
    "sudo", "su", "doas",               # 权限提升
    "crontab", "at", "batch",           # 定时任务
    "systemctl", "service", "launchctl", # 系统服务
    "docker", "kubectl",                # 容器操作
    "mount", "umount",                  # 挂载操作
    "fdisk", "mkfs",                    # 磁盘操作
    "dd",                               # 磁盘复制（危险）
    "shutdown", "reboot", "poweroff",   # 系统控制
]

# 危险路径模式正则（拦截路径跳转）
_DANGEROUS_PATH_PATTERNS = [
    r"\.\.",                            # 相对路径越权 (../)
    r"(?:^|\s|[<>|&;])/",               # Unix 绝对路径 (如 /etc)
    r"(?:^|\s|[<>|&;])~",               # Unix 主目录 (~/.ssh)
    r"(?:^|\s|[<>|&;])\\",              # Windows 根目录 (\)
    r"(?i)(?:^|\s|[<>|&;])[a-z]:",      # Windows 盘符 (C:, D:)
]


def _get_safe_path(relative_path: str) -> str:
    """
    将模型传入的相对路径转换为绝对路径，并检查是否越界。

    【符号链接防御】：
    使用 realpath 解析符号链接的真实路径，防止通过 ln -s 绕过沙盒。
    """
    # 将 OFFICE_DIR 转化为标准绝对路径（解析符号链接）
    base_dir = os.path.realpath(os.path.abspath(OFFICE_DIR))
    # 将目标路径转化为绝对路径并解析符号链接的真实路径
    target_path = os.path.realpath(os.path.abspath(os.path.join(base_dir, relative_path)))

    # 核心防御：目标路径的真实路径必须以 OFFICE_DIR 的真实路径开头
    if not target_path.startswith(base_dir):
        raise PermissionError(f"越权拦截：你试图访问沙盒外的路径 '{relative_path}'！你只能在 office 工位内活动。")

    return target_path


@my_tool
def start_task_folder(task_type: str = "") -> str:
    """
    创建任务工作目录，所有文档创建/编辑操作都应在该目录下进行。

    参数:
        task_type: 任务类型描述，如 "create-docx"、"create-pptx"、"edit-docx" 等。
                   可以为空，目录名会自动生成。

    返回:
        任务文件夹路径（相对于 office 工位），格式为 tasks/task-YYYY-MM-DD-NNN。
        示例: tasks/task-2026-05-27-001

    使用场景:
        当你需要创建 Word 文档、PPT 或编辑现有文档时，先调用此工具创建任务目录，
        然后在该目录下进行所有操作（解压、修改、打包等）。
    """
    try:
        tasks_dir = _get_safe_path("tasks")
        os.makedirs(tasks_dir, exist_ok=True)

        today = datetime.now().strftime("%Y-%m-%d")

        # 查找当天已有的任务序号
        existing_dirs = [d for d in os.listdir(tasks_dir)
                        if d.startswith(f"task-{today}-")]
        seq = len(existing_dirs) + 1

        folder_name = f"task-{today}-{seq:03d}"
        folder_path = os.path.join(tasks_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        task_desc = f" ({task_type})" if task_type else ""
        return f"✅ 任务目录已创建：{folder_name}{task_desc}\n所有操作请在该目录下进行。"

    except Exception as e:
        return f"❌ 创建任务目录失败：{str(e)}"


@my_tool
def list_office_files(sub_dir: str = "") -> str:
    """
    查看 office 工位里有哪些文件和文件夹。
    如果 sub_dir 为空，则查看工位根目录。
    """
    try:
        target_dir = _get_safe_path(sub_dir)
        if not os.path.exists(target_dir):
            return f"目录不存在：{sub_dir}"

        items = os.listdir(target_dir)
        if not items:
            return f"[{sub_dir if sub_dir else 'office 根目录'}] 是空的。"

        # 格式化输出，标注是文件还是文件夹
        result = []
        for item in items:
            item_path = os.path.join(target_dir, item)
            item_type = "📁" if os.path.isdir(item_path) else "📄"
            result.append(f"{item_type} {item}")

        return "\n".join(result)
    except Exception as e:
        return str(e)


@my_tool
def read_office_file(filepath: str) -> str:
    """
    读取 office 工位里指定文件的内容。
    filepath 参数应该是相对于 office 的路径，例如 "test.py" 或 "skills/my_skill.py"。
    """
    try:
        target_path = _get_safe_path(filepath)
        if not os.path.exists(target_path):
            return f"文件不存在：{filepath}"

        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
            # 防爆截断：防止读取过大的文件
            if len(content) > 10000:
                return content[:10000] + "\n\n...[内容过长，已被安全截断]..."
            return content
    except Exception as e:
        return str(e)


@my_tool
def write_office_file(filepath: str, content: str, mode: str = "w") -> str:
    """
    在 office 工位里操作文件内容。

    参数说明:
    - filepath: 相对路径，例如 "spider.py" 或 "docs/readme.md"。
    - content: 要写入的具体文本或代码内容。
    - mode: 写入模式。
        - "w" (默认): 覆盖/新建模式。如果文件已存在，将彻底清空原内容并写入新内容。
        - "a": 追加模式。保留原内容，将新内容追加到文件最末尾。
    ⚠️ 智能体操作规范：
    1. 如果你要修改一个长文件中间的某几行，目前最安全的做法是：读取原文件，在你的内存中完成替换，然后用 "w" 模式把【完整的最新代码】重写进去。
    2. 如果你需要重命名文件或删除文件，请直接使用 execute_office_shell 工具执行 `mv` 或 `rm` 命令。
    3. 禁止编写 与 跳出office工位 相关的任何语言脚本！
    """
    try:
        target_path = _get_safe_path(filepath)

        # 严格校验传入的 mode
        if mode not in ["w", "a"]:
            return "❌ 错误：mode 参数必须是 'w' (覆盖) 或 'a' (追加)。"

        # 如果模型想在子目录里写文件，确保子目录存在
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        with open(target_path, mode, encoding="utf-8") as f:
            # 如果是追加模式，且内容不是以换行符开头，自动补一个换行
            if mode == "a" and not content.startswith("\n"):
                f.write("\n" + content)
            else:
                f.write(content)

        action = "覆盖/新建" if mode == "w" else "追加"
        return f"成功以 {action} 模式写入文件：{filepath} (共 {len(content)} 字符)"
    except Exception as e:
        return str(e)


@my_tool
def execute_office_shell(command: str) -> str:
    """
    在 office 工位中执行 Shell 命令。

    【极其重要的安全限制】：
    1. 当前工作目录已经是 office 工位，所有文件路径必须使用相对路径，例如 `ls -la`、`ls *.pptx`、`node script.js`。
    2. 严禁使用绝对路径，包括 `/Users/.../workspace/office/...`；即使路径位于 office 内也会被拒绝。
    3. 禁止使用 `..`、`~`、Windows 盘符等目录跳转形式。
    4. 查看文件优先使用 list_office_files，不要用绝对路径执行 ls。
    5. 跨平台注意：当前宿主机可能是 Windows、Linux 或 Mac。请根据环境使用对应的原生 Shell 命令。
    6. 这是一个非交互式终端！所有命令必须携带免确认参数（如 -y, --quiet）。
    7. 每次执行都是独立的终端进程。需要进入子目录请使用命令链或相对路径。
    8. 危险命令黑名单：curl/wget/ssh/kill/sudo 等已被禁止。
    9. 环境隔离：只保留 PATH/HOME/LANG 等基础环境变量，API Key 等敏感信息不可访问。
    """
    try:
        force_execution = command.strip().startswith("!force ")
        if force_execution:
            command = command.strip()[7:].strip()

        # 1. 检查危险路径模式（路径跳转）
        for pattern in _DANGEROUS_PATH_PATTERNS:
            if re.search(pattern, command):
                return "❌ 权限拒绝：检测到绝对路径或目录跳转。execute_office_shell 的当前目录已经是 office，请改用相对路径，例如 `ls -la`、`ls *.pptx`、`node script.js`。"

        # 2. 检查危险命令黑名单（命令注入、外联、权限提升等）
        command_parts = command.strip().split()
        if command_parts:
            first_cmd = command_parts[0].lower()
            if first_cmd in _SAFE_INTERPRETERS:
                if len(command_parts) > 1 and command_parts[1] in {"-c", "-e"}:
                    return "❌ 权限拒绝：不允许通过 -c/-e 参数执行内联代码！"

                if len(command_parts) > 2 and command_parts[1] == "-m" and not force_execution:
                    return (
                        f"⚠️ 解释器模块执行请求：`{command}`\n"
                        f"该操作将运行模块 `{command_parts[2]}`，请确认无误后重新执行。\n"
                        f"如需确认执行，可在命令前添加 `!force ` 前缀。"
                    )

                if len(command_parts) > 1 and not command_parts[1].startswith("-"):
                    script_file = command_parts[1]
                    try:
                        _get_safe_path(script_file)
                    except PermissionError:
                        return f"❌ 权限拒绝：脚本 '{script_file}' 不在 office 工位内！"
            else:
                for dangerous_cmd in _DANGEROUS_COMMANDS:
                    if first_cmd == dangerous_cmd or first_cmd.startswith(dangerous_cmd + " "):
                        return f"❌ 权限拒绝：'{first_cmd}' 是危险命令，已被禁止执行！"

        # 3. 使用安全的环境变量白名单（防止敏感信息泄露）
        safe_env = _SAFE_ENV_WHITELIST.copy()

        result = subprocess.run(
            command,
            shell=True,
            cwd=OFFICE_DIR,
            env=safe_env,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )

        output = f" ● 当前系统: {SYS_OS}\n"
        output += f" ● 执行命令: `{command}`\n"
        output += f" ● 退出码 (Exit Code): {result.returncode}\n"

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0 and ("prompt" in stderr.lower() or "y/n" in stdout.lower()):
            output += "\n💡 系统提示：命令可能由于交互式等待而失败。请重试并添加 -y 参数！"

        if stdout:
            output += f"\n[STDOUT]\n{stdout[-2000:] if len(stdout) > 2000 else stdout}"
        if stderr:
            output += f"\n[STDERR]\n{stderr[-2000:] if len(stderr) > 2000 else stderr}"

        if not stdout and not stderr:
            if result.returncode == 0:
                output += "\n(静默执行完毕：无终端输出)"
            else:
                output += "\n(异常退出：Exit Code 非 0，无错误日志输出)"

        return output

    except subprocess.TimeoutExpired:
        return "❌ 严重错误：命令执行超时（60s）被熔断！请检查是否有阻塞式交互。"
    except Exception as e:
        return f"❌ 执行异常：{str(e)}"