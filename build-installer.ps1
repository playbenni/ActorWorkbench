param(
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.1.0',
    [string]$InnoCompiler,
    [switch]$SkipAppBuild
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $SkipAppBuild) { & (Join-Path $PSScriptRoot 'build.ps1') }
if (-not (Test-Path -LiteralPath 'dist/ActorWorkbench/ActorWorkbench.exe')) { throw 'Build the app first.' }
if (-not $InnoCompiler) {
    $compilerCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($compilerCommand) { $InnoCompiler = $compilerCommand.Source }
    else {
        $candidates = @(
            "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe",
            "$env:LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe",
            "$PSScriptRoot/build/inno/ISCC.exe"
        )
        $InnoCompiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $InnoCompiler) { throw 'Install Inno Setup 6 or pass -InnoCompiler with the path to ISCC.exe.' }
& $InnoCompiler "/DAppVersion=$Version" (Join-Path $PSScriptRoot 'installer/ActorWorkbench.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$installerPath = Join-Path $PSScriptRoot "dist/installer/ActorWorkbench-$Version-Setup-x64.exe"
$checksum = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$checksum  $([IO.Path]::GetFileName($installerPath))" | Set-Content -LiteralPath "$installerPath.sha256" -Encoding ascii
Write-Host "Built $installerPath"
