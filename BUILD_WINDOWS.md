# Windows Build

## 1. Install Dependencies

```powershell
pip install -r requirements.txt
pip install pyinstaller
```

## 2. Build App

```powershell
.\build_windows.ps1
```

Output will be generated under `dist/QiuAiDatamaker/`.

This build includes:

- the application
- bundled Python runtime
- bundled Python dependencies
- bundled `trajectory_scripts` resources used by convert/check/label flow
- generated `icon\Q1.ico` from `icon\Q1.png`

## 3. Package as Installer

Use Inno Setup with [installer_windows.iss](/F:/Workspace_VS/QiuAi-datamaker/openclaw_hermas_data/qiuai-datamaker/installer_windows.iss:1).

Steps:

```powershell
iscc installer_windows.iss
```

If `iscc` is not in `PATH`, open the script directly in Inno Setup and click `Build`.

Recommended installer contents:

- `QiuAiDatamaker.exe`
- bundled Python runtime files from PyInstaller
- bundled `trajectory_scripts`

## 4. Runtime Notes

- Dev mode writes to the project `DATA/` directory
- Installed builds write to `%LOCALAPPDATA%\QiuAiDatamaker\DATA`
- each student stores local config and logs on their own machine
- DeepSeek key is local per student
