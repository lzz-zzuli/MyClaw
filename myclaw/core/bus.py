import asyncio


task_queue = asyncio.Queue()

async def emit_task(content: str):
    # 异步任务队列总线，用于解耦用户输入和 Agent 处理
    await task_queue.put(content)