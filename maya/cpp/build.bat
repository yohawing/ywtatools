@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul || exit /b 1

if "%~1"=="" goto :default_matrix

for %%V in (%*) do (
    call :build_version "%%~V"
    if errorlevel 1 goto :failed
)
goto :success

:default_matrix
call :build_version "2025"
if errorlevel 1 goto :failed
call :build_version "2026"
if errorlevel 1 goto :failed
call :build_version "2027"
if errorlevel 1 goto :failed
goto :success

:build_version
set "VERSION=%~1"
if "%VERSION%"=="2025" goto :version_valid
if "%VERSION%"=="2026" goto :version_valid
if "%VERSION%"=="2027" goto :version_valid
echo Unsupported Maya version: %VERSION% 1>&2
exit /b 2

:version_valid
set "BUILD_DIR=%SCRIPT_DIR%build.%VERSION%-ninja"
set "VSWHERE=C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
    echo vswhere.exe was not found: "%VSWHERE%" 1>&2
    exit /b 1
)
set "VS_INSTALL="
for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -version "[17.0,18.0)" -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS_INSTALL=%%I"
if not defined VS_INSTALL (
    echo Visual Studio 2022 C++ x64 toolchain was not found 1>&2
    exit /b 1
)
set "VSDEVCMD=%VS_INSTALL%\Common7\Tools\VsDevCmd.bat"
if not exist "%VSDEVCMD%" (
    echo VS2022 VsDevCmd.bat was not found: "%VSDEVCMD%" 1>&2
    exit /b 1
)
call "%VSDEVCMD%" -arch=x64 >nul
if errorlevel 1 (
    echo Failed to initialize the VS2022 x64 environment 1>&2
    exit /b 1
)
where ninja >nul 2>&1
if errorlevel 1 (
    echo Ninja is required for Maya plugin builds but was not found on PATH 1>&2
    exit /b 1
)
echo Configuring Maya %VERSION% in "%BUILD_DIR%"
cmake -S "%SCRIPT_DIR%." -B "%BUILD_DIR%" -G Ninja -DCMAKE_BUILD_TYPE=Release -DMAYA_VERSION=%VERSION%
if errorlevel 1 (
    echo CMake configure failed for Maya %VERSION% 1>&2
    exit /b 1
)

echo Building Maya %VERSION% (Release)
cmake --build "%BUILD_DIR%" --target install --config Release
if errorlevel 1 (
    echo CMake build failed for Maya %VERSION% 1>&2
    exit /b 1
)
exit /b 0

:failed
popd >nul
exit /b 1

:success
popd >nul
exit /b 0
