# Giraffe — 生产级 AI 运行时框架

Giraffe 是一个面向生产环境的高可靠 AI 应用运行时框架。

**核心特性：**
* **可靠调用**：指数退避重试、熔断器与自愈免疫，API 故障自动修复。
* **持久上下文**：多层记忆系统（内存/JSON/SQLite/向量库）与 CLAUDE.md 项目规范自动注入。
* **智能路由**：自动进行意图分类与档位判定，弹性匹配最优模型（Grok / Claude / Gemini）。
* **任务编排**：内置 DAG 任务拆解引擎，支持 Coordinator-Worker 复杂任务协作。
* **全程观测**：集成 OpenTelemetry 全链路追踪与自动统计日志。

---

## 快速安装

```bash
# 基础安装
pip install .

# 完整功能（含向量库检索与 MCP）
pip install ".[all]"

# 源码运行依赖
pip install opentelemetry-api opentelemetry-sdk fastapi uvicorn
python giraffe.py
```

---

## 快速上手

### 1. 初始化与配置
```bash
giraffe --init
```
这将在 `~/.giraffe/config.json` 生成默认配置。编辑该文件填入 API 密钥或路由规则。

**Vertex AI 免密钥认证（推荐）：**
```bash
gcloud auth application-default login
```

**极简 `config.json` 示例：**
```json
{
  "router": {
    "primary_model": {
      "provider": "vertex_ai",
      "model": "gemini-3.5-flash",
      "project": "YOUR_GCP_PROJECT"
    }
  }
}
```

### 2. 启动服务
```bash
giraffe          # 启动交互式命令行模式
giraffe --serve  # 启动 Web 服务 (REST API & WebSocket)
giraffe --quiet  # 静默启动，仅打印 WARNING 及以上级别日志
giraffe --debug  # 调试模式启动，输出全量详细日志
```

---

## 常用 CLI 命令

在交互式命令行中，你可以使用以下命令控制框架：

| 命令 | 说明 |
|------|------|
| `/model <name>` | 强制锁定当前模型（如 `/model sonnet` 或 `/model auto` 恢复） |
| `/tier <tier>` | 锁定计算档位（nano/low/medium/high/xhigh） |
| `/skills` | 列出当前所有可用技能 |
| `/<skill_name>` | 触发特定技能（如 `/analyze_repo` 分析当前代码库） |
| `/usagestats` | 查看当前会话的模型使用量与费用统计 |
| `/loglevel [level]` | 查看或动态调整日志输出级别（如 `/loglevel debug`） |
| `/health` | 执行系统健康检查 |
| `/q` 或 `/quit` | 退出交互式命令行 |

---

## 上下文与技能扩展

* **项目记忆注入**：在项目根目录下放置 `GIRAFFE.md` 或 `CLAUDE.md`，系统启动时会自动将其作为项目规范注入到 System Prompt 中。
* **自定义技能**：将编写好的技能 Markdown 文件（支持 YAML frontmatter 配置特定模型或别名）放入 `~/.giraffe/skills/` 目录，即可通过 `/技能名` 动态加载和调用。

---

## 开发与构建

```bash
# 运行全部单元测试
python -m pytest tests/ -v

# 一键编译打包为单文件可执行程序 (Windows)
python build_exe.py
```
