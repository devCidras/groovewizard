# Gera a app (dist\GrooveWizard\) e o instalador (dist\GrooveWizard-<versao>-setup.exe).
# Precisa: Python, e o Inno Setup 6 (https://jrsoftware.org/isinfo.php) para o instalador.
# -SemInstalador: so gera e testa dist\ (usado no CI, que nao tem o Inno Setup)
param([switch]$SemInstalador)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install --quiet pyinstaller==6.22.3 -r requirements.txt
$version = python -c "import organizador; print(organizador.__version__)"

# termos em .txt para o ecra de licenca do instalador (mesmo texto que a app mostra)
New-Item -ItemType Directory -Force installer\build | Out-Null
python -c "from organizador import termos; [open(f'installer/build/termos_{k}.txt','w',encoding='utf-8-sig').write(v) for k,v in termos.TERMS.items()]"

python tests\test_pipeline.py
if ($LASTEXITCODE -ne 0) { exit 1 }

# pacotes grandes que a app nao usa, se estiverem instalados neste PC.
# Modulos Qt que a app nao usa ficam de fora (e alguns, como o VirtualKeyboard, nao sao LGPL).
$excl = "librosa numba scipy sklearn PySide6.QtQml PySide6.QtQuick PySide6.QtPdf PySide6.QtOpenGL PySide6.QtVirtualKeyboard".Split(" ") | ForEach-Object { "--exclude-module", $_ }
python -m PyInstaller --noconfirm --clean --windowed --name GrooveWizard --icon organizador\recursos\groovewizard.ico `
    --add-data "organizador\recursos;organizador\recursos" @excl app.py
if ($LASTEXITCODE -ne 0) { exit 1 }

# o hook do PySide6 copia DLLs do Qt mesmo sem os modulos: tirar as que nao sao usadas
$qt = "dist\GrooveWizard\_internal\PySide6"
$unused = "Qt6VirtualKeyboard.dll Qt6Pdf.dll Qt6Qml.dll Qt6QmlMeta.dll Qt6QmlModels.dll Qt6QmlWorkerScript.dll Qt6Quick.dll Qt6OpenGL.dll opengl32sw.dll plugins\imageformats\qpdf.dll plugins\generic\qtuiotouchplugin.dll".Split(" ")
foreach ($f in $unused) { if (Test-Path "$qt\$f") { Remove-Item -LiteralPath "$qt\$f" -Force } }
foreach ($d in "plugins\platforminputcontexts", "plugins\networkinformation", "plugins\tls", "qml") {
    if (Test-Path "$qt\$d") { Get-ChildItem -LiteralPath "$qt\$d" -File -Recurse | Remove-Item -Force; Remove-Item -LiteralPath "$qt\$d" -Recurse -Force }
}

# a app empacotada tem de arrancar (e medir um BPM) depois de tirar os modulos
Push-Location $env:TEMP
$testLog = Join-Path $env:TEMP "groovewizard-self-test.log"
Remove-Item $testLog -ErrorAction SilentlyContinue
$testProcess = Start-Process "$PSScriptRoot\dist\GrooveWizard\GrooveWizard.exe" -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
$ok = $testProcess.ExitCode -eq 0 -and (Test-Path $testLog) -and (Select-String -Quiet -Pattern "^self-test ok" -Path $testLog)
Remove-Item $testLog -ErrorAction SilentlyContinue
Pop-Location
if (-not $ok) { Write-Error "o .exe nao arranca ou nao fecha corretamente depois de tirar os modulos Qt"; exit 1 }

# nenhum plugin/DLL do Qt pode depender de uma DLL que foi tirada
$gone = "Qt6Pdf Qt6Qml Qt6Quick Qt6OpenGL Qt6VirtualKeyboard".Split(" ")
$broken = Get-ChildItem $qt -Recurse -Include *.dll, *.pyd | Where-Object {
    $bytes = [System.IO.File]::ReadAllBytes($_.FullName); $text = [System.Text.Encoding]::ASCII.GetString($bytes)
    $gone | Where-Object { $text.Contains("$_.dll") } }
if ($broken) { Write-Error ("ficheiros que dependem de DLLs tiradas: " + ($broken.Name -join ", ")); exit 1 }

# licencas, avisos de terceiros e as versoes exatas usadas nesta build vao com a app
New-Item -ItemType Directory -Force dist\GrooveWizard\licencas | Out-Null
Copy-Item licencas\* dist\GrooveWizard\licencas\ -Force
Copy-Item LICENSE dist\GrooveWizard\LICENSE.txt -Force
$v = @("Versao da app: $version", ("Python: " + (python -c "import sys; print(sys.version)")))
$v += python -m pip freeze | Select-String -Pattern "^(mutagen|PySide6|PySide6_Essentials|shiboken6|Send2Trash|pyinstaller|numpy|soundfile|cffi|pycparser|typing_extensions)==" -CaseSensitive:$false
$v | Set-Content -Encoding utf8 dist\GrooveWizard\licencas\VERSOES.txt
if ($SemInstalador) { exit 0 }

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Write-Error "Inno Setup nao encontrado (https://jrsoftware.org/isinfo.php): instalador nao gerado"; exit 1 }
& $iscc "/DAppVersion=$version" installer\GrooveWizard.iss
