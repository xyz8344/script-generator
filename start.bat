@echo off
chcp 65001 >nul
title 🎬 爆款脚本生成器

echo.
echo   🎬 爆款脚本生成器 - 正在启动...
echo.
echo   依赖安装中，请稍候...
echo.

cd /d "%~dp0"

:: 安装依赖
pip install -r requirements.txt -q

echo.
echo   ✅ 依赖就绪，正在启动网站...
echo.
echo   📱 浏览器会自动打开，不要关掉这个窗口。
echo   🛑 用完后按 Ctrl+C 停止。
echo.
echo   ─────────────────────────────────────
echo.

:: 启动 Streamlit
streamlit run app.py --server.port 8501 --server.headless true

pause
