@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Arayuz dili: PBO_LANG (tr/en) varsa o; yoksa Windows bolgesel ayari veya kurulum dili Turkce ise tr, degilse en.
rem (Python tarafi ayni kurali kullanir; config.toml [ui] language ayari yalnizca Python mesajlarini etkiler.)
set "UILANG=en"
set "LOC=xx"
for /f "tokens=3" %%L in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do set "LOC=%%L"
if /i "%LOC:~0,2%"=="tr" set "UILANG=tr"
for /f "tokens=3" %%L in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Nls\Language" /v InstallLanguage 2^>nul') do if /i "%%L"=="041F" set "UILANG=tr"
if /i "%PBO_LANG%"=="tr" set "UILANG=tr"
if /i "%PBO_LANG%"=="en" set "UILANG=en"

if "%UILANG%"=="tr" title PBO AutoTuner kurulum
if not "%UILANG%"=="tr" title PBO AutoTuner setup
echo.
if "%UILANG%"=="tr" echo === PBO AutoTuner kurulum ===
if not "%UILANG%"=="tr" echo === PBO AutoTuner setup ===
echo.

call :find
if defined PYEXE goto have_python

if "%UILANG%"=="tr" echo Python 3.11 veya uzeri bulunamadi. Otomatik kurulum deneniyor...
if not "%UILANG%"=="tr" echo Python 3.11 or newer was not found. Trying automatic installation...
where winget >nul 2>nul
if errorlevel 1 goto try_download
if "%UILANG%"=="tr" echo winget ile Python 3.12 kuruluyor. Yonetici izni gerekmez, birkac dakika surebilir...
if not "%UILANG%"=="tr" echo Installing Python 3.12 with winget. No administrator rights needed, this may take a few minutes...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find
if defined PYEXE goto have_python
if "%UILANG%"=="tr" echo winget ile kurulum olmadi. python.org uzerinden denenecek...
if not "%UILANG%"=="tr" echo winget installation did not work. Trying python.org instead...

:try_download
call :download_python
call :find
if defined PYEXE goto have_python

echo.
if "%UILANG%"=="tr" echo HATA: Python otomatik kurulamadi.
if not "%UILANG%"=="tr" echo ERROR: Python could not be installed automatically.
if "%UILANG%"=="tr" echo Elle kurun: https://www.python.org/downloads/
if not "%UILANG%"=="tr" echo Install it by hand: https://www.python.org/downloads/
if "%UILANG%"=="tr" echo Kurulumda "Add python.exe to PATH" kutusunu isaretleyin, sonra bu dosyayi tekrar calistirin.
if not "%UILANG%"=="tr" echo During setup tick "Add python.exe to PATH", then run this file again.
goto fail

:have_python
if "%UILANG%"=="tr" echo Python bulundu: %PYEXE%
if not "%UILANG%"=="tr" echo Python found: %PYEXE%
echo.
"%PYEXE%" -m pbo_tuner.setup_env
if errorlevel 1 goto fail
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1

rem ---------------------------------------------------------------------------
rem :find  ->  PYEXE'yi 3.11+ bir python.exe yoluna ayarlar (bulunamazsa bos)
rem ---------------------------------------------------------------------------
:find
set "PYEXE="
call :try_py 3.12
call :try_py 3.13
call :try_py 3.11
call :try_py 3.14
call :try_dir "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :try_dir "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :try_dir "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
call :try_dir "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
call :try_dir "%ProgramFiles%\Python312\python.exe"
call :try_dir "%ProgramFiles%\Python313\python.exe"
call :try_dir "%ProgramFiles%\Python311\python.exe"
call :try_dir "%ProgramFiles%\Python314\python.exe"
call :try_cmd python
goto :eof

:try_py
if defined PYEXE goto :eof
set "CAND="
for /f "usebackq delims=" %%P in (`py -%1 -c "import sys; print(sys.executable)" 2^>nul`) do set "CAND=%%P"
call :accept "%CAND%"
goto :eof

:try_cmd
if defined PYEXE goto :eof
set "CAND="
for /f "usebackq delims=" %%P in (`%1 -c "import sys; print(sys.executable)" 2^>nul`) do set "CAND=%%P"
call :accept "%CAND%"
goto :eof

:try_dir
if defined PYEXE goto :eof
call :accept %1
goto :eof

:accept
if defined PYEXE goto :eof
if "%~1"=="" goto :eof
if not exist "%~1" goto :eof
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof

rem ---------------------------------------------------------------------------
rem :download_python  ->  python.org'dan Python 3.12.10 (son ikili kurulumlu 3.12 surumu) indirip sessiz kurar
rem ---------------------------------------------------------------------------
:download_python
set "PYINST=%TEMP%\python-3.12.10-amd64.exe"
if "%UILANG%"=="tr" echo python.org uzerinden Python 3.12.10 indiriliyor...
if not "%UILANG%"=="tr" echo Downloading Python 3.12.10 from python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%PYINST%'"
if errorlevel 1 goto :eof
if not exist "%PYINST%" goto :eof
if "%UILANG%"=="tr" echo Kuruluyor. Yonetici izni gerekmez...
if not "%UILANG%"=="tr" echo Installing. No administrator rights needed...
start /wait "" "%PYINST%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
goto :eof
