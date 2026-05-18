"""
build_exe.py — Giraffe 一键打包脚本

产物（输出到 release/ 目录）：
  Giraffe_Portable_1.9.5_windows_x64.zip   — 解压即用便携版
  Giraffe_Setup_1.9.5_windows_x64.exe      — Windows 安装向导（需 Inno Setup）

步骤：
  1. 安装必要工具（pyinstaller、pillow）
  2. 将 assets/giraffe.png 转换为多尺寸 .ico
  3. PyInstaller 打包生成 giraffe.exe
  4. 打包便携 zip（giraffe.exe + config.json + README.md）
  5. 生成 Inno Setup 脚本并编译安装包（自动安装 Inno Setup 如未找到）
  6. 打印所有产物摘要
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR   = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
DIST_DIR   = BASE_DIR / "dist"
RELEASE_DIR = BASE_DIR / "release"
PNG_SRC    = ASSETS_DIR / "giraffe.png"
ICO_DEST   = ASSETS_DIR / "giraffe.ico"

VERSION    = "1.9.5"
APP_NAME   = "Giraffe"
ARCH       = "windows_x64"
EXE_NAME   = f"{APP_NAME}_Setup_{VERSION}_{ARCH}.exe"
ZIP_NAME   = f"{APP_NAME}_Portable_{VERSION}_{ARCH}.zip"
ISS_PATH   = BASE_DIR / "giraffe_setup.iss"

# Inno Setup 候选路径（winget 默认装在 AppData\Local\Programs）
ISCC_CANDIDATES = [
    Path(r"C:\Users") / os.environ.get("USERNAME", "") / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
]
INNO_INSTALLER_URL = (
    "https://files.jrsoftware.org/is/6/innosetup-6.3.3.exe"
)

# ─── 1. 确保依赖已安装 ────────────────────────────────────────────────────────
def ensure_deps() -> None:
    for pkg in ("pyinstaller", "pillow"):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[Build] Installing {pkg}...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                check=True
            )

# ─── 2. PNG → ICO ────────────────────────────────────────────────────────────
def build_ico() -> None:
    if not PNG_SRC.exists():
        print(f"[Build] Warning: {PNG_SRC} not found, skipping icon.")
        return
    from PIL import Image
    img = Image.open(PNG_SRC).convert("RGBA")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
    imgs[0].save(ICO_DEST, format="ICO", sizes=sizes, append_images=imgs[1:])
    print(f"[Build] Icon generated: {ICO_DEST}")

# ─── 3. PyInstaller 打包 ──────────────────────────────────────────────────────
def run_pyinstaller() -> None:
    print("[Build] Running PyInstaller...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "giraffe.spec", "--clean", "--noconfirm"],
        cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        print("[Build] ✗ PyInstaller failed.")
        sys.exit(1)
    print("[Build] ✓ PyInstaller succeeded.")

# ─── 4. 便携版 zip ────────────────────────────────────────────────────────────
def build_portable_zip() -> None:
    RELEASE_DIR.mkdir(exist_ok=True)
    exe_src   = DIST_DIR / "giraffe.exe"
    cfg_src   = DIST_DIR / "config.json"
    readme    = BASE_DIR / "README.md"
    zip_dest  = RELEASE_DIR / ZIP_NAME

    if not exe_src.exists():
        print("[Build] ✗ giraffe.exe not found, skipping portable zip.")
        return

    # 生成 dist/config.json 模板（若不存在）
    if not cfg_src.exists():
        _place_config_template()

    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_src,  "giraffe.exe")
        zf.write(cfg_src,  "config.json")
        if readme.exists():
            zf.write(readme, "README.md")

    size_mb = zip_dest.stat().st_size / (1024 * 1024)
    print(f"[Build] ✓ Portable zip: {zip_dest.name}  ({size_mb:.1f} MB)")

# ─── 5. 安装包（Inno Setup） ──────────────────────────────────────────────────
def find_iscc() -> Path | None:
    for p in ISCC_CANDIDATES:
        if p.exists():
            return p
    return None

def install_inno_setup() -> Path | None:
    """静默安装 Inno Setup，返回 ISCC.exe 路径（或 None 若失败）。"""
    tmp = BASE_DIR / "_inno_installer.exe"
    print(f"[Build] Downloading Inno Setup from {INNO_INSTALLER_URL} ...")
    try:
        urllib.request.urlretrieve(INNO_INSTALLER_URL, tmp)
    except Exception as e:
        print(f"[Build] ✗ Download failed: {e}")
        return None

    print("[Build] Installing Inno Setup (silent)...")
    result = subprocess.run(
        [str(tmp), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        timeout=120,
    )
    tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"[Build] ✗ Inno Setup install failed (code {result.returncode}).")
        return None

    return find_iscc()

def write_iss_script() -> None:
    """生成 Inno Setup 脚本。"""
    exe_path = DIST_DIR / "giraffe.exe"
    cfg_path = DIST_DIR / "config.json"
    ico_path = ICO_DEST
    readme   = BASE_DIR / "README.md"

    readme_line = (
        f'Source: "{readme}"; DestDir: "{{app}}"; Flags: ignoreversion'
        if readme.exists() else ""
    )

    iss_content = f"""
; Giraffe Installer Script — auto-generated by build_exe.py
#define MyAppName      "{APP_NAME}"
#define MyAppVersion   "{VERSION}"
#define MyAppPublisher "Giraffe Project"
#define MyAppExeName   "giraffe.exe"

[Setup]
AppId={{{{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
OutputDir={RELEASE_DIR}
OutputBaseFilename={APP_NAME}_Setup_{VERSION}_{ARCH}
SetupIconFile={ico_path}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
; 允许添加到 PATH
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "{{cm:CreateDesktopIcon}}";        GroupDescription: "{{cm:AdditionalIcons}}"; Flags: unchecked
Name: "addtopath";      Description: "Add Giraffe to system PATH";      GroupDescription: "System integration:";   Flags: unchecked

[Files]
Source: "{exe_path}"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{cfg_path}"; DestDir: "{{app}}"; Flags: ignoreversion onlyifdoesntexist
{readme_line}

[Icons]
Name: "{{group}}\\{{#MyAppName}}";           Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{group}}\\Uninstall {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{{#MyAppName}}";   Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Registry]
; 添加到 PATH（可选任务）
Root: HKLM; Subkey: "SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment"; \\
    ValueType: expandsz; ValueName: "Path"; \\
    ValueData: "{{olddata}};{{app}}"; \\
    Tasks: addtopath; Check: NeedsAddPath('{{app}}')

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "Launch {{#MyAppName}} now"; \\
    Flags: nowait postinstall skipifsilent
"""
    ISS_PATH.write_text(iss_content.strip(), encoding="utf-8")
    print(f"[Build] Inno Setup script written: {ISS_PATH.name}")

def build_installer() -> None:
    iscc = find_iscc()
    if iscc is None:
        print("[Build] Inno Setup not found, attempting auto-install...")
        iscc = install_inno_setup()

    if iscc is None:
        print("[Build] ✗ Inno Setup unavailable — skipping installer.")
        print("       Install manually: https://jrsoftware.org/isdl.php")
        return

    write_iss_script()
    print(f"[Build] Compiling installer with {iscc.name}...")
    result = subprocess.run([str(iscc), str(ISS_PATH)], cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("[Build] ✗ Inno Setup compilation failed.")
        return

    out = RELEASE_DIR / EXE_NAME
    if out.exists():
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"[Build] ✓ Installer: {out.name}  ({size_mb:.1f} MB)")
    else:
        print("[Build] ✗ Installer output not found.")

# ─── 6. 在 dist/ 放空白配置模板 ──────────────────────────────────────────────
def _place_config_template() -> None:
    template = {
        "_comment": "Giraffe config — edit here or run giraffe.exe to auto-configure",
        "router": {"primary_model": {}},
        "security": {"budget": {"daily_usd": 3.3, "monthly_usd": 100.0}},
        "memory": {"enabled": True},
        "display": {"color": True, "show_thinking": False},
    }
    dest = DIST_DIR / "config.json"
    if not dest.exists():
        DIST_DIR.mkdir(exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)

# ─── 7. 汇总摘要 ──────────────────────────────────────────────────────────────
def print_summary() -> None:
    print()
    print("=" * 60)
    print(f"  ✓ Build complete!  →  release/")
    print("=" * 60)
    for f in sorted(RELEASE_DIR.glob("*")):
        size_mb = f.stat().st_size / (1024 * 1024)
        tag = "📦" if f.suffix == ".zip" else "🔧"
        print(f"  {tag}  {f.name:<45}  {size_mb:>6.1f} MB")
    print("=" * 60)
    print()
    print("  Portable : unzip anywhere, run giraffe.exe")
    print("  Installer: double-click to install, adds Start Menu entry")
    print()

# ─── 主流程 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(f"  {APP_NAME} v{VERSION} — Build System")
    print("=" * 60)
    print()

    ensure_deps()
    build_ico()
    run_pyinstaller()
    _place_config_template()
    build_portable_zip()
    build_installer()
    print_summary()
