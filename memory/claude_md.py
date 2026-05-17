"""
CLAUDE.md / Project Memory — 对应 src memdir 分层记忆系统
自动加载项目级、全局级 CLAUDE.md，注入 system prompt。
AI 可主动写入 memory 文件。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("claude_md")

_CLAUDE_MD_FILENAME = "CLAUDE.md"
_GIRAFFE_MD_FILENAME = "GIRAFFE.md"
_MEMORY_SUBDIR = ".giraffe/memory"
_CLAUDE_MEMORY_SUBDIR = ".claude/memory"
_MAX_MEMORY_CHARS = 20_000   # 单个文件最大注入字符数
_MAX_TOTAL_CHARS = 50_000    # 总注入字符上限


def find_claude_md_files(cwd: str | Path) -> list[tuple[str, Path]]:
    """
    查找所有相关的 CLAUDE.md/GIRAFFE.md 文件，按优先级排序。
    返回 [(label, path), ...] 优先级从低到高（后面的覆盖前面的）。
    对应 src memdir 的分层查找逻辑。
    """
    results: list[tuple[str, Path]] = []
    cwd = Path(cwd).resolve()

    # 1. 全局：~/.giraffe/GIRAFFE.md 或 ~/.claude/CLAUDE.md
    for global_dir, names in [
        (Path.home() / ".giraffe", [_GIRAFFE_MD_FILENAME, _CLAUDE_MD_FILENAME]),
        (Path.home() / ".claude", [_CLAUDE_MD_FILENAME]),
    ]:
        for name in names:
            p = global_dir / name
            if p.exists():
                results.append(("global", p))
                break

    # 2. 逐级向上扫描（从仓库根到 cwd）
    parents = list(reversed(cwd.parents)) + [cwd]
    for parent in parents:
        for name in [_GIRAFFE_MD_FILENAME, _CLAUDE_MD_FILENAME]:
            p = parent / name
            if p.exists():
                results.append((f"project:{parent.name}", p))
                break

    # 3. 项目 memory 目录下的所有 .md 文件
    for mem_dir_name in [_MEMORY_SUBDIR, _CLAUDE_MEMORY_SUBDIR]:
        mem_dir = cwd / mem_dir_name
        if mem_dir.exists():
            for md_file in sorted(mem_dir.glob("*.md")):
                results.append((f"memory:{md_file.stem}", md_file))

    return results


def build_context_from_claude_md(cwd: str | Path) -> str:
    """
    读取所有 CLAUDE.md 文件，构建注入 system prompt 的文本。
    对应 getCachedClaudeMdContent。
    """
    files = find_claude_md_files(cwd)
    if not files:
        return ""

    sections: list[str] = []
    total_chars = 0

    for label, filepath in files:
        try:
            content = filepath.read_text(encoding="utf-8").strip()
            if not content:
                continue
            if len(content) > _MAX_MEMORY_CHARS:
                content = content[:_MAX_MEMORY_CHARS] + "\n...[截断]"
            if total_chars + len(content) > _MAX_TOTAL_CHARS:
                logger.info(f"[CLAUDE.md] 总长度超限，跳过: {filepath}")
                break
            sections.append(f"# {label} ({filepath.name})\n\n{content}")
            total_chars += len(content)
            logger.debug(f"[CLAUDE.md] 加载: {filepath} ({len(content)} 字符)")
        except Exception as e:
            logger.warning(f"[CLAUDE.md] 读取失败 {filepath}: {e}")

    if not sections:
        return ""

    header = "以下是项目相关的指令和记忆（请严格遵守）：\n\n"
    return header + "\n\n---\n\n".join(sections)


def write_memory(content: str, filename: str = "notes.md",
                 cwd: str | Path | None = None) -> Path:
    """
    将内容写入 memory 文件（AI 主动写入记忆）。
    对应 src 中 AI 写入 .claude/memory/ 的功能。
    """
    base = Path(cwd) if cwd else Path.cwd()
    mem_dir = base / _MEMORY_SUBDIR
    mem_dir.mkdir(parents=True, exist_ok=True)

    # 安全检查：防止路径穿越
    target = (mem_dir / filename).resolve()
    if not str(target).startswith(str(mem_dir.resolve())):
        raise ValueError(f"非法文件路径: {filename}")

    target.write_text(content, encoding="utf-8")
    logger.info(f"[CLAUDE.md] 写入记忆: {target}")
    return target


def append_memory(content: str, filename: str = "notes.md",
                  cwd: str | Path | None = None) -> Path:
    """向记忆文件追加内容（不覆盖）。"""
    base = Path(cwd) if cwd else Path.cwd()
    mem_dir = base / _MEMORY_SUBDIR
    mem_dir.mkdir(parents=True, exist_ok=True)
    target = (mem_dir / filename).resolve()

    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    separator = "\n\n---\n\n" if existing else ""
    target.write_text(existing + separator + content, encoding="utf-8")
    logger.info(f"[CLAUDE.md] 追加记忆: {target}")
    return target
