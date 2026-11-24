@echo off
rem Yonetici olarak calistirmak icin: dosyaya sag tik > "Yonetici olarak calistir"
cd /d "%~dp0"
rem python_path.txt UTF-8 yazilir. Kullanici adinda ASCII disi harf varsa Python yolu ancak UTF-8 kod
rem sayfasinda dogru okunur, yoksa Python bulunamaz.
chcp 65001 >nul
set "PY=python"
rem kur.bat psutil'in kuruldugu Python'un yolunu python_path.txt'ye yazar
if exist "python_path.txt" set /p PY=<python_path.txt
"%PY%" -m pbo_tuner %*
if errorlevel 1 pause
