# -*- mode: python ; coding: utf-8 -*-
"""
giraffe.spec — PyInstaller 打包规格文件

用法：
    pyinstaller giraffe.spec
    # 或通过 build_exe.py 一键打包：
    python build_exe.py
"""

block_cipher = None

a = Analysis(
    ["giraffe_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # config.json 放在 exe 同目录，用户可编辑
        # 注意：不打包进 exe，由 build_exe.py 在 dist/ 生成一份空白模板
        # 打包 skills/ 目录（内置技能）
        ("skills/", "skills/"),
        # 打包 assets/ 目录（含图标等）
        ("assets/", "assets/"),
    ],
    hiddenimports=[
        # Google Auth
        "google.auth",
        "google.auth.transport",
        "google.auth.transport.requests",
        "google.auth.credentials",
        "google.auth.exceptions",
        "google.oauth2",
        "google.oauth2.service_account",
        "google.oauth2.credentials",
        "google.api_core",
        "google.api_core.exceptions",
        # Anthropic / Claude
        "anthropic",
        "anthropic._models",
        "anthropic.types",
        # Google GenAI
        "google.genai",
        "google.genai.types",
        # Requests / charset
        "charset_normalizer",
        "charset_normalizer.md__mypyc",
        "requests",
        "certifi",
        "urllib3",
        # OpenTelemetry（可选遥测）
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        # FastAPI / Uvicorn（REST Gateway）
        "fastapi",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # dotenv
        "dotenv",
        # JSON / dataclasses
        "dataclasses",
        "json",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "src",
        "matplotlib",
        "notebook",
        "IPython",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "wx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="giraffe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,          # UPX 压缩（需安装 upx）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # 命令行程序，保留控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r"d:\program\py\2\assets\giraffe.ico",   # 绝对路径避免相对路径问题
    onefile=True,
)
