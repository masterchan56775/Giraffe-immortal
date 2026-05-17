"""
Coordinator 模式 — 完全
实现多 Worker 编排：并行 fan-out、task-notification 格式、
continue vs spawn-fresh 决策逻辑。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

logger = logging.getLogger("coordinator")

# ─── task-notification XML 格式（

TASK_NOTIFICATION_TEMPLATE = """<task-notification>
<task-id>{task_id}</task-id>
<status>{status}</status>
<summary>{summary}</summary>
<result>{result}</result>
<usage>
  <total_tokens>{total_tokens}</total_tokens>
  <tool_uses>{tool_uses}</tool_uses>
  <duration_ms>{duration_ms}</duration_ms>
</usage>
</task-notification>"""

WorkerStatus = Literal["completed", "failed", "killed"]

@dataclass
class WorkerResult:
    task_id: str
    status: WorkerStatus
    summary: str
    result: str = ""
    total_tokens: int = 0
    tool_uses: int = 0
    duration_ms: int = 0
    error: str | None = None

    def to_notification(self) -> str:
        """生成 task-notification XML，。"""
        return TASK_NOTIFICATION_TEMPLATE.format(
            task_id=self.task_id,
            status=self.status,
            summary=self.summary,
            result=self.result[:5000] if self.result else "",
            total_tokens=self.total_tokens,
            tool_uses=self.tool_uses,
            duration_ms=self.duration_ms,
        )

@dataclass
class WorkerHandle:
    task_id: str
    description: str
    prompt: str
    # 当前会话历史（用于 continue 决策）
    context_messages: list[dict] = field(default_factory=list)
    result: WorkerResult | None = None
    aborted: bool = False

def get_coordinator_system_prompt(worker_tools: list[str]) -> str:
    """
    。
    """
    tools_str = ", ".join(worker_tools) if worker_tools else "bash, read_file, edit_file, grep, glob"
    return f"""你是 Giraffe Coordinator，一个编排多个 Worker Agent 完成复杂软件工程任务的 AI 协调器。

## 1. 你的角色

你是**协调器（Coordinator）**。你的职责：
- 帮助用户实现目标
- 指派 Worker 进行调研、实现和验证代码变更
- 合成结果并与用户沟通
- 能直接回答的问题直接回答，不要委托给 Worker

你发送的每条消息都面向用户。Worker 的结果和系统通知是内部信号，不是对话对象——绝不感谢或确认它们，直接将新信息摘要给用户。

## 2. 你的工具

- **spawn_worker** — 派生一个新 Worker
- **continue_worker** — 向已有 Worker 发送后续指令（复用其上下文）
- **stop_worker** — 停止正在运行的 Worker

派生 Worker 时：
- 不要用一个 Worker 去检查另一个 Worker。Worker 完成时会主动通知你。
- 不要派 Worker 去做简单的文件读取或命令执行——给他们更高层次的任务。
- Worker prompt 必须**完全自包含**——Worker 看不到你和用户的对话历史。

## 3. Worker 结果格式

Worker 结果以 `<task-notification>` XML 送达：

```xml
<task-notification>
<task-id>{{agentId}}</task-id>
<status>completed|failed|killed</status>
<summary>{{人类可读的状态摘要}}</summary>
<result>{{agent 的最终文本响应}}</result>
<usage>
  <total_tokens>N</total_tokens>
  <tool_uses>N</tool_uses>
  <duration_ms>N</duration_ms>
</usage>
</task-notification>
```

## 4. 任务工作流

| 阶段 | 执行者 | 目的 |
|------|--------|------|
| 调研 | Workers（并行）| 调查代码库、理解问题 |
| 合成 | **你**（协调器）| 阅读调研结果，制定实现规范 |
| 实现 | Workers | 按规范进行有针对性的变更，提交 |
| 验证 | Workers | 测试变更是否有效 |

**并行是你的超能力。** 独立的 Worker 尽量并发启动。

## 5. 撰写 Worker Prompt 的关键原则

**Worker 看不到你的对话历史。** 每个 prompt 必须包含 Worker 所需的一切：
- 具体的文件路径、行号、错误信息
- 明确说明"完成"的标准
- 不要写"根据你的发现..."——自己合成后再给指令

**continue vs spawn-fresh 决策**：
- 调研覆盖了需要编辑的文件 → **continue**（Worker 已有上下文）
- 调研范围广但实现范围窄 → **spawn-fresh**（避免拖累无关上下文）
- 修复失败或扩展近期工作 → **continue**（Worker 有错误上下文）
- 验证另一个 Worker 的代码 → **spawn-fresh**（新鲜视角）

Worker 可用工具：{tools_str}"""

def get_coordinator_user_context(worker_tools: list[str]) -> dict[str, str]:
    """
    。
    注入 Coordinator 专用的用户上下文。
    """
    tools_str = ", ".join(worker_tools)
    return {
        "workerToolsContext": f"Workers 通过 spawn_worker 工具可使用以下工具：{tools_str}"
    }

# ─── Worker 执行引擎 ──────────────────────────────────────────────────────

class WorkerExecutor:
    """
    执行单个 Worker 任务。
    。
    """

    def __init__(
        self,
        call_llm: Callable,   # fn(messages, system, tools) -> str (同步)
        tools: dict,
        system_prompt: str = "",
    ):
        self.call_llm = call_llm
        self.tools = tools
        self.system_prompt = system_prompt

    async def run(self, handle: WorkerHandle) -> WorkerResult:
        """
        运行一个 Worker，返回 WorkerResult。
        Worker 内部也走 AgenticLoop（如果有工具的话）。
        """
        start_ms = int(time.time() * 1000)
        task_id = handle.task_id

        logger.info(f"[Worker:{task_id}] 开始执行: {handle.description}")

        try:
            # 构建 Worker messages
            messages = list(handle.context_messages)
            if not messages or messages[-1]["role"] != "user":
                messages.append({"role": "user", "content": handle.prompt})

            # 调用 LLM（支持 agentic loop 或直接调用）
            loop = asyncio.get_event_loop()
            result_text = await loop.run_in_executor(
                None, self.call_llm, messages, self.system_prompt
            )

            duration_ms = int(time.time() * 1000) - start_ms
            logger.info(f"[Worker:{task_id}] 完成 ({duration_ms}ms)")

            return WorkerResult(
                task_id=task_id,
                status="completed",
                summary=f'Worker "{handle.description}" 完成',
                result=result_text,
                duration_ms=duration_ms,
            )

        except asyncio.CancelledError:
            return WorkerResult(
                task_id=task_id,
                status="killed",
                summary=f'Worker "{handle.description}" 已停止',
                duration_ms=int(time.time() * 1000) - start_ms,
            )
        except Exception as e:
            logger.error(f"[Worker:{task_id}] 失败: {e}")
            return WorkerResult(
                task_id=task_id,
                status="failed",
                summary=f'Worker "{handle.description}" 失败: {e}',
                error=str(e),
                duration_ms=int(time.time() * 1000) - start_ms,
            )

# ─── CoordinatorSession ───────────────────────────────────────────────────

class CoordinatorSession:
    """
    管理一次 Coordinator 会话中的所有 Worker。
    。

    支持：
    - spawn_worker：派生新 Worker（立即异步执行）
    - continue_worker：向已有 Worker 追加指令（复用上下文）
    - stop_worker：取消 Worker
    - 通知合并：将 task-notification 注入 Coordinator 的 messages
    """

    def __init__(
        self,
        call_llm: Callable,
        tools: dict,
        worker_system_prompt: str = "",
        on_notification: Callable[[str, WorkerResult], None] | None = None,
    ):
        self.call_llm = call_llm
        self.tools = tools
        self.worker_system_prompt = worker_system_prompt
        self.on_notification = on_notification

        self._handles: dict[str, WorkerHandle] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, WorkerResult] = {}
        self._notification_queue: asyncio.Queue[WorkerResult] = asyncio.Queue()

        self._executor = WorkerExecutor(call_llm, tools, worker_system_prompt)

    def spawn_worker(
        self,
        description: str,
        prompt: str,
        initial_context: list[dict] | None = None,
    ) -> str:
        """
        派生新 Worker，立即开始执行（后台 task）。
        返回 task_id 供后续 continue/stop 使用。

        。
        """
        task_id = f"worker-{str(uuid.uuid4())[:6]}"
        handle = WorkerHandle(
            task_id=task_id,
            description=description,
            prompt=prompt,
            context_messages=list(initial_context or []),
        )
        self._handles[task_id] = handle

        async def _run_and_notify():
            result = await self._executor.run(handle)
            handle.result = result
            self._results[task_id] = result
            await self._notification_queue.put(result)
            if self.on_notification:
                self.on_notification(task_id, result)

        task = asyncio.ensure_future(_run_and_notify())
        self._tasks[task_id] = task
        logger.info(f"[Coordinator] 派生 Worker: {task_id} ({description})")
        return task_id

    def continue_worker(
        self,
        task_id: str,
        message: str,
    ) -> str:
        """
        向已有 Worker 发送后续指令（复用其上下文）。
        。

        决策原则：
        - 调研覆盖了要编辑的文件 → continue（保留 Worker 上下文）
        - 修复失败或扩展工作 → continue
        """
        handle = self._handles.get(task_id)
        if not handle:
            logger.warning(f"[Coordinator] continue_worker: 未知 task_id={task_id}")
            return task_id

        # 取消旧 task（如果还在运行）
        old_task = self._tasks.get(task_id)
        if old_task and not old_task.done():
            old_task.cancel()

        # 构建新 prompt（保留原有上下文 + 新指令）
        prev_result = self._results.get(task_id)
        context = list(handle.context_messages)
        if prev_result and prev_result.result:
            context.append({"role": "assistant", "content": prev_result.result})
        context.append({"role": "user", "content": message})

        new_handle = WorkerHandle(
            task_id=task_id,
            description=handle.description,
            prompt=message,
            context_messages=context,
        )
        self._handles[task_id] = new_handle

        async def _run_and_notify():
            result = await self._executor.run(new_handle)
            new_handle.result = result
            self._results[task_id] = result
            await self._notification_queue.put(result)
            if self.on_notification:
                self.on_notification(task_id, result)

        task = asyncio.ensure_future(_run_and_notify())
        self._tasks[task_id] = task
        logger.info(f"[Coordinator] 继续 Worker: {task_id}")
        return task_id

    def stop_worker(self, task_id: str) -> bool:
        """停止 Worker。对应 TaskStopTool。"""
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"[Coordinator] 停止 Worker: {task_id}")
            return True
        return False

    async def collect_notifications(self, timeout: float = 0.1) -> list[WorkerResult]:
        """
        收集已完成的 Worker 通知（非阻塞）。
        调用方（Coordinator LLM loop）在每轮开始前调用。
        """
        results = []
        try:
            while True:
                r = self._notification_queue.get_nowait()
                results.append(r)
        except asyncio.QueueEmpty:
            pass
        return results

    async def wait_all(self) -> list[WorkerResult]:
        """等待所有 Worker 完成。"""
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        return list(self._results.values())

    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

# ─── 顶层入口：run_coordinator ────────────────────────────────────────────

async def run_coordinator(
    user_request: str,
    call_coordinator_llm: Callable[[list[dict], str], str],
    call_worker_llm: Callable[[list[dict], str], str],
    tools: dict,
    max_coordinator_turns: int = 20,
    on_coordinator_text: Callable[[str], None] | None = None,
    on_worker_spawn: Callable[[str, str], None] | None = None,
    on_worker_done: Callable[[str, WorkerResult], None] | None = None,
) -> str:
    """
    完整的 Coordinator 执行流程。
    。

    Args:
        user_request: 用户的原始请求
        call_coordinator_llm: (messages, system) -> response_text（协调器模型）
        call_worker_llm: (messages, system) -> response_text（Worker 模型）
        tools: 工具注册表
        max_coordinator_turns: 最大协调轮数
        on_coordinator_text: 协调器输出回调
        on_worker_spawn: Worker 派生回调 (task_id, description)
        on_worker_done: Worker 完成回调 (task_id, result)
    """
    worker_tool_names = list(tools.keys())
    coordinator_system = get_coordinator_system_prompt(worker_tool_names)

    session = CoordinatorSession(
        call_llm=call_worker_llm,
        tools=tools,
        on_notification=lambda tid, r: on_worker_done(tid, r) if on_worker_done else None,
    )

    messages: list[dict] = [{"role": "user", "content": user_request}]
    final_response = ""

    for turn in range(max_coordinator_turns):
        logger.info(f"[Coordinator] turn={turn+1}")

        # 收集已完成的 Worker 通知，注入为 user message
        notifications = await session.collect_notifications()
        for notif in notifications:
            notification_msg = notif.to_notification()
            messages.append({"role": "user", "content": notification_msg})
            logger.info(f"[Coordinator] 收到 Worker 通知: {notif.task_id} ({notif.status})")

        # 调用 Coordinator LLM
        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None, call_coordinator_llm, messages, coordinator_system
            )
        except Exception as e:
            logger.error(f"[Coordinator] LLM 调用失败: {e}")
            break

        if on_coordinator_text:
            on_coordinator_text(response)

        messages.append({"role": "assistant", "content": response})
        final_response = response

        # 解析 Coordinator 的 "工具调用"（基于文本指令解析，简化版）
        # 真实实现中 Coordinator 也应走 tool_use loop
        spawned = _parse_and_execute_coordinator_tools(
            response, session, on_worker_spawn
        )

        # 如果没有 spawn/continue/stop 且没有 pending workers → 结束
        if not spawned and session.active_count() == 0:
            # 等待最后一批 Worker 通知
            await asyncio.sleep(0.1)
            remaining = await session.collect_notifications()
            if not remaining:
                break
            for notif in remaining:
                messages.append({"role": "user", "content": notif.to_notification()})

        # 如果有 active Workers，等待至少一个完成再继续
        if session.active_count() > 0:
            # 轮询等待
            while session.active_count() > 0:
                await asyncio.sleep(0.5)
                notifications = await session.collect_notifications()
                if notifications:
                    for notif in notifications:
                        messages.append({
                            "role": "user",
                            "content": notif.to_notification(),
                        })
                    break

    return final_response

def _parse_and_execute_coordinator_tools(
    response: str,
    session: CoordinatorSession,
    on_spawn: Callable[[str, str], None] | None,
) -> bool:
    """
    简单解析 Coordinator 响应中的工具调用指令（文本模式）。
    真实实现应通过 tool_use 解析——此处为快速集成版本。
    """
    spawned = False
    # 解析 spawn_worker(description="...", prompt="...")
    import re
    spawn_pattern = re.compile(
        r'spawn_worker\s*\(\s*description\s*=\s*["\']([^"\']+)["\'],\s*'
        r'(?:subagent_type\s*=\s*["\'][^"\']+["\'],\s*)?'
        r'prompt\s*=\s*["\']([^"\']+)["\']',
        re.DOTALL,
    )
    for m in spawn_pattern.finditer(response):
        desc = m.group(1)
        prompt = m.group(2)
        task_id = session.spawn_worker(description=desc, prompt=prompt)
        if on_spawn:
            on_spawn(task_id, desc)
        spawned = True

    return spawned

# ─── 同步包装 ──────────────────────────────────────────────────────────────

def run_coordinator_sync(
    user_request: str,
    call_coordinator_llm: Callable,
    call_worker_llm: Callable,
    tools: dict,
    **kwargs,
) -> str:
    """同步入口。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        run_coordinator(
            user_request=user_request,
            call_coordinator_llm=call_coordinator_llm,
            call_worker_llm=call_worker_llm,
            tools=tools,
            **kwargs,
        )
    )
