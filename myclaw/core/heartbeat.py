import os
import json
import asyncio
from datetime import datetime, timedelta
from .config import TASKS_FILE
from .bus import task_queue
from .tools.builtins import tasks_lock


def _check_and_process_tasks(lock, thread_id: str) -> list:
    """
    同步函数：检查并处理到期任务（在线程池中执行）。

    Args:
        lock: threading.Lock，用于保护 tasks.json 文件操作
        thread_id: 当前会话的 thread_id，用于过滤定时任务

    Returns:
        triggered_tasks: 已到期的任务列表，需要放入队列触发
    """
    if not os.path.exists(TASKS_FILE):
        return []

    now = datetime.now()
    pending_tasks = []
    triggered_tasks = []

    with lock:  # 同步函数中使用同步锁，正确！
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                tasks = json.loads(content)
        except Exception:
            return []

        if not tasks:
            return []

        for t in tasks:
            # 只处理当前 thread_id 的任务
            task_thread_id = t.get("thread_id")
            if thread_id and task_thread_id and task_thread_id != thread_id:
                pending_tasks.append(t)
                continue

            try:
                target_dt = datetime.strptime(t["target_time"], "%Y-%m-%d %H:%M:%S")
                if now >= target_dt:
                    triggered_tasks.append(t)

                    repeat_freq = t.get("repeat")
                    if repeat_freq:
                        repeat_count = t.get("repeat_count")

                        if repeat_count is not None:
                            if repeat_count <= 1:
                                continue
                            else:
                                t["repeat_count"] = repeat_count - 1

                        if repeat_freq == "hourly":
                            next_dt = target_dt + timedelta(hours=1)
                        elif repeat_freq == "daily":
                            next_dt = target_dt + timedelta(days=1)
                        elif repeat_freq == "weekly":
                            next_dt = target_dt + timedelta(days=7)
                        else:
                            continue

                        t["target_time"] = next_dt.strftime("%Y-%m-%d %H:%M:%S")
                        pending_tasks.append(t)
                else:
                    pending_tasks.append(t)
            except Exception:
                pass

        if triggered_tasks:
            try:
                with open(TASKS_FILE, "w", encoding="utf-8") as f:
                    json.dump(pending_tasks, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    return triggered_tasks


async def pacemaker_loop(check_interval: int = 10, thread_id: str = None):
    """
    后台心脏起搏器协程。

    Args:
        check_interval: 检查间隔秒数
        thread_id: 当前会话的 thread_id，用于过滤定时任务
    """
    while True:
        await asyncio.sleep(check_interval)

        # 在线程池中执行同步操作（不阻塞主线程）
        triggered_tasks = await asyncio.to_thread(
            _check_and_process_tasks,
            tasks_lock,
            thread_id
        )

        # 异步部分：把触发任务放入队列
        for t in triggered_tasks:
            system_msg = (
                f"【系统内部心跳触发】\n"
                f"你设定的定时任务已到期，请立即主动提醒用户或执行动作。\n"
                f"任务内容：{t['description']}"
            )
            # Agent 会收到这条消息，自动执行提醒或动作
            await task_queue.put(system_msg)