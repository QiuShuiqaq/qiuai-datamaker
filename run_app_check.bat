@echo off
set PYTHON_EXE=D:\Program\PYTHON\python\python.exe
set APP_DIR=%~dp0

if not exist "%PYTHON_EXE%" (
  echo Python not found: %PYTHON_EXE%
  pause
  exit /b 1
)

pushd "%APP_DIR%"
"%PYTHON_EXE%" app.py --startup-check
popd
