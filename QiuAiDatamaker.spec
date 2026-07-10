# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


APP_DIR = Path(SPECPATH)
REPO_DIR = APP_DIR.parent
TRAJECTORY_SCRIPT_DIR = REPO_DIR / "trajectory_data_code" / "阿里脚本"
ICON_DIR = APP_DIR / "icon"
ICON_FILE = ICON_DIR / "Q1.ico"

datas = [
    (str(TRAJECTORY_SCRIPT_DIR), "trajectory_scripts"),
    (str(ICON_DIR), "icon"),
]
datas += collect_data_files("openai")

hiddenimports = []
hiddenimports += collect_submodules("openai")

a = Analysis(
    ["app.py"],
    pathex=[str(APP_DIR)],
    binaries=[],
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
