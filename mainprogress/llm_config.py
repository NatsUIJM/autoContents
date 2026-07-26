"""LLM 配置统一加载模块。

全项目唯一的 LLM 配置来源，优先级：
1. 环境变量 AUTOCONTENTS_API_KEY / AUTOCONTENTS_BASE_URL / AUTOCONTENTS_MODEL
2. static/llm_config.json（支持 $ENV_VAR$ 引用环境变量）

app.py 的 Web 配置管理（增删改查配置文件）仍保留在 app.py 中，
本模块只负责"解析出最终可用的 api_key / base_url / model"。
"""

import json
import os
from pathlib import Path

ENV_API_KEY = "AUTOCONTENTS_API_KEY"
ENV_BASE_URL = "AUTOCONTENTS_BASE_URL"
ENV_MODEL = "AUTOCONTENTS_MODEL"

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-397b-a17b"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "static" / "llm_config.json"


def resolve_value(val):
    """解析 $ENV_VAR$ 形式的环境变量引用，其余原样返回。"""
    if isinstance(val, str) and val.startswith("$") and val.endswith("$"):
        env_val = os.getenv(val[1:-1])
        if env_val is None:
            raise ValueError(f"环境变量 {val[1:-1]} 未设置")
        return env_val
    return val


def _load_from_file():
    """从 static/llm_config.json 读取激活配置，文件不存在或无有效配置时返回 None。"""
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    configs = data.get("configs")
    if configs is not None:
        # 新格式：多配置 + active_id
        active_id = data.get("active_id")
        config = None
        if active_id:
            for c in configs:
                if c.get("id") == active_id:
                    config = c
                    break
        if not config and configs:
            config = configs[0]
        if not config:
            return None
    else:
        # 旧格式：单层字典
        config = data

    return {
        "api_key": resolve_value(config.get("api_key", "")) or "",
        "base_url": resolve_value(config.get("base_url", "")) or DEFAULT_BASE_URL,
        "model": resolve_value(config.get("model", "")) or DEFAULT_MODEL,
    }


def load_llm_config() -> dict:
    """返回 {"api_key", "base_url", "model"}。

    环境变量优先于配置文件；任一来源提供 api_key 即可，
    base_url / model 缺省时使用默认值。无可用 api_key 时抛出 ValueError。
    """
    env_key = os.getenv(ENV_API_KEY, "").strip()
    if env_key:
        return {
            "api_key": env_key,
            "base_url": os.getenv(ENV_BASE_URL, "").strip() or DEFAULT_BASE_URL,
            "model": os.getenv(ENV_MODEL, "").strip() or DEFAULT_MODEL,
        }

    file_config = _load_from_file()
    if file_config and file_config["api_key"]:
        return file_config

    raise ValueError(
        "未找到可用的 LLM 配置：请设置环境变量 "
        f"{ENV_API_KEY}（可选 {ENV_BASE_URL} / {ENV_MODEL}），"
        f"或在 {CONFIG_PATH} 中配置 api_key"
    )


def get_async_client(**client_kwargs):
    """基于当前配置创建 openai.AsyncOpenAI 客户端。"""
    from openai import AsyncOpenAI

    cfg = load_llm_config()
    return AsyncOpenAI(
        api_key=cfg["api_key"], base_url=cfg["base_url"], **client_kwargs
    ), cfg
