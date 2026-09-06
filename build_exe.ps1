$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$exeOutput = Join-Path $PSScriptRoot "dist"

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name LastWarBot `
    --contents-directory . `
    --distpath $exeOutput `
    --add-data "parameters;parameters" `
    --add-data "png;png" `
    --add-data "tesseract_bin;tesseract_bin" `
    main.py

Write-Host "EXE hazir: $exeOutput\LastWarBot\LastWarBot.exe"
