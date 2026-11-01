@echo off
rem Yonetici olarak calistirmak icin: dosyaya sag tik > "Yonetici olarak calistir"
cd /d "%~dp0"
set "PY=python"
rem kur.bat psutil'in kuruldugu Python'un yolunu python_path.txt'ye yazar
if exist "python_path.txt" set /p PY=<python_path.txt
"%PY%" -m pbo_tuner %*
if errorlevel 1 pause
