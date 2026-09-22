$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$workbenchPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $workbenchPython)) { throw 'Create .venv and install requirements.txt first.' }
$workbenchTcl = Join-Path $PSScriptRoot 'build/tcl-runtime'
if (-not (Test-Path -LiteralPath (Join-Path $workbenchTcl 'tcl8.6/init.tcl'))) {
    $workbenchBase = & $workbenchPython -c 'import sys; print(sys.base_prefix)'
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'build') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $workbenchBase 'tcl') -Destination $workbenchTcl -Recurse
}
# Tcl's native file loader cannot follow this host's runtime projection.
# A local dependency copy also gives PyInstaller a valid Tcl/Tk script tree.
$env:TCL_LIBRARY = Join-Path $workbenchTcl 'tcl8.6'
$env:TK_LIBRARY = Join-Path $workbenchTcl 'tk8.6'
& $workbenchPython -c 'import tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy()'
if ($LASTEXITCODE -ne 0) { throw 'Tcl/Tk runtime check failed' }
& $workbenchPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $workbenchPython -m PyInstaller --clean --noconfirm --onedir --windowed --name ActorWorkbench --add-data 'ibworkbench;ibworkbench' --exclude-module capstone --exclude-module pefile --exclude-module mmh3 --exclude-module xxhash main.py
if ($LASTEXITCODE -ne 0) { throw 'Executable packaging failed' }
Write-Host 'Built dist/ActorWorkbench/ActorWorkbench.exe. Keep its _internal folder alongside it. No game assets or Blender are bundled.'
