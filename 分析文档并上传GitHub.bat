@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

title ZhiDu - Analyze and Publish

set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py"

if not "%~1"=="" goto run_file

echo.
echo ==========================================
echo   ZhiDu - Analyze document and push GitHub
echo ==========================================
echo   A file picker will open.
echo   Choose a document to analyze:
echo   .docx / .txt / .md / .srt / .pdf / .rtf
echo.

"%PY%" analyze_and_publish.py --pick
if errorlevel 1 goto failed
goto done

:run_file
echo.
echo Analyzing: %~1
"%PY%" analyze_and_publish.py --file "%~1"
if errorlevel 1 goto failed

:done
echo.
echo Done. Press any key to close...
pause >nul
exit /b 0

:failed
echo.
echo [FAILED] See the message above.
echo Press any key to close...
pause >nul
exit /b 1
