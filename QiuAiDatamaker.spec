# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


APP_DIR = Path(SPECPATH)
REPO_DIR = APP_DIR.parent
TRAJECTORY_SCRIPT_DIR = APP_DIR / "trajectory_scripts"
ICON_DIR = APP_DIR / "icon"
ICON_FILE = ICON_DIR / "Q1.ico"

datas = [
    (str(TRAJECTORY_SCRIPT_DIR), "trajectory_scripts"),
    (str(ICON_DIR), "icon"),
]
datas += collect_data_files("openai")

binaries = []
conda_bin_dir = Path(sys.prefix) / "Library" / "bin"
required_runtime_dlls = [
    "libexpat.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "liblzma.dll",
    "libbz2.dll",
    "ffi.dll",
    "sqlite3.dll",
]
if conda_bin_dir.exists():
    for dll_name in required_runtime_dlls:
        dll_path = conda_bin_dir / dll_name
        if dll_path.exists():
            binaries.append((str(dll_path), "."))

hiddenimports = []
hiddenimports += collect_submodules("openai")

a = Analysis(
    ["app.py"],
    pathex=[str(APP_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QiuAiDatamaker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ICON_FILE),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="QiuAiDatamaker",
)
