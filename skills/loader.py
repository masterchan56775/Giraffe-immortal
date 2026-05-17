"""
Skills 系统
基于 Markdown 文件的可扩展技能目录，支持 /slash_command 调用。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger("skills")

# 技能搜索路径（优先级从高到低）
_SKILL_SEARCH_PATHS: list[Path] = []

@dataclass
class Skill:
    """一个技能（对应一个 .md 文件或内置定义）。"""
    name: str                              # 命令名（无 /）
    description: str
    prompt: str                            # 系统提示词
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    aliases: list[str] = field(default_factory=list)
    when_to_use: str = ""
    source: str = "bundled"               # bundled | user | project
    filepath: Path | None = None
    get_prompt_fn: Callable[[str], str] | None = None   # 动态 prompt

    def get_prompt(self, args: str = "") -> str:
        if self.get_prompt_fn:
            return self.get_prompt_fn(args)
        if args:
            return f"{self.prompt}\n\n用户参数：{args}"
        return self.prompt

# ── 内置技能注册表 ────────────────────────────────────────────────────────────

_BUNDLED_SKILLS: list[Skill] = []
_SKILL_REGISTRY: dict[str, Skill] = {}   # name → Skill（已加载）

def register_bundled_skill(skill: Skill) -> None:
    """注册内置技能。"""
    _BUNDLED_SKILLS.append(skill)
    _SKILL_REGISTRY[skill.name] = skill
    for alias in skill.aliases:
        _SKILL_REGISTRY[alias] = skill
    logger.debug(f"[Skills] 注册内置技能: /{skill.name}")

def _load_bundled_skills() -> None:
    """加载所有内置技能。"""
    _BUNDLED_SKILLS.clear()
    _SKILL_REGISTRY.clear()

    # ── 分析仓库 ──
    register_bundled_skill(Skill(
        name="analyze_repo",
        description="深入分析代码仓库结构、架构和依赖关系",
        aliases=["repo", "codebase"],
        allowed_tools=["bash", "read_file", "grep", "glob"],
        when_to_use="用户想了解仓库结构或代码架构时",
        prompt="""你是一个代码库分析专家。请对当前仓库进行系统性分析：

1. **目录结构**：使用 glob/bash 列出关键目录和文件
2. **主要模块**：识别核心模块和它们的职责
3. **依赖关系**：分析模块间的依赖图
4. **技术栈**：识别使用的框架、库和工具
5. **架构模式**：总结使用的设计模式

请提供清晰的分析报告，包括架构图（用 ASCII 或 Mermaid）。""",
    ))

    # ── 代码审查 ──
    register_bundled_skill(Skill(
        name="review",
        description="审查指定文件或目录的代码质量、安全性和可维护性",
        aliases=["code_review", "cr"],
        allowed_tools=["read_file", "grep", "glob"],
        when_to_use="用户想要代码审查时",
        prompt="""你是一个严格的代码审查专家。请审查以下代码并提供：

1. **安全问题**：输入验证、注入、权限控制
2. **代码质量**：命名、复杂度、重复代码
3. **性能问题**：低效算法、不必要的 IO
4. **可维护性**：模块化、文档、测试覆盖
5. **改进建议**：具体的修改建议（附代码示例）

按严重程度（Critical/High/Medium/Low）分类问题。""",
    ))

    # ── 调试 ──
    register_bundled_skill(Skill(
        name="debug",
        description="系统性调试问题，分析日志和错误",
        aliases=["diagnose"],
        allowed_tools=["bash", "read_file", "grep"],
        when_to_use="用户遇到 bug 或错误需要调试时",
        prompt="""你是一个调试专家。请系统性地分析问题：

1. **复现**：理解问题的触发条件
2. **日志分析**：检查相关日志和错误信息
3. **假设**：列出可能的原因（按可能性排序）
4. **验证**：逐一验证假设
5. **修复**：提供具体的修复方案

使用结构化思维，不要跳过步骤。""",
    ))

    # ── 生成测试 ──
    register_bundled_skill(Skill(
        name="test",
        description="为指定代码生成完整的测试套件",
        aliases=["gen_test", "write_tests"],
        allowed_tools=["read_file", "edit_file", "write_file", "bash"],
        when_to_use="用户需要生成测试代码时",
        prompt="""你是一个测试工程师。为给定代码生成全面的测试：

1. **单元测试**：覆盖所有函数的正常路径
2. **边界测试**：空值、极值、边界条件
3. **错误测试**：异常情况和错误处理
4. **集成测试**：模块间交互（如需要）

使用符合项目风格的测试框架。确保测试可以独立运行。""",
    ))

    # ── 文档生成 ──
    register_bundled_skill(Skill(
        name="doc",
        description="为代码生成文档（README、docstrings、API 文档）",
        aliases=["docs", "document"],
        allowed_tools=["read_file", "write_file", "glob"],
        when_to_use="用户需要生成或更新文档时",
        prompt="""你是一个技术文档工程师。请生成清晰、完整的文档：

- 函数/类：添加 docstring（参数、返回值、示例）
- 模块：生成模块级 README
- API：生成接口文档（含示例请求/响应）

文档要准确、简洁，包含实用的使用示例。""",
    ))

# ── 从目录加载用户/项目技能 ──────────────────────────────────────────────────

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter。"""
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    yaml_text = content[3:end].strip()
    body = content[end + 3:].strip()
    meta: dict = {}
    for line in yaml_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            # 简单解析 list
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [v.strip().strip('"\'') for v in val[1:-1].split(",")]
            else:
                meta[key] = val.strip('"\'')
    return meta, body

def _load_skills_from_dir(skills_dir: Path, source: str) -> list[Skill]:
    """从目录加载 .md 技能文件。"""
    if not skills_dir.exists():
        return []
    skills = []
    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
            meta, prompt = _parse_frontmatter(text)
            name = meta.get("name", md_file.stem.replace("-", "_").replace(" ", "_"))
            description = meta.get("description", f"技能：{name}")
            allowed_tools = meta.get("allowed_tools", [])
            if isinstance(allowed_tools, str):
                allowed_tools = [t.strip() for t in allowed_tools.split(",")]
            skill = Skill(
                name=name,
                description=description,
                prompt=prompt,
                allowed_tools=allowed_tools,
                model=meta.get("model"),
                aliases=[a.strip() for a in meta.get("aliases", "").split(",") if a.strip()],
                when_to_use=meta.get("when_to_use", ""),
                source=source,
                filepath=md_file,
            )
            skills.append(skill)
            logger.debug(f"[Skills] 加载 {source} 技能: /{name} ({md_file.name})")
        except Exception as e:
            logger.warning(f"[Skills] 加载失败 {md_file}: {e}")
    return skills

def load_all_skills(cwd: str | Path | None = None) -> dict[str, Skill]:
    """
    加载所有技能（内置 + 用户全局 + 项目级）。
    优先级：项目级 > 用户全局 > 内置
    """
    # 内置技能
    _load_bundled_skills()
    registry = dict(_SKILL_REGISTRY)

    # 用户全局技能：~/.giraffe/skills/
    user_skills_dir = Path.home() / ".giraffe" / "skills"
    for skill in _load_skills_from_dir(user_skills_dir, "user"):
        registry[skill.name] = skill
        for alias in skill.aliases:
            registry[alias] = skill

    # 项目级技能：{cwd}/.giraffe/skills/ 或 {cwd}/.claude/skills/
    if cwd:
        for subdir in [".giraffe/skills", ".claude/skills", "skills"]:
            project_dir = Path(cwd) / subdir
            for skill in _load_skills_from_dir(project_dir, "project"):
                registry[skill.name] = skill
                for alias in skill.aliases:
                    registry[alias] = skill

    return registry

def get_skill(name: str, cwd: str | Path | None = None) -> Skill | None:
    """按名称获取技能（包含 / 前缀也可以）。"""
    name = name.lstrip("/").lower()
    registry = load_all_skills(cwd)
    return registry.get(name)

def list_skills(cwd: str | Path | None = None) -> list[Skill]:
    """返回所有可用技能列表。"""
    seen: set[str] = set()
    result: list[Skill] = []
    for skill in load_all_skills(cwd).values():
        if skill.name not in seen:
            seen.add(skill.name)
            result.append(skill)
    return sorted(result, key=lambda s: (s.source != "project", s.name))
