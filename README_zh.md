# Giraffe — 生产级 AI 运行时框架

DAG 执行引擎 | 多智能体 Swarm | 全链路可观测性 | 4级记忆 | 故障自愈 | 双认证引擎

## 概述

Giraffe 是一个面向生产环境的 AI 运行时框架。它接管了 LLM API 调用的完整生命周期——从用户输入、路由决策、任务执行到结果返回——并内置了可靠性保障、上下文持久化和运行状态可观测能力。

**核心能力：**

- **双认证引擎**：同时支持 Google Cloud ADC（Vertex AI 无秘钥认证）和兼容 OpenAI 协议的标准 API Key 认证。系统根据配置自动判断使用哪种模式。
- **4级记忆系统**：短期记忆（内存 LRU）、事实记忆（JSON 结构化提取）、长期记忆（SQLite 全量存档）、语义记忆（ChromaDB 向量检索）。上下文跨会话保留，支持关键词和语义相似度检索。
- **DAG 执行引擎**：复杂任务被分解为有向无环图中的多个节点。每个节点执行后自动保存检查点到 SQLite，支持断点续跑和任意步骤回滚。
- **多智能体 Swarm**：高复杂度任务自动触发多角色协作流程（架构师、程序员、审查员），多轮迭代直至达成共识。
- **故障自愈**：自动处理超时、限流、模型不可用、上下文溢出等异常，通过重试、模型降级、上下文压缩等策略恢复执行。
- **全链路可观测**：OpenTelemetry 追踪所有关键路径的耗时与调用链。EventBus 通过 SSE 和 WebSocket 实时推送内部状态。

## 安装

```bash
# 基础安装
pip install .

# 包含向量检索
pip install ".[vector]"

# 包含 MCP 协议
pip install ".[mcp]"

# 全量依赖
pip install ".[all]"
```

或从源码运行：

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install fastapi uvicorn python-multipart

# 可选（缺失时自动降级）
pip install chromadb sentence-transformers   # 向量检索
pip install mcp                              # MCP 协议

python giraffe.py
```

## 快速开始

### 1. 初始化

```bash
giraffe --init
```

在 `~/.giraffe/` 目录生成默认配置文件。

### 2. 配置认证

**方式 A — Google Cloud ADC 认证（推荐用于 Vertex AI）：**

```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "project": "你的项目ID",
      "location": "us-central1"
    }
  }
}
```

启动前执行 `gcloud auth application-default login` 完成本地认证，无需填写 API Key。

**方式 B — 兼容 OpenAI 协议的 API Key 认证：**

```json
{
  "router": {
    "primary_model": {
      "provider": "openai",
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-你的密钥"
    }
  }
}
```

当配置中存在有效的 `api_key` 时，系统自动切换为标准 HTTP 请求模式。

配置文件查找顺序：`--config 指定路径` > `当前目录 config.json` > `~/.giraffe/config.json` > 内置默认值。

### 3. 启动

```bash
# 交互模式
giraffe

# Web 服务模式（REST / WebSocket / SSE）
giraffe --serve

# 路由测试（不产生实际 API 调用）
giraffe --test-route "设计一个高并发系统架构"

# 健康检查
giraffe --health
```

## 系统架构

```
用户输入 / HTTP / WebSocket
        ↓
┌──────────────────────────────────────────────┐
│  可观测层 (OpenTelemetry + OTLP)             │
│  事件总线 → SSE / WebSocket 实时推送         │
└──────────────────┬───────────────────────────┘
                   ↓
① 配置中心      Config / AppState / CreditMonitor
                   ↓
② 路由引擎      关键词匹配(<1ms) + LLM 深度判定(~200ms)
                5档准入 × 模型矩阵
                   ↓
         ┌────────┴─────────┐
         ↓                  ↓
③-A 执行管道           ③-B Swarm 协作
    DAG 图引擎              架构师 → 程序员 → 审查员
    断点续跑                多轮迭代
         └────────┬─────────┘
                  ↓
④ 4级记忆      短期 / 事实 / 长期 / 语义
                  ↓
⑤ 故障自愈      重试 / 降级 / 压缩 / 兜底
                  ↓
⑥ 安全控制      三级审批 + 护栏 + Token 预算
                  ↓
⑦ 集成层        网关 / MCP / Web 服务 / 多模态
                  ↓
⑧ 执行器        熔断器 / 缓存 / 任务分解 / 并行执行
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/health` | 系统健康诊断（存储、路由、管道、Token 预算） |
| `/memory` | 4级记忆系统状态 |
| `/route <消息>` | 测试路由决策（不调用 API） |
| `/stats` | 管道运行统计（调用次数、成功率、缓存命中） |
| `/evolve` | 触发故障恢复策略优化 |
| `/help` | 查看全部命令 |

## API 端点（`--serve` 模式）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送消息，返回 SSE 流。支持 multipart 图片上传 |
| `/api/events` | GET | 订阅实时事件流 |
| `/ws/chat` | WS | 全双工 WebSocket，支持 token 级流式响应 |
| `/api/health` | GET | 系统健康状态 JSON |

## 测试

```bash
# 运行全部 429 个测试用例
python -m pytest tests/ -v
```
