@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Iniciando Trading Scanner Dashboard...
echo Acede a: http://localhost:8501
python -m streamlit run dashboard.py --server.headless false --browser.gatherUsageStats false
pause
