"""
giraffe_launcher.py — Giraffe .exe 唯一入口点

PyInstaller 打包时以此文件为入口：
  1. 在所有导入前设置静默环境变量
  2. 运行配置向导（缺失时引导用户完成设置）
  3. 启动 Giraffe 主程序
"""
import os

# ── 必须在任何第三方库导入前设置 ─────────────────────────────────────────────
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

# ── 配置向导（静默检测，缺失时交互引导）────────────────────────────────────
from integration.setup_wizard import SetupWizard

SetupWizard().run_if_needed()

# ── 启动 Giraffe ─────────────────────────────────────────────────────────────
from giraffe import main

main()
