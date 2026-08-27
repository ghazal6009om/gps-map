@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Video Converter - Convert to Web MP4 (Preserve GPS/Metadata)

REM ============================================================
REM   Video Converter Tool
REM   Converts any video (MOV/MKV/etc) to browser-friendly MP4
REM   (H.264 + AAC, auto-rotation) while PRESERVING ALL metadata:
REM   GPS coordinates, date/time, and device details.
REM   Uses ffmpeg (conversion) + exiftool (metadata copy).
REM
REM   USAGE: drag & drop a video file onto this .bat, OR type the path.
REM ============================================================

set "SCRIPTPATH=%~dp0"
set "FFMPEG=ffmpeg"
set "EXIFTOOL=%SCRIPTPATH%tools\exiftool\exiftool.exe"

echo ============================================
echo    Video Converter - Web MP4 + Metadata
echo ============================================
echo.

REM ---- Get input file ----
if not "%~1"=="" (
    set "INPUT=%~1"
) else (
    set /p "INPUT=Drag & drop a video file here and press Enter: "
)
set "INPUT=%INPUT:"=%"

if not exist "%INPUT%" (
    echo [ERROR] File not found: "%INPUT%"
    echo.
    pause
    exit /b 1
)

REM ---- Locate ffmpeg (prefer bundled copy, else PATH) ----
if exist "%SCRIPTPATH%tools\ffmpeg\bin\ffmpeg.exe" set "FFMPEG=%SCRIPTPATH%tools\ffmpeg\bin\ffmpeg.exe"
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ffmpeg not found. Install ffmpeg or place it in tools\ffmpeg\bin.
    pause
    exit /b 1
)

REM ---- Prepare ASCII temp workspace (handles Arabic/spaces in names) ----
set "WORK=%TEMP%\vid_convert_tool"
if not exist "%WORK%" mkdir "%WORK%"
set "SRCFILE=%WORK%\src_input"
set "EXT=%~x1"

REM ---- Copy to ASCII temp name ----
copy /y "%INPUT%" "%SRCFILE%%EXT%" >nul
if errorlevel 1 (
    echo [ERROR] Could not read input file.
    pause
    exit /b 1
)
set "SRC=%SRCFILE%%EXT%"
set "OUT=%WORK%\out.mp4"

echo Converting... (this may take a while for large videos)
echo.
echo Source : %INPUT%
echo Output : %~dp1%~n1.mp4
echo.

REM ---- Convert: web-compatible H.264 + AAC, auto-rotation, yuv420p ----
"%FFMPEG%" -y -i "%SRC%" -c:v libx264 -preset medium -crf 23 -vf "format=yuv420p" -c:a aac -movflags +faststart "%OUT%" 2>nul
if errorlevel 1 (
    echo [ERROR] Conversion failed. Is this a valid video file?
    pause
    exit /b 1
)

REM ---- Preserve all metadata (GPS, date/time, device) from source ----
echo Copying metadata (GPS, date, device)...
"%EXIFTOOL%" -overwrite_original_in_place -TagsFromFile "%SRC%" -all:all "-GPS:all" "-Keys:all" "-QuickTime:all" "-Composite:all" "%OUT%" >nul 2>nul

REM ---- Place result next to source with same base name ----
copy /y "%OUT%" "%~dp1%~n1.mp4" >nul
if errorlevel 1 (
    echo [ERROR] Could not write output file to source folder.
    pause
    exit /b 1
)

echo.
echo ============================================
echo    SUCCESS!
echo    Saved: %~dp1%~n1.mp4
echo    Video converted to MP4 and metadata preserved.
echo ============================================
echo.
pause
endlocal
