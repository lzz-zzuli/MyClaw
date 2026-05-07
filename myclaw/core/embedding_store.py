import hashlib
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .config import VEC_INDEX_FILE
from .embedding_provider import get_embedding_provider


class EmbeddingStore:
    """
    知识库向量存储管理器 (sqlite-vec 封装)

    职责:
    - 管理 sqlite-vec 向量数据库连接
    - 增量嵌入: 新增/更新记忆时嵌入, content_hash 未变时跳过
    - 删除向量: 删除记忆时清理
    - 语义检索: 给定查询文本, 返回最相似的 note_id 列表
    - 启动同步: 检测未嵌入/过期的记忆, 补充嵌入

    降级策略: embedding_provider 为 None 时 is_available() 返回 False,
    所有操作变为空操作, 检索退化为纯关键词匹配
    """

    def __init__(self, db_path: str, embedding_provider: Any | None):
        """
        初始化向量存储管理器

        Args:
            db_path: vec_index.sqlite3 文件路径
            embedding_provider: langchain Embeddings 实例, None 表示降级模式
        """
        self._db_path = db_path
        self._provider = embedding_provider
        self._available = embedding_provider is not None
        self._conn: sqlite3.Connection | None = None
        self._dim: int = 0  # 当前向量维度, 0 表示未初始化
        self._model_name: str = ""
        self._lock = threading.Lock()

        # provider 为 None 时跳过所有数据库初始化, 直接进入降级模式
        if not self._available:
            return

        try:
            self._init_db()
        except Exception as e:
            print(f"⚠️  [EmbeddingStore] 数据库初始化失败, 降级为纯关键词: {e}")
            self._available = False

    def is_available(self) -> bool:
        """Embedding 是否可用 (provider 非 None 且数据库初始化成功)"""
        return self._available

    # ── 数据库初始化 ──────────────────────────────────────

    def _init_db(self):
        """打开 SQLite 连接, 加载 sqlite-vec 扩展, 探测维度, 创建表"""
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.enable_load_extension(True)

        import sqlite_vec
        sqlite_vec.load(self._conn)

        # 通过实际嵌入一段文本来探测向量维度 (不同模型维度不同)
        # bge-m3=1024, nomic-embed-text=768, text-embedding-3-small=1536
        self._dim = self._detect_dimension()
        if self._dim <= 0:
            raise RuntimeError("无法探测 Embedding 模型维度")

        # 从 provider 实例获取模型名, 用于元数据记录
        if hasattr(self._provider, "model"):
            self._model_name = self._provider.model
        elif hasattr(self._provider, "model_name"):
            self._model_name = self._provider.model_name
        else:
            self._model_name = "unknown"

        # 如果已有向量表的维度与当前模型不匹配 (如换了模型), 需要重建
        existing_dim = self._get_existing_dimension()
        if existing_dim is not None and existing_dim != self._dim:
            print(f"🔄 [EmbeddingStore] 维度变更 {existing_dim}→{self._dim}, 重建向量表")
            self._rebuild_tables()

        self._ensure_tables()

    def _detect_dimension(self) -> int:
        """
        通过实际调用 embed_query 探测当前模型的向量维度

        不硬编码维度是因为不同模型输出不同: bge-m3=1024, text-embedding-3-small=1536
        返回 0 表示探测失败
        """
        try:
            vec = self._provider.embed_query("dimension probe")
            return len(vec)
        except Exception as e:
            print(f"⚠️  [EmbeddingStore] 维度探测失败: {e}")
            return 0

    def _get_existing_dimension(self) -> int | None:
        """读取数据库中已有向量的维度, 表不存在或为空时返回 None"""
        try:
            cursor = self._conn.execute(
                "SELECT embedding_dim FROM embedding_meta LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _ensure_tables(self):
        """
        确保数据库表存在

        创建两张表:
        - embedding_meta: 元数据表 (note_id, title, content_hash, 维度, 模型名, 时间戳)
        - note_vectors_{dim}: vec0 虚拟表 (note_id + float向量)
          表名带维度后缀, 因为 sqlite-vec 的 vec0 虚拟表维度在建表时固定, 不可修改
        """
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS embedding_meta (
                note_id       TEXT PRIMARY KEY,
                title         TEXT NOT NULL,
                content_hash  TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                model_name    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );
        """)

        # vec0 虚拟表: 维度在创建时固定, 不同维度对应不同表
        table_name = f"note_vectors_{self._dim}"
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} "
            f"USING vec0(note_id TEXT PRIMARY KEY, vector float[{self._dim}])"
        )
        self._vec_table = table_name
        self._conn.commit()

    def _rebuild_tables(self):
        """
        维度变更时重建向量表

        场景: 用户换了 Embedding 模型 (如从 bge-m3 换成 nomic-embed-text),
        维度从 1024 变为 768, 旧向量无法复用, 必须清空重建
        """
        if self._conn:
            try:
                old_dim = self._get_existing_dimension()
                if old_dim:
                    self._conn.execute(f"DROP TABLE IF EXISTS note_vectors_{old_dim}")
                self._conn.execute("DELETE FROM embedding_meta")
                self._conn.commit()
            except Exception:
                pass

    # ── 嵌入文本构造 ──────────────────────────────────────

    @staticmethod
    def _build_embedding_text(title: str, content: str, tags: list[str]) -> str:
        """
        构造用于嵌入的文本

        策略: title 重复一次提升其在语义表示中的权重
        (Embedding 模型对重复出现的文本会赋予更高关注度)
        格式: "{title}。{title}。{tags}。{content}"
        """
        tag_text = " ".join(tags) if tags else ""
        if tag_text:
            return f"{title}。{title}。{tag_text}。{content}"
        return f"{title}。{title}。{content}"

    @staticmethod
    def _get_content_hash(text: str) -> str:
        """
        计算文本的 SHA256 前 16 字符

        用途: 检测内容是否变更, 未变更时跳过嵌入调用, 节省 API 费用
        (不是存完整内容的哈希用于还原, 仅用于变更检测)
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    # ── 向量归一化 ────────────────────────────────────────

    @staticmethod
    def _normalize_vector(vec: list[float]) -> list[float]:
        """
        L2 归一化: 将向量缩放为单位长度 (||v||=1)

        为什么归一化: 归一化后 L2 距离与余弦相似度有简单换算关系
        cosine_similarity = 1 - L2_distance / 2
        这样 sqlite-vec 返回的 L2 距离可以直接转换为余弦相似度
        """
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()

    # ── 核心操作 ──────────────────────────────────────────

    def embed_and_upsert(self, note_id: str, title: str, content: str, tags: list[str]) -> None:
        """
        嵌入一条记忆并写入向量库

        流程:
        1. 构造嵌入文本 (title×2 + tags + content)
        2. 计算 content_hash, 与数据库中已有 hash 对比, 未变则跳过
        3. 调用 Embedding API 将文本转为向量
        4. L2 归一化向量
        5. 序列化为二进制 blob, 写入 sqlite-vec 虚拟表
        6. 更新 embedding_meta 元数据

        嵌入失败时仅打印警告, 不抛异常, 不影响记忆写入本身
        """
        if not self._available:
            return

        text = self._build_embedding_text(title, content, tags)
        content_hash = self._get_content_hash(text)

        # 检查是否需要重新嵌入 (content_hash 未变则跳过, 省一次 API 调用)
        with self._lock:
            cursor = self._conn.execute(
                "SELECT content_hash FROM embedding_meta WHERE note_id = ?",
                (note_id,),
            )
            row = cursor.fetchone()
            if row and row[0] == content_hash:
                return  # 内容未变, 跳过

        try:
            # 调用 Embedding API, embed_documents 接受文本列表, 返回向量列表
            vectors = self._provider.embed_documents([text])
            vec = self._normalize_vector(vectors[0])

            # sqlite-vec 要求向量以二进制 blob 形式传入
            import sqlite_vec
            vec_blob = sqlite_vec.serialize_float32(vec)

            now = datetime.now(timezone.utc).isoformat()

            with self._lock:
                # 先删除旧向量 (若存在), 避免主键冲突
                self._conn.execute(
                    f"DELETE FROM {self._vec_table} WHERE note_id = ?",
                    (note_id,),
                )
                # 写入新向量
                self._conn.execute(
                    f"INSERT INTO {self._vec_table} (note_id, vector) VALUES (?, ?)",
                    (note_id, vec_blob),
                )
                # 更新元数据 (ON CONFLICT 实现 upsert)
                self._conn.execute(
                    """INSERT INTO embedding_meta (note_id, title, content_hash, embedding_dim, model_name, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(note_id) DO UPDATE SET
                         title=excluded.title, content_hash=excluded.content_hash,
                         embedding_dim=excluded.embedding_dim, model_name=excluded.model_name,
                         updated_at=excluded.updated_at""",
                    (note_id, title, content_hash, self._dim, self._model_name, now, now),
                )
                self._conn.commit()

        except Exception as e:
            print(f"⚠️  [EmbeddingStore] 嵌入失败 note_id={note_id}: {e}")

    def remove(self, note_id: str) -> None:
        """
        删除一条记忆的向量记录

        同时从 vec0 虚拟表和 embedding_meta 元数据表删除
        """
        if not self._available:
            return

        with self._lock:
            self._conn.execute(
                f"DELETE FROM {self._vec_table} WHERE note_id = ?",
                (note_id,),
            )
            self._conn.execute(
                "DELETE FROM embedding_meta WHERE note_id = ?",
                (note_id,),
            )
            self._conn.commit()

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """
        语义检索: 给定查询文本, 返回最相似的 note_id 列表

        流程:
        1. 将查询文本嵌入为向量
        2. L2 归一化
        3. 用 sqlite-vec 的 MATCH 语法做向量近邻搜索
        4. 将返回的 L2 距离转换为余弦相似度:
           归一化向量下, cosine = 1 - L2_distance / 2

        Args:
            query: 查询文本 (如用户输入)
            top_k: 返回最相似的 K 条, 默认 20

        Returns:
            [(note_id, cosine_similarity), ...] 按相似度降序
            失败时返回空列表
        """
        if not self._available:
            return []

        try:
            # 将查询文本嵌入为向量
            query_vec = self._provider.embed_query(query)
            query_vec = self._normalize_vector(query_vec)

            # 序列化为 sqlite-vec 要求的二进制格式
            import sqlite_vec
            query_blob = sqlite_vec.serialize_float32(query_vec)

            # sqlite-vec 向量近邻搜索: WHERE vector MATCH ? 按 L2 距离排序
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT note_id, distance FROM {self._vec_table} "
                    f"WHERE vector MATCH ? ORDER BY distance LIMIT ?",
                    (query_blob, top_k),
                )
                rows = cursor.fetchall()

            # sqlite-vec 对 float 向量返回 L2 距离
            # 归一化向量的数学关系: cosine_similarity = 1 - distance / 2
            # 值域: 1.0=完全相同, 0.0=完全无关
            results = []
            for note_id, distance in rows:
                cosine_sim = max(0.0, 1.0 - distance / 2)
                results.append((note_id, cosine_sim))

            return results

        except Exception as e:
            print(f"⚠️  [EmbeddingStore] 语义检索失败: {e}")
            return []

    def sync_missing(self, index_items: list[dict]) -> None:
        """
        启动时同步: 补充未嵌入的记忆, 清理已删除记忆的向量残留

        两个方向的差集:
        - index.json 有但数据库没有 → 补充嵌入
        - 数据库有但 index.json 没有 → 清理残留向量

        典型场景: 用户手动删除了 .md 文件但没走 delete_memory_note,
        或数据库文件被删后重建
        """
        if not self._available:
            return

        # 获取已有嵌入的 note_id 集合
        with self._lock:
            cursor = self._conn.execute("SELECT note_id FROM embedding_meta")
            embedded_ids = {row[0] for row in cursor.fetchall()}

        index_ids = {item.get("id", "") for item in index_items if item.get("id")}

        # 补充缺失的嵌入 (index.json 有但数据库没有)
        missing_ids = index_ids - embedded_ids
        if missing_ids:
            print(f"🔄 [EmbeddingStore] 补充嵌入 {len(missing_ids)} 条记忆...")
            for item in index_items:
                note_id = item.get("id", "")
                if note_id not in missing_ids:
                    continue
                # 从 .md 文件加载完整记录再嵌入
                record = self._load_note_record(note_id)
                if record:
                    self.embed_and_upsert(
                        note_id=note_id,
                        title=record.get("title", ""),
                        content=record.get("content", ""),
                        tags=record.get("tags", []),
                    )

        # 清理残留向量 (数据库有但 index.json 没有)
        stale_ids = embedded_ids - index_ids
        if stale_ids:
            print(f"🧹 [EmbeddingStore] 清理 {len(stale_ids)} 条残留向量...")
            for note_id in stale_ids:
                self.remove(note_id)

    @staticmethod
    def _load_note_record(note_id: str) -> dict | None:
        """
        从 .md 文件加载完整记忆记录

        解析 YAML frontmatter 提取元数据, body 部分作为 content
        文件不存在时返回 None
        """
        from .config import KNOWLEDGE_DIR
        import yaml

        filepath = os.path.join(KNOWLEDGE_DIR, f"{note_id}.md")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        # 解析 frontmatter (--- 包裹的 YAML 头部)
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                except Exception:
                    meta = {}
                content = parts[2].strip()
                return {
                    "id": meta.get("id", note_id),
                    "title": meta.get("title", ""),
                    "tags": meta.get("tags", []),
                    "content": content,
                }

        # 无 frontmatter 的降级处理: 整个文件作为 content
        return {"id": note_id, "title": "", "tags": [], "content": raw.strip()}

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None


# ── 单例管理 ──────────────────────────────────────────────

# 全局唯一实例, 避免重复打开数据库
_store_instance: EmbeddingStore | None = None
_store_lock = threading.Lock()


def get_embedding_store() -> EmbeddingStore:
    """
    获取全局 EmbeddingStore 单例

    首次调用时:
    1. 通过 get_embedding_provider() 创建 Embeddings 实例
    2. 初始化 EmbeddingStore (打开数据库, 探测维度, 建表)
    3. 执行 sync_missing() 补充未嵌入的记忆

    后续调用直接返回已有实例
    """
    global _store_instance
    if _store_instance is not None:
        return _store_instance
    with _store_lock:
        if _store_instance is None:
            provider = get_embedding_provider()
            _store_instance = EmbeddingStore(VEC_INDEX_FILE, provider)
            if _store_instance.is_available():
                # 启动时同步: 将 index.json 中未嵌入的记忆补充到向量库
                from .tools.builtins import _load_knowledge_index
                try:
                    index_items = _load_knowledge_index()
                    _store_instance.sync_missing(index_items)
                except Exception as e:
                    print(f"⚠️  [EmbeddingStore] 启动同步失败: {e}")
        return _store_instance


def reset_embedding_store():
    """重置单例 (测试用, 关闭连接并清空实例, 下次 get_embedding_store 会重新创建)"""
    global _store_instance
    with _store_lock:
        if _store_instance is not None:
            _store_instance.close()
        _store_instance = None
