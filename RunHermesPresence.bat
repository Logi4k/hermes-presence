@echo off
:: RunHermesPresence.bat
:: Drop this in shell:startup to auto-start with Windows
:: Or double-click to run manually
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0RunHermesPresence.ps1"
