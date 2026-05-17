"""
Shell 命令只读/安全性验证 — 
提供精确的 git 子命令白名单 + 外部命令白名单，用于 BashTool 并发安全判断。
"""
from __future__ import annotations
import re
import shlex
from typing import Literal

FlagArgType = Literal["none", "number", "string", "char"]

# ── git 子命令只读白名单 ──────────────────────────────────────────────────────

_GIT_SAFE_FLAGS_COMMON = {
    "--color": "none", "--no-color": "none",
    "--stat": "none", "--numstat": "none", "--shortstat": "none",
    "--name-only": "none", "--name-status": "none",
    "--oneline": "none", "--graph": "none", "--decorate": "none",
    "--all": "none", "--branches": "none", "--tags": "none", "--remotes": "none",
    "--since": "string", "--after": "string", "--until": "string", "--before": "string",
    "--max-count": "number", "-n": "number",
    "--author": "string", "--committer": "string", "--grep": "string",
}

GIT_READ_ONLY_COMMANDS: dict[str, set[str]] = {
    "git diff": set(_GIT_SAFE_FLAGS_COMMON) | {
        "--cached", "--staged", "--patch", "-p", "-u", "-s", "--no-patch",
        "--word-diff", "--no-renames", "--find-renames", "--diff-algorithm",
        "--ignore-space-change", "--ignore-all-space", "--ignore-blank-lines",
        "--histogram", "--patience", "--minimal", "--exit-code", "--quiet",
        "--relative", "--diff-filter", "-R", "-M", "-C", "-B", "-D",
        "-S", "-G",  # require args but mark safe
    },
    "git log": set(_GIT_SAFE_FLAGS_COMMON) | {
        "--abbrev-commit", "--reverse", "--first-parent", "--merges", "--no-merges",
        "--walk-reflogs", "--full-history", "--dense", "--sparse",
        "--skip", "-p", "--patch", "--no-patch", "--ancestry-path",
        "--follow", "--source", "--simplify-merges",
        "--format", "--pretty", "--encoding", "--notes",
    },
    "git show": set(_GIT_SAFE_FLAGS_COMMON) | {
        "--format", "--pretty", "--encoding", "-p", "--no-patch",
        "--stat", "--expand-tabs", "--raw",
    },
    "git status": {"--short", "-s", "--branch", "-b", "--porcelain",
                   "--untracked-files", "-u", "--ignored", "--ahead-behind",
                   "--no-ahead-behind", "--renames", "--no-renames"},
    "git blame": {"--line-porcelain", "--porcelain", "--show-stats",
                  "--incremental", "-M", "-C", "--date", "-w",
                  "--abbrev", "-L", "--reverse", "--first-parent"},
    "git branch": {"--list", "-l", "-r", "--remotes", "-a", "--all",
                   "--verbose", "-v", "--contains", "--merged", "--no-merged",
                   "--sort", "--format", "--column"},
    "git stash list": {"--oneline", "--stat", "--format", "--pretty"},
    "git tag": {"-l", "--list", "--sort", "--contains", "--format", "--merged"},
    "git remote": {"-v", "--verbose", "show", "get-url"},
    "git fetch": {"--dry-run", "--verbose", "-v", "--all", "--prune",
                  "--prune-tags", "--tags", "--depth", "--no-tags"},
    "git ls-files": {"-v", "--cached", "-c", "--others", "-o", "--ignored", "-i",
                     "--modified", "-m", "--deleted", "-d", "--exclude"},
    "git cat-file": {"-t", "-s", "-e", "-p", "--batch", "--batch-check"},
    "git rev-parse": {"--abbrev-ref", "--symbolic", "--verify",
                      "--short", "--is-inside-work-tree", "--git-dir", "--show-toplevel"},
    "git describe": {"--tags", "--always", "--dirty", "--abbrev",
                     "--long", "--candidates", "--match", "--first-parent"},
    "git shortlog": {"-s", "--summary", "-n", "--numbered",
                     "--email", "-e", "-c", "--committer"},
    "git reflog": set(_GIT_SAFE_FLAGS_COMMON) | {"--all", "--date", "--format"},
    "git worktree list": {"--porcelain", "-v"},
    "git config": {"--list", "-l", "--get", "--get-all", "--global",
                   "--local", "--system", "--type", "--no-includes"},
}

# ── 外部命令只读白名单 ────────────────────────────────────────────────────────

EXTERNAL_READ_ONLY_COMMANDS: dict[str, set[str]] = {
    "cat":    {"-n", "-A", "-b", "-e", "-s", "-T", "-v", "--number",
               "--show-all", "--squeeze-blank"},
    "ls":     {"-l", "-a", "-h", "-r", "-t", "-S", "-R", "--color",
               "--sort", "-1", "-d", "-F", "-i", "-s", "-n", "--all",
               "--human-readable", "--reverse", "--time", "--size",
               "--format", "--group-directories-first"},
    "pwd":    {"-P", "-L", "--physical", "--logical"},
    "echo":   {"-n", "-e"},
    "head":   {"-n", "-c", "--lines", "--bytes", "-q", "--quiet", "-v"},
    "tail":   {"-n", "-c", "-f", "--follow", "--lines", "--bytes",
               "-q", "--quiet", "--retry", "--max-unchanged-stats",
               "--pid", "-s", "--sleep-interval"},
    "wc":     {"-l", "-w", "-c", "-m", "-L", "--lines", "--words",
               "--bytes", "--chars", "--max-line-length"},
    "grep":   {"-r", "-R", "--recursive", "-l", "--files-with-matches",
               "-n", "--line-number", "-c", "--count", "-i", "--ignore-case",
               "-v", "--invert-match", "-E", "--extended-regexp",
               "-F", "--fixed-strings", "-P", "--perl-regexp",
               "-o", "--only-matching", "--color", "-A", "-B", "-C",
               "--context", "--include", "--exclude", "--exclude-dir",
               "-w", "--word-regexp", "-x", "--line-regexp", "--max-count",
               "--no-filename", "-H", "--with-filename", "-h"},
    "find":   {"-name", "-type", "-size", "-mtime", "-atime", "-ctime",
               "-maxdepth", "-mindepth", "-path", "-prune", "-print",
               "-ls", "-exec", "-iname", "-newer", "-not", "!",
               "-o", "-or", "-and", "-a", "-perm"},
    "sort":   {"-r", "-n", "-k", "-t", "-u", "-f", "--reverse",
               "--numeric-sort", "--key", "--field-separator", "--unique",
               "--ignore-case", "--human-numeric-sort", "-h",
               "--version-sort", "-V"},
    "uniq":   {"-c", "-d", "-u", "-i", "-f", "--count", "--repeated",
               "--unique", "--ignore-case", "--skip-fields"},
    "cut":    {"-d", "-f", "-c", "--delimiter", "--fields", "--characters",
               "--complement", "--output-delimiter"},
    "awk":    {"-F", "-v", "-f"},
    "sed":    {"-n", "-e", "-E", "--quiet", "--silent", "-r",
               "--regexp-extended", "--expression", "--file"},
    "diff":   {"-u", "-c", "-y", "-r", "-i", "-w", "-b", "-q",
               "--unified", "--context", "--side-by-side", "--recursive",
               "--ignore-case", "--ignore-all-space", "--brief",
               "--ignore-trailing-space", "--color"},
    "which":  {"--all", "-a"},
    "where":  {},
    "type":   {"-a", "-f", "-P", "-t"},
    "env":    {},
    "printenv": {},
    "whoami": {},
    "id":     {"-u", "-g", "-G", "-n", "-r"},
    "uname":  {"-a", "-s", "-n", "-r", "-v", "-m", "-p", "-i", "-o",
               "--all", "--kernel-name", "--nodename", "--kernel-release",
               "--kernel-version", "--machine", "--processor", "--hardware-platform",
               "--operating-system"},
    "date":   {"-u", "-R", "-r", "-I", "+"},
    "df":     {"-h", "-H", "-k", "-m", "-T", "-i", "--human-readable",
               "--portability", "--inodes", "--print-type"},
    "du":     {"-h", "-s", "-a", "-c", "-d", "--max-depth", "--human-readable",
               "--summarize", "--all", "--total"},
    "ps":     {"-e", "-f", "-u", "-a", "-x", "-l", "-p", "--forest",
               "--sort", "-o", "--format", "aux", "auxf"},
    "top":    {"-b", "-n", "-d", "-u", "-p"},
    "uptime": {},
    "free":   {"-h", "-b", "-k", "-m", "-g", "--human", "--giga"},
    "lsof":   {"-i", "-n", "-p", "-u", "+D"},
    "netstat": {"-a", "-n", "-t", "-u", "-l", "-p", "-r", "-s"},
    "ss":     {"-a", "-n", "-t", "-u", "-l", "-p", "-r", "-s", "-4", "-6"},
    "curl":   {"--head", "-I", "-s", "--silent", "-o", "--output",
               "-O", "--remote-name", "-L", "--location", "-A", "--user-agent",
               "-H", "--header", "--max-time", "-m", "--connect-timeout",
               "--retry", "-k", "--insecure", "--compressed",
               "-v", "--verbose", "-f", "--fail", "--url", "-u"},
    "wget":   {"-q", "--quiet", "-v", "--verbose", "-O", "--output-document",
               "--spider", "--no-check-certificate", "--timeout",
               "--tries", "--user-agent", "-U"},
    "pip":    {"list", "show", "freeze", "check"},
    "npm":    {"list", "ls", "info", "view", "outdated", "audit"},
    "yarn":   {"info", "list", "outdated", "why", "check"},
    "tree":   {"-a", "-d", "-l", "-f", "-i", "-s", "-h", "-p",
               "-L", "--filelimit", "--dirsfirst", "-C",
               "--noreport", "-I", "-P"},
    "file":   {"-b", "-i", "-L", "-z", "--brief", "--mime", "--dereference",
               "--uncompress"},
    "stat":   {"-c", "--format", "-f", "--file-system", "-L",
               "--dereference", "--printf"},
    "md5sum": {"--check", "-c", "--quiet", "--status"},
    "sha256sum": {"--check", "-c", "--quiet", "--status"},
    "xxd":    {"-l", "-s", "-c", "-g", "-u"},
    "strings": {"-a", "-n", "-t", "--radix", "--bytes"},
    "jq":     {"-r", "-c", "-e", "-s", "--raw-output", "--compact-output",
               "--exit-status", "--slurp", "--sort-keys", "--tab",
               "--indent", "--arg", "--argjson", "--rawfile"},
    "yq":     {"-r", "-e", "--rawfile", "--exit-status"},
    "python": {"-c", "-m"},   # 读取用途
    "python3": {"-c", "-m"},
    "node":   {"-e", "--eval", "-p", "--print"},
    "ruby":   {"-e"},
    "perl":   {"-e", "-n", "-p", "-l", "-a", "-F"},
}

# 危险命令前缀（不论参数，始终需要确认）
DANGEROUS_EXEC_PATTERNS = [
    "eval", "exec", "source", ".", "bash -c", "sh -c",
    "zsh -c", "fish -c", "xargs",
    "python -c", "python3 -c", "node -e", "ruby -e", "perl -e",
    "sudo", "su ", "doas",
]

def _tokenize(command: str) -> list[str]:
    """简单 token 化（处理引号）。"""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()

def is_read_only(command: str) -> bool:
    """
    判断命令是否为只读/并发安全。

    """
    cmd = command.strip()

    # git 命令
    if cmd.startswith("git "):
        for subcmd, safe_flags in GIT_READ_ONLY_COMMANDS.items():
            if cmd.startswith(subcmd):
                remaining = cmd[len(subcmd):]
                tokens = _tokenize(remaining)
                for tok in tokens:
                    if not tok.startswith("-"):
                        # 非 flag token（文件名、commit hash、branch 名）→ 允许
                        continue
                    # -<number> 等价于 -n <number>，git log 支持
                    if re.match(r'^-\d+$', tok):
                        continue
                    # 允许 --flag=value 中的 --flag 部分
                    flag = tok.split("=")[0]
                    if flag not in safe_flags:
                        return False
                return True
        return False

    # 外部命令
    tokens = _tokenize(cmd)
    if not tokens:
        return False
    base_cmd = tokens[0]

    if base_cmd not in EXTERNAL_READ_ONLY_COMMANDS:
        return False

    safe = EXTERNAL_READ_ONLY_COMMANDS[base_cmd]
    for tok in tokens[1:]:
        if tok.startswith("-"):
            flag = tok.split("=")[0]
            if flag not in safe:
                return False
    return True

def classify_command(command: str) -> tuple[str, str]:
    """
    分类命令安全级别。
    返回 ('safe', '') | ('ask', reason) | ('deny', reason)

    """
    cmd = command.strip()

    # 检查危险执行模式（deny）
    for pat in DANGEROUS_EXEC_PATTERNS[:6]:  # eval/exec/source
        if cmd.split()[0] == pat.split()[0] if " " not in pat else cmd.startswith(pat):
            return "deny", f"命令含代码执行入口: {pat}"

    # 检查只读
    if is_read_only(cmd):
        return "safe", ""

    # 管道链：每段分别检查
    if "|" in cmd:
        parts = [p.strip() for p in cmd.split("|")]
        for part in parts:
            level, reason = classify_command(part)
            if level == "deny":
                return "deny", reason
        return "ask", "管道命令含写入操作"

    # 其余默认需要确认
    return "ask", "未知命令，需要确认"
