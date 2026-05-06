import os
from dotenv import load_dotenv

load_dotenv()

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.dirname(CORE_DIR)
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)

WORKSPACE_DIR = os.getenv("MyCLAW_WORKSPACE", os.path.join(PROJECT_ROOT, "workspace"))


DB_PATH = os.path.join(WORKSPACE_DIR, "state.sqlite3")     # 状态机：潜意识与短期记忆
SESSIONS_FILE = os.path.join(WORKSPACE_DIR, "sessions.json") # 会话元数据：名字、描述、计数
MEMORY_DIR = os.path.join(WORKSPACE_DIR, "memory")         # 显性记忆：Markdown 画像
KNOWLEDGE_DIR = os.path.join(MEMORY_DIR, "knowledge")      # 知识库：长期事实 / 偏好 / 项目知识
KNOWLEDGE_INDEX_FILE = os.path.join(KNOWLEDGE_DIR, "index.json")
PERSONAS_DIR = os.path.join(WORKSPACE_DIR, "personas")     # 人设区：系统 Prompt
SCRIPTS_DIR = os.path.join(WORKSPACE_DIR, "scripts")       # 脚本区：自动化武器库
OFFICE_DIR = os.path.join(WORKSPACE_DIR, "office")         # 沙盒工位 唯一被允许执行文件与shell操作的空间
SKILLS_DIR = os.path.join(OFFICE_DIR, "skills")            # 技能卡槽
TASKS_FILE = os.path.join(WORKSPACE_DIR, "tasks.json")

for d in [WORKSPACE_DIR, MEMORY_DIR, KNOWLEDGE_DIR, PERSONAS_DIR, SCRIPTS_DIR, OFFICE_DIR, SKILLS_DIR]:
    os.makedirs(d, exist_ok=True)

print(f"🔧 [Config] Workspace 路径已就绪: {WORKSPACE_DIR}")