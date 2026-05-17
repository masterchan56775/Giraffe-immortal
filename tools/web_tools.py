"""
Web 工具
获取 URL 并转换为 Markdown。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from tools.base import BaseTool, PermissionResult, ToolContext, ToolResult

_MAX_CONTENT_CHARS = 50_000

def _html_to_markdown(html: str) -> str:
    """
    简单的 HTML→Markdown 转换（不依赖额外库）。
    如果安装了 markdownify 则使用它。
    """
    try:
        import markdownify
        return markdownify.markdownify(html, heading_style="ATX")
    except ImportError:
        pass

    # 回退：简单清理
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

class WebFetchTool(BaseTool):
    """
    获取 URL 内容并返回 Markdown。
    支持 HTTP/HTTPS，超时 30s。
    不执行 JavaScript（纯 HTTP 请求）。
    """

    name = "web_fetch"
    description = (
        "获取 URL 内容（HTTP GET）并转换为 Markdown 文本。"
        "不支持需要 JavaScript 渲染的页面。"
        "适合读取文档、API 响应、静态页面等。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要获取的 URL（http:// 或 https://）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 30）",
                "default": 30,
            },
            "raw": {
                "type": "boolean",
                "description": "返回原始文本（不转 Markdown，默认 false）",
                "default": False,
            },
        },
        "required": ["url"],
    }
    is_read_only = True

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        url = args.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return PermissionResult(
                behavior="deny",
                message=f"不支持的协议：{parsed.scheme}（仅允许 http/https）",
            )
        # 本地/私有地址需确认
        host = parsed.hostname or ""
        private_hosts = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
        if host in private_hosts or host.startswith("192.168.") or host.startswith("10."):
            return PermissionResult(
                behavior="ask",
                message=f"即将访问本地/内网地址：{url}，确认？",
            )
        return PermissionResult(behavior="allow")

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        url: str = args["url"]
        timeout: int = min(int(args.get("timeout", 30)), 60)
        raw: bool = args.get("raw", False)

        try:
            import urllib.request
            import urllib.error

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; GiraffeAgent/1.0)"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 读取内容
                content_type = resp.headers.get("Content-Type", "")
                raw_bytes = resp.read(_MAX_CONTENT_CHARS * 3)   # 多读一点留给截断
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                text = raw_bytes.decode(charset, errors="replace")

        except ImportError:
            return ToolResult(content="urllib 不可用", is_error=True)
        except Exception as e:
            return ToolResult(content=f"请求失败：{e}", is_error=True)

        if raw:
            content = text
        elif "html" in content_type.lower():
            content = _html_to_markdown(text)
        else:
            content = text

        # 截断
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + "\n\n...[内容截断]"

        header = f"URL: {url}\n\n"
        return ToolResult(content=header + content)

    def is_concurrency_safe(self, args: dict) -> bool:
        return True
