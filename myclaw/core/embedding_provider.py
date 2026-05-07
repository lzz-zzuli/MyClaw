import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# 各提供商默认 Embedding 模型
EMBEDDING_DEFAULT_MODELS = {
    "openai": "text-embedding-3-small",
    "aliyun": "text-embedding-v3",
    "dashscope": "text-embedding-v3",
    "z.ai": "embedding-3",
    "tencent": "hunyuan-embedding",
    "ollama": "nomic-embed-text",
}

# 各厂商 OpenAI 兼容接口地址 (与 provider.py 保持一致)
COMPATIBLE_BASE_URLS = {
    "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "z.ai": "https://open.bigmodel.cn/api/paas/v4",
    "tencent": "https://api.hunyuan.cloud.tencent.com/v1",
}


def get_embedding_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any | None:
    """
    Embedding 提供商工厂 (遵循 provider.py 的 get_provider 模式)

    参数:
        provider_name: 提供商名称 (openai, aliyun, dashscope, z.ai, tencent, ollama)
                       None 时从 EMBEDDING_PROVIDER 环境变量读取
                       环境变量也未配置则返回 None (降级为纯关键词)
        model_name:    模型名称, None 时从 EMBEDDING_MODEL 读取, 仍未配置则使用默认模型
        base_url:      自定义 API 地址, None 时从 EMBEDDING_API_BASE / OPENAI_API_BASE 读取
        api_key:       自定义 API Key, None 时从 EMBEDDING_API_KEY / OPENAI_API_KEY 读取

    返回:
        langchain Embeddings 实例, 或 None (降级模式)
    """
    # 1. 解析 provider_name
    resolved_provider = provider_name or os.environ.get("EMBEDDING_PROVIDER", "")
    if not resolved_provider:
        return None

    resolved_provider = resolved_provider.lower()

    # 2. 解析 model_name
    resolved_model = model_name or os.environ.get("EMBEDDING_MODEL", "")
    if not resolved_model:
        resolved_model = EMBEDDING_DEFAULT_MODELS.get(resolved_provider, "")
    if not resolved_model:
        return None

    # 3. 按提供商分支
    if resolved_provider in ["openai", "aliyun", "dashscope", "z.ai", "tencent", "other"]:
        from langchain_openai import OpenAIEmbeddings

        current_api_key = api_key or os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not current_api_key:
            return None

        final_base_url = base_url or os.environ.get("EMBEDDING_API_BASE") or os.environ.get("OPENAI_API_BASE")
        if not final_base_url:
            final_base_url = COMPATIBLE_BASE_URLS.get(resolved_provider)

        kwargs = {
            "model": resolved_model,
            "api_key": current_api_key,
        }
        if final_base_url:
            kwargs["base_url"] = final_base_url

        return OpenAIEmbeddings(**kwargs)

    elif resolved_provider == "ollama":
        # 优先使用 langchain_ollama (新版, 无弃用警告), 回退到 langchain_community
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            from langchain_community.embeddings import OllamaEmbeddings

        final_base_url = base_url or os.environ.get("EMBEDDING_API_BASE") or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

        return OllamaEmbeddings(model=resolved_model, base_url=final_base_url)

    else:
        return None
