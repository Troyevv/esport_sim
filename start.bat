@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0" || goto :error
py -3.12 -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))" >nul 2>nul
if not errorlevel 1 goto :py
python -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))" >nul 2>nul
if errorlevel 1 goto :missing
python -X utf8 "tools\source_windows.py" start
goto :result
:py
py -3.12 -X utf8 "tools\source_windows.py" start
:result
if errorlevel 1 goto :error
popd
exit /b 0
:missing
echo Для запуска из исходников установите Python 3.12 для Windows.
:error
echo Не удалось завершить операцию EsportSim. Проверьте сообщение выше.
pause
exit /b 1
