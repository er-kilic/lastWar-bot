$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$exeOutput = Join-Path $PSScriptRoot "dist"
$buildDir = Join-Path $PSScriptRoot "build\LastWarBot"
$distDir = Join-Path $exeOutput "LastWarBot"

# PyInstaller'in kendi --clean adimi OneDrive/AV tarafindan kilitli dosyalarda
# sessizce cokebiliyor; onceki ciktiyi burada kendimiz temizliyoruz.
if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }

& $python -m PyInstaller `
    --noconfirm `
    --onedir `
    --name LastWarBot `
    --contents-directory . `
    --distpath $exeOutput `
    --add-data "parameters;parameters" `
    --add-data "png;png" `
    --add-data "tesseract_bin;tesseract_bin" `
    main.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller basarisiz oldu (exit code $LASTEXITCODE). EXE guncellenmedi."
    exit $LASTEXITCODE
}

Write-Host "EXE hazir: $exeOutput\LastWarBot\LastWarBot.exe"
