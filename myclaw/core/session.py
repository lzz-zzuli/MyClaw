import os
import json
import threading
from datetime import datetime, timezone
from typing import Optional

class SessionManager:
    """
    会话元数据管理器

    负责：
    - 创建新会话（自动生成 session_id）
    - 列出历史会话
    - 查找/重命名会话
    - 更新会话描述、消息计数
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, sessions_file: str = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init(sessions_file)
            return cls._instance

    def _init(self, sessions_file: str):
        from .config import SESSIONS_FILE
        self.sessions_file = sessions_file or SESSIONS_FILE
        self._file_lock = threading.Lock()
        os.makedirs(os.path.dirname(self.sessions_file), exist_ok=True)

    def _load_sessions(self) -> list[dict]:
        """读取会话列表"""
        with self._file_lock:
            if not os.path.exists(self.sessions_file):
                return []
            try:
                with open(self.sessions_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return []
                    return json.loads(content)
            except Exception:
                return []

    def _save_sessions(self, sessions: list[dict]):
        """保存会话列表"""
        with self._file_lock:
            with open(self.sessions_file, "w", encoding="utf-8") as f:
                json.dump(sessions, f, ensure_ascii=False, indent=2)

    def create_session(self, name: Optional[str] = None) -> dict:
        """
        创建新会话，返回会话元数据

        session_id 格式: session_YYYYMMDD_HHMMSS
        """
        now = datetime.now()
        session_id = f"session_{now.strftime('%Y%m%d_%H%M%S')}"

        session = {
            "session_id": session_id,
            "name": name or session_id,
            "description": "",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message_count": 0
        }

        sessions = self._load_sessions()
        sessions.append(session)
        self._save_sessions(sessions)

        return session

    def list_sessions(self) -> list[dict]:
        """列出所有历史会话（按更新时间倒序）"""
        sessions = self._load_sessions()
        return sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)

    def find_session(self, name: str) -> Optional[dict]:
        """
        按名称查找会话

        支持精确匹配 name 字段，也支持 session_id 匹配
        """
        sessions = self._load_sessions()
        for s in sessions:
            if s.get("name") == name or s.get("session_id") == name:
                return s
        return None

    def get_session(self, session_id: str) -> Optional[dict]:
        """按 session_id 获取会话"""
        sessions = self._load_sessions()
        for s in sessions:
            if s.get("session_id") == session_id:
                return s
        return None

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话"""
        sessions = self._load_sessions()
        for s in sessions:
            if s.get("session_id") == session_id:
                s["name"] = new_name
                s["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._save_sessions(sessions)
                return True
        return False

    def update_description(self, session_id: str, description: str) -> bool:
        """更新会话描述"""
        sessions = self._load_sessions()
        for s in sessions:
            if s.get("session_id") == session_id:
                s["description"] = description
                s["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._save_sessions(sessions)
                return True
        return False

    def increment_message_count(self, session_id: str) -> bool:
        """增加消息计数"""
        sessions = self._load_sessions()
        for s in sessions:
            if s.get("session_id") == session_id:
                s["message_count"] = s.get("message_count", 0) + 1
                s["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                self._save_sessions(sessions)
                return True
        return False

    def delete_session(self, session_id: str) -> bool:
        """删除会话元数据（不删除 SQLite 状态和日志）"""
        sessions = self._load_sessions()
        new_sessions = [s for s in sessions if s.get("session_id") != session_id]
        if len(new_sessions) < len(sessions):
            self._save_sessions(new_sessions)
            return True
        return False


session_manager = SessionManager()