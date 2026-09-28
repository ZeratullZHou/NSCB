@ECHO OFF
rem NSC_Builder 2.0a MODBAKE 启动器
rem 把 LayeredFS mod（ExeFs/RomFs 文件夹）打进游戏本体，重建为可安装的 NSP
Title NSC_Builder v2.0a -- MODBAKE
setlocal
set "prog_dir=%~dp0"

rem 自动适配目录布局：仓库源码（tools\py\ztools）、部署 2.0a（ztools_2a）或部署 1.01b（ztools）
if exist "%prog_dir%tools\py\ztools\squirrel.py" (
	set "zt=%prog_dir%tools\py\ztools"
) else if exist "%prog_dir%ztools_2a\squirrel.py" (
	set "zt=%prog_dir%ztools_2a"
) else if exist "%prog_dir%ztools\squirrel.py" (
	set "zt=%prog_dir%ztools"
) else (
	echo [!] 未找到 squirrel.py
	pause
	exit /b 1
)
cd /d "%zt%"

rem 依赖检查
python -c "import Crypto, tqdm, urllib3" >nul 2>&1
if errorlevel 1 (
	echo [!] 缺少 Python 依赖，请先安装：
	echo     pip install pycryptodome tqdm urllib3 googletrans chardet bs4 unidecode pykakasi colorama zstandard requests
	pause
	exit /b 1
)
if not exist "hacbrewpack.exe" (
	echo [!] 缺少 ztools\hacbrewpack.exe（获取方式见 README / PATCH_NOTES）
	pause
	exit /b 1
)

echo ************************************************************
echo   NSC_Builder 2.0a -- MODBAKE
echo   把 LayeredFS mod（ExeFs/RomFs 文件夹）整合进游戏本体，
echo   重建为可安装的 NSP。
echo   安装需大气层 sigpatches + DBI/Tinfoil，或 SX OS。
echo ************************************************************
echo.

set "game="
set /p game=拖入本体游戏 XCI/NSP 后回车:
if not defined game exit /b 0
set "game=%game:"=%"

set "moddir="
set /p moddir=拖入 mod 文件夹（含 ExeFs/RomFs）后回车:
if not defined moddir exit /b 0
set "moddir=%moddir:"=%"

set "outdir="
set /p outdir=输出目录（直接回车 = 游戏同目录 MODBAKE_output）:
set "outdir=%outdir:"=%"

set cmd=python squirrel.py --bake_mod "%game%" --mod_path "%moddir%"
if defined outdir set cmd=%cmd% -o "%outdir%"
if exist "%prog_dir%prod.keys" set cmd=%cmd% -k "%prog_dir%prod.keys%"
if not exist "%prog_dir%prod.keys" if exist "%zt%\keys.txt" set cmd=%cmd% -k "%zt%\keys.txt"
if not exist "%prog_dir%prod.keys" if not exist "%zt%\keys.txt" if exist "%prog_dir%ztools\keys.txt" set cmd=%cmd% -k "%prog_dir%ztools\keys.txt"

echo.
%cmd%
echo.
PAUSE
