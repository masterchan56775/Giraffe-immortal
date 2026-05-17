"""
AgenticLoop — 。
支持 Claude/Gemini/Grok 三个 provider 的 streaming tool use。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable

from tools.base import BaseTool, PermissionResult, ToolContext, ToolResult

logger = logging.getLogger("agentic_loop")

MAX_TURNS = 50          # 防止死循环

# ─── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """一次 tool_use 调用（流式积累后完整）。"""
    tool_use_id: str
    name: str
    input: dict = field(default_factory=dict)
    # 流式积累 JSON 片段
    _input_buf: str = field(default="", repr=False)

    def append_json(self, chunk: str) -> None:
        self._input_buf += chunk

    def finalize(self) -> None:
        if self._input_buf and not self.input:
            try:
                self.input = json.loads(self._input_buf)
            except json.JSONDecodeError:
                self.input = {"_raw": self._input_buf}

@dataclass
class AgenticResult:
    final_text: str
    tool_calls_made: int = 0
    turns: int = 0
    error: str | None = None

# ─── 权限确认（CLI 交互）──────────────────────────────────────────────────

def _ask_user_permission(msg: str) -> bool:
    """阻塞式终端确认，对应 src 的 canUseTool 'ask' 行为。"""
    print(f"\n{'='*60}")
    print(f"[权限确认] {msg}")
    print("输入 y/yes 确认，其他任意键取消：", end="", flush=True)
    try:
        ans = input().strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False

# ─── Provider-specific streaming ────────────────────────────────────────────

class _ClaudeStreamer:
    """Claude（AnthropicVertex）streaming tool use。"""

    def __init__(self, client, model: str, config: dict):
        self.client = client
        self.model = model
        self.config = config

    async def stream(
        self,
        messages: list[dict],
        system: str,
        tools_schema: list[dict],
    ) -> AsyncGenerator[dict, None]:
        """
        生成事件：
          {"type": "text_delta", "text": "..."}
          {"type": "tool_use_start", "tool_use_id": "...", "name": "..."}
          {"type": "tool_input_delta", "tool_use_id": "...", "chunk": "..."}
          {"type": "tool_use_done", "tool_use_id": "..."}
          {"type": "message_done", "stop_reason": "..."}
          {"type": "usage", "input_tokens": N, "output_tokens": N}
        """
        loop = asyncio.get_event_loop()

        def _sync_stream():
            events = []
            kw = dict(
                model=self.model,
                messages=messages,
                system=system,
                tools=tools_schema,
                max_tokens=self.config.get("max_tokens", 8192),
            )
            if self.config.get("thinking"):
                kw["thinking"] = self.config["thinking"]

            with self.client.messages.stream(**kw) as s:
                for ev in s:
                    t = ev.type
                    if t == "content_block_start":
                        cb = ev.content_block
                        if cb.type == "tool_use":
                            events.append({
                                "type": "tool_use_start",
                                "tool_use_id": cb.id,
                                "name": cb.name,
                            })
                        elif cb.type == "text":
                            pass  # text block starts
                    elif t == "content_block_delta":
                        d = ev.delta
                        if d.type == "text_delta":
                            events.append({"type": "text_delta", "text": d.text})
                        elif d.type == "input_json_delta":
                            events.append({
                                "type": "tool_input_delta",
                                "chunk": d.partial_json,
                            })
                    elif t == "content_block_stop":
                        # 判断是否是 tool_use block 结束
                        events.append({"type": "content_block_stop"})
                    elif t == "message_delta":
                        events.append({
                            "type": "message_done",
                            "stop_reason": ev.delta.stop_reason,
                        })
                    elif t == "message_start":
                        u = ev.message.usage
                        events.append({
                            "type": "usage",
                            "input_tokens": u.input_tokens,
                            "output_tokens": 0,
                        })
            return events

        events = await loop.run_in_executor(None, _sync_stream)
        for ev in events:
            yield ev

class _GeminiStreamer:
    """Gemini streaming tool use（google-genai SDK）。"""

    def __init__(self, client, model: str, config: dict):
        self.client = client
        self.model = model
        self.config = config

    async def stream(
        self,
        messages: list[dict],
        system: str,
        tools_schema: list[dict],
    ) -> AsyncGenerator[dict, None]:
        from google.genai import types as gtypes
        loop = asyncio.get_event_loop()

        def _sync_stream():
            events = []
            # 转换 messages 为 Gemini contents 格式
            contents = []
            for m in messages:
                role = "user" if m["role"] == "user" else "model"
                parts = []
                content = m.get("content", "")
                if isinstance(content, str):
                    parts.append(gtypes.Part(text=content))
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            parts.append(gtypes.Part(text=block["text"]))
                        elif block.get("type") == "tool_result":
                            # Gemini function response
                            parts.append(gtypes.Part(
                                function_response=gtypes.FunctionResponse(
                                    name=block.get("name", "tool"),
                                    response={"content": block.get("content", "")},
                                )
                            ))
                        elif block.get("type") == "tool_use":
                            parts.append(gtypes.Part(
                                function_call=gtypes.FunctionCall(
                                    name=block["name"],
                                    args=block.get("input", {}),
                                )
                            ))
                if parts:
                    contents.append(gtypes.Content(role=role, parts=parts))

            # 转换 tools
            func_decls = []
            for t in tools_schema:
                func_decls.append(gtypes.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["input_schema"],
                ))
            gemini_tools = [gtypes.Tool(function_declarations=func_decls)] if func_decls else None

            cfg = gtypes.GenerateContentConfig(
                system_instruction=system,
                tools=gemini_tools,
                max_output_tokens=self.config.get("max_tokens", 8192),
            )

            resp_stream = self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=cfg,
            )
            for chunk in resp_stream:
                for part in (chunk.candidates[0].content.parts if chunk.candidates else []):
                    if hasattr(part, "text") and part.text:
                        events.append({"type": "text_delta", "text": part.text})
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        uid = str(uuid.uuid4())[:8]
                        events.append({"type": "tool_use_start", "tool_use_id": uid, "name": fc.name})
                        events.append({"type": "tool_input_delta", "chunk": json.dumps(dict(fc.args))})
                        events.append({"type": "content_block_stop"})
            events.append({"type": "message_done", "stop_reason": "end_turn"})
            return events

        events = await loop.run_in_executor(None, _sync_stream)
        for ev in events:
            yield ev

class _GrokStreamer:
    """Grok/OpenAI-compatible streaming tool use。"""

    def __init__(self, client, model: str, config: dict):
        self.client = client
        self.model = model
        self.config = config

    async def stream(
        self,
        messages: list[dict],
        system: str,
        tools_schema: list[dict],
    ) -> AsyncGenerator[dict, None]:
        loop = asyncio.get_event_loop()

        def _sync_stream():
            events = []
            # 注入 system message
            oai_msgs = [{"role": "system", "content": system}] + messages

            # 转换 tool schema 到 OpenAI 格式
            oai_tools = []
            for t in tools_schema:
                oai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                })

            kw = dict(
                model=self.model,
                messages=oai_msgs,
                stream=True,
                max_tokens=self.config.get("max_tokens", 8192),
            )
            if oai_tools:
                kw["tools"] = oai_tools

            stream = self.client.chat.completions.create(**kw)

            # 按 index 积累 tool_calls
            tc_bufs: dict[int, dict] = {}

            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    continue
                delta = choice.delta
                if delta.content:
                    events.append({"type": "text_delta", "text": delta.content})
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tc_bufs:
                            tc_bufs[idx] = {
                                "tool_use_id": tc.id or f"tc_{idx}",
                                "name": tc.function.name or "",
                                "args_buf": "",
                            }
                            events.append({
                                "type": "tool_use_start",
                                "tool_use_id": tc_bufs[idx]["tool_use_id"],
                                "name": tc_bufs[idx]["name"],
                            })
                        if tc.function.arguments:
                            tc_bufs[idx]["args_buf"] += tc.function.arguments
                            events.append({
                                "type": "tool_input_delta",
                                "chunk": tc.function.arguments,
                            })
                if choice.finish_reason:
                    for buf in tc_bufs.values():
                        events.append({"type": "content_block_stop"})
                    events.append({
                        "type": "message_done",
                        "stop_reason": choice.finish_reason,
                    })
            return events

        events = await loop.run_in_executor(None, _sync_stream)
        for ev in events:
            yield ev

# ─── AgenticLoop ───────────────────────────────────────────────────────────

class AgenticLoop:
    """
    LLM → tool_use → result 循环，。

    支持：
    - 三种 provider 的 streaming tool_use
    - 并发安全工具的并发执行（对应 StreamingToolExecutor）
    - 危险命令确认（behavior='ask'）
    - 自动截断（max_turns）
    """

    def __init__(
        self,
        provider: str,           # 'claude' | 'gemini' | 'grok'
        client,                  # 对应 provider 的 SDK client
        model: str,
        tools: dict[str, BaseTool],
        config: dict | None = None,
        on_text: Callable[[str], None] | None = None,
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_done: Callable[[str, ToolResult], None] | None = None,
        confirm_fn: Callable[[str], bool] | None = None,
    ):
        self.provider = provider
        self.client = client
        self.model = model
        self.tools = tools
        self.config = config or {}
        self.on_text = on_text or (lambda t: None)
        self.on_tool_start = on_tool_start or (lambda n, a: None)
        self.on_tool_done = on_tool_done or (lambda n, r: None)
        self.confirm_fn = confirm_fn or _ask_user_permission

        # 构建 streamer
        if provider == "claude":
            self._streamer = _ClaudeStreamer(client, model, self.config)
        elif provider == "gemini":
            self._streamer = _GeminiStreamer(client, model, self.config)
        else:
            self._streamer = _GrokStreamer(client, model, self.config)

    def _tools_schema(self) -> list[dict]:
        return [t.to_anthropic_schema() for t in self.tools.values()]

    def _make_ctx(self, cwd: str, session_id: str) -> ToolContext:
        return ToolContext(cwd=cwd, model=self.model, session_id=session_id)

    async def _execute_tool(
        self, call: ToolCall, ctx: ToolContext
    ) -> ToolResult:
        """权限检查 + 执行单个工具。"""
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(
                content=f"未知工具：{call.name}",
                is_error=True,
                tool_use_id=call.tool_use_id,
            )

        # 校验
        vr = tool.validate(call.input)
        if not vr.ok:
            return ToolResult(
                content=f"参数错误：{vr.message}",
                is_error=True,
                tool_use_id=call.tool_use_id,
            )

        # 权限
        perm = tool.check_permission(call.input, ctx)
        if perm.behavior == "deny":
            return ToolResult(
                content=f"权限拒绝：{perm.message}",
                is_error=True,
                tool_use_id=call.tool_use_id,
            )
        if perm.behavior == "ask":
            confirmed = await asyncio.get_event_loop().run_in_executor(
                None, self.confirm_fn, perm.message
            )
            if not confirmed:
                return ToolResult(
                    content="用户取消操作。",
                    is_error=True,
                    tool_use_id=call.tool_use_id,
                )

        # 执行
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, tool.execute, call.input, ctx
            )
        except Exception as e:
            result = ToolResult(content=f"工具执行异常：{e}", is_error=True)

        result.tool_use_id = call.tool_use_id
        result = tool.truncate_result(result)
        return result

    async def _run_turn(
        self,
        messages: list[dict],
        system: str,
        ctx: ToolContext,
    ) -> tuple[list[dict], str, list[ToolCall]]:
        """
        执行一轮 LLM 调用 + tool 执行。
        返回 (new_messages_to_append, accumulated_text, tool_calls_made)。
        """
        text_buf = ""
        # 当前活跃的 tool_use 积累
        current_tools: dict[str, ToolCall] = {}   # tool_use_id → ToolCall
        current_tool_id: str | None = None

        # 已完成等待执行的工具（按 ID 顺序）
        pending_calls: list[ToolCall] = []

        # 从流式事件积累 assistant message 的 content blocks
        content_blocks: list[dict] = []
        current_text_block: str = ""

        async for ev in self._streamer.stream(messages, system, self._tools_schema()):
            etype = ev["type"]

            if etype == "text_delta":
                t = ev["text"]
                text_buf += t
                current_text_block += t
                self.on_text(t)

            elif etype == "tool_use_start":
                # 保存之前的文本 block
                if current_text_block:
                    content_blocks.append({"type": "text", "text": current_text_block})
                    current_text_block = ""

                uid = ev["tool_use_id"]
                name = ev["name"]
                tc = ToolCall(tool_use_id=uid, name=name)
                current_tools[uid] = tc
                current_tool_id = uid

                content_blocks.append({
                    "type": "tool_use",
                    "id": uid,
                    "name": name,
                    "input": {},  # 后续 finalize 填充
                })
                self.on_tool_start(name, {})

            elif etype == "tool_input_delta":
                chunk = ev.get("chunk", "")
                if current_tool_id and current_tool_id in current_tools:
                    current_tools[current_tool_id].append_json(chunk)

            elif etype == "content_block_stop":
                # tool_use block 结束 → finalize 并加入待执行队列
                if current_tool_id and current_tool_id in current_tools:
                    tc = current_tools[current_tool_id]
                    tc.finalize()
                    # 更新 content_blocks 中对应项的 input
                    for cb in content_blocks:
                        if cb.get("type") == "tool_use" and cb.get("id") == tc.tool_use_id:
                            cb["input"] = tc.input
                    pending_calls.append(tc)
                    current_tool_id = None

            elif etype == "message_done":
                if current_text_block:
                    content_blocks.append({"type": "text", "text": current_text_block})
                    current_text_block = ""

        # 构建 assistant message
        new_messages: list[dict] = []
        if content_blocks:
            new_messages.append({
                "role": "assistant",
                "content": content_blocks,
            })

        if not pending_calls:
            return new_messages, text_buf, []

        # ── 执行工具（并发安全的并发，否则串行）──────────────────────────
        results: list[ToolResult] = []

        # 分组：并发安全 vs 串行
        i = 0
        while i < len(pending_calls):
            group_concurrent: list[ToolCall] = []
            while i < len(pending_calls):
                tc = pending_calls[i]
                tool = self.tools.get(tc.name)
                safe = tool.is_concurrency_safe(tc.input) if tool else False
                if safe:
                    group_concurrent.append(tc)
                    i += 1
                else:
                    break

            if group_concurrent:
                # 并发执行
                coros = [self._execute_tool(tc, ctx) for tc in group_concurrent]
                group_results = await asyncio.gather(*coros)
                for r in group_results:
                    results.append(r)
                    self.on_tool_done(r.tool_use_id, r)
            else:
                # 串行执行下一个非安全工具
                tc = pending_calls[i]
                r = await self._execute_tool(tc, ctx)
                results.append(r)
                self.on_tool_done(r.tool_use_id, r)
                i += 1

        # 构建 tool_result user message
        tool_result_content: list[dict] = []
        for r in results:
            tool_result_content.append({
                "type": "tool_result",
                "tool_use_id": r.tool_use_id,
                "content": r.content if isinstance(r.content, str) else json.dumps(r.content),
                "is_error": r.is_error,
            })

        if tool_result_content:
            new_messages.append({
                "role": "user",
                "content": tool_result_content,
            })

        return new_messages, text_buf, pending_calls

    async def run(
        self,
        user_message: str,
        system: str,
        history: list[dict] | None = None,
        cwd: str = ".",
        session_id: str = "",
    ) -> AgenticResult:
        """
        完整的 agentic 循环入口。
        。
        """
        session_id = session_id or str(uuid.uuid4())[:8]
        ctx = self._make_ctx(cwd, session_id)

        messages: list[dict] = list(history or [])
        messages.append({"role": "user", "content": user_message})

        total_text = ""
        total_tool_calls = 0
        turn = 0

        while turn < MAX_TURNS:
            turn += 1
            logger.info(f"[AgenticLoop] turn={turn} messages={len(messages)}")

            new_msgs, text, calls = await self._run_turn(messages, system, ctx)
            messages.extend(new_msgs)
            total_text += text
            total_tool_calls += len(calls)

            if not calls:
                # 没有 tool_use → 对话结束
                break

            if turn >= MAX_TURNS:
                logger.warning(f"[AgenticLoop] 达到最大轮数 {MAX_TURNS}，强制终止")
                break

        return AgenticResult(
            final_text=total_text,
            tool_calls_made=total_tool_calls,
            turns=turn,
        )

# ─── 同步封装（供非 async 代码使用）─────────────────────────────────────

def run_agentic(
    provider: str,
    client,
    model: str,
    tools: dict[str, BaseTool],
    user_message: str,
    system: str,
    history: list[dict] | None = None,
    cwd: str = ".",
    session_id: str = "",
    config: dict | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_done: Callable[[str, ToolResult], None] | None = None,
) -> AgenticResult:
    """同步入口，内部创建 event loop 运行 AgenticLoop。"""
    loop_obj = AgenticLoop(
        provider=provider,
        client=client,
        model=model,
        tools=tools,
        config=config,
        on_text=on_text,
        on_tool_start=on_tool_start,
        on_tool_done=on_tool_done,
    )
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        loop_obj.run(user_message, system, history, cwd, session_id)
    )
