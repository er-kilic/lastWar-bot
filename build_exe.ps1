$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$exeOutput = Join-Path $PSScriptRoot "exe_output"

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name LastWarBot `
    --distpath $exeOutput `
    --add-data "parameters;parameters" `
    --add-data "png;png" `
    main.py

Write-Host "EXE hazir: $exeOutput\LastWarBot\LastWarBot.exe"
