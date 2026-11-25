@echo off
REM Cift tikla: render PC kurulumu (X:\ComfyVFX). Yonetici izni ister.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoExit -ExecutionPolicy Bypass -File \"%~dp0windows\install_render_pc.ps1\" -InstallDir X:\ComfyVFX'"
