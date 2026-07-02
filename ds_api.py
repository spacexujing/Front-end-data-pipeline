"""
ds_api.py — DeepSeek 大模型调用接口

支持 DeepSeek 官方 API（OpenAI 兼容协议），提供同步和流式两种调用方式。

Usage:
    from ds_api import DeepSeekClient

    client = DeepSeekClient()  # 自动从参数 → 环境变量 → key.config 中读取 API Key
    # 或
    client = DeepSeekClient(api_key="sk-xxx")

    # 普通调用
    reply = client.chat("你好，请介绍一下自己")
    print(reply)

    # 流式调用
    for chunk in client.chat_stream("写一首关于编程的诗"):
        print(chunk, end="", flush=True)

    # 多轮对话
    messages = [
        {"role": "system", "content": "你是一个前端设计专家。"},
        {"role": "user",   "content": "如何提升网页的视觉层次感？"},
    ]
    reply = client.chat(messages)
"""

from __future__ import annotations

import os
import json
import logging
from typing import Optional, List, Dict, Any, Union, Iterator

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"          # 日常对话
DEFAULT_REASONER = "deepseek-reasoner"   # 推理模型（DeepSeek-R1）
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT = 120  # 秒

_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "key.config")


def _load_api_key_from_config() -> Optional[str]:
    """从 key.config 文件中读取 DEEPSEEK_API_KEY。"""
    if not os.path.isfile(_CONFIG_PATH):
        return None
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("DEEPSEEK_API_KEY="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
    except OSError:
        pass
    return None

# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class DeepSeekError(Exception):
    """DeepSeek API 调用异常"""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 response_body: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


class DeepSeekAuthError(DeepSeekError):
    """认证失败（API Key 无效或过期）"""
    pass


class DeepSeekRateLimitError(DeepSeekError):
    """频率限制"""
    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """
    DeepSeek API 客户端。

    Args:
        api_key: API 密钥，默认从环境变量 DEEPSEEK_API_KEY 读取
        base_url: API 地址，默认 https://api.deepseek.com
        model: 默认模型名称
        temperature: 默认温度参数
        max_tokens: 默认最大 token 数
        timeout: 请求超时时间（秒）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.api_key = (
            api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or _load_api_key_from_config()
            or ""
        )
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_key:
            raise DeepSeekAuthError(
                "未设置 API Key。请传入 api_key 参数、设置环境变量 DEEPSEEK_API_KEY，"
                "或在 key.config 中配置 DEEPSEEK_API_KEY=sk-xxx"
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def chat(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **extra_kwargs,
    ) -> str:
        """
        发送对话请求，返回模型回复文本。

        Args:
            prompt: 用户消息字符串，或完整的 messages 列表。
            model: 模型名称，默认使用实例配置。
            system: system prompt（仅 prompt 为字符串时生效）。
            temperature: 采样温度。
            max_tokens: 最大输出 token 数。
            **extra_kwargs: 其他 OpenAI 兼容参数（top_p, stop 等）。

        Returns:
            模型回复的文本内容。
        """
        messages = self._build_messages(prompt, system)
        body = self._build_body(messages, model, temperature, max_tokens, extra_kwargs)

        resp = self._request("POST", "/chat/completions", body)
        return resp["choices"][0]["message"]["content"]

    def chat_stream(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **extra_kwargs,
    ) -> Iterator[str]:
        """
        流式对话，逐步 yield 模型回复文本。

        用法与 chat() 相同，返回一个生成器。
        """
        messages = self._build_messages(prompt, system)
        body = self._build_body(messages, model, temperature, max_tokens, extra_kwargs)
        body["stream"] = True

        resp = self._session.post(
            f"{self.base_url}/chat/completions",
            json=body,
            timeout=self.timeout,
            stream=True,
        )
        self._check_response(resp)

        for line in resp.iter_lines(decode_unicode=True):
            if not line or line.startswith(":"):
                continue
            if line == "data: [DONE]":
                break
            if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    def chat_with_tools(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        tools: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **extra_kwargs,
    ) -> Dict[str, Any]:
        """
        带 tool calling 的对话，返回完整的 message 对象。

        Returns:
            {"role": "assistant", "content": ..., "tool_calls": [...]}
        """
        messages = self._build_messages(prompt, system)
        body = self._build_body(messages, model, temperature, max_tokens, extra_kwargs)
        body["tools"] = tools

        resp = self._request("POST", "/chat/completions", body)
        return resp["choices"][0]["message"]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        system: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """构建标准 messages 列表。"""
        if isinstance(prompt, list):
            return prompt
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_body(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建请求 body。"""
        body: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        body.update(extra)
        return body

    def _request(
        self,
        method: str,
        endpoint: str,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """发送同步 HTTP 请求，检查错误并返回 JSON。"""
        url = f"{self.base_url}{endpoint}"
        logger.debug("DeepSeek API request: %s %s", method, url)

        resp = self._session.request(
            method=method,
            url=url,
            json=body,
            timeout=self.timeout,
        )
        self._check_response(resp)
        return resp.json()

    def _check_response(self, resp: requests.Response) -> None:
        """检查 HTTP 响应，按状态码抛出对应异常。"""
        if resp.status_code < 300:
            return

        try:
            error_body = resp.json()
        except ValueError:
            error_body = {}

        error_msg = error_body.get("error", {}).get("message", resp.text)

        if resp.status_code == 401:
            raise DeepSeekAuthError(error_msg, status_code=401, response_body=error_body)
        if resp.status_code == 429:
            raise DeepSeekRateLimitError(error_msg, status_code=429, response_body=error_body)
        raise DeepSeekError(error_msg, status_code=resp.status_code, response_body=error_body)


# ==========================================================================
# 模块级快捷函数（使用默认客户端）
# ==========================================================================

_default_client: Optional[DeepSeekClient] = None


def _get_client() -> DeepSeekClient:
    """获取或懒初始化默认客户端。"""
    global _default_client
    if _default_client is None:
        _default_client = DeepSeekClient()
    return _default_client


def chat(prompt: Union[str, List[Dict[str, str]]], **kwargs) -> str:
    """快捷函数：使用默认客户端进行对话调用。"""
    return _get_client().chat(prompt, **kwargs)


def chat_stream(prompt: Union[str, List[Dict[str, str]]], **kwargs) -> Iterator[str]:
    """快捷函数：使用默认客户端进行流式对话。"""
    return _get_client().chat_stream(prompt, **kwargs)


# ==========================================================================
# CLI
# ==========================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ds_api.py <你的问题>")
        print("       python ds_api.py --stream <你的问题>")
        print()
        print("API Key 配置方式（按优先级）:")
        print("  1. 传入 api_key 参数")
        print("  2. 环境变量 DEEPSEEK_API_KEY")
        print("  3. key.config 文件中的 DEEPSEEK_API_KEY")
        sys.exit(1)

    use_stream = sys.argv[1] == "--stream"
    question = " ".join(sys.argv[2:] if use_stream else sys.argv[1:])

    client = DeepSeekClient()

    if use_stream:
        print("Assistant: ", end="", flush=True)
        for chunk in client.chat_stream(question):
            print(chunk, end="", flush=True)
        print()
    else:
        print("Assistant:", client.chat(question))
