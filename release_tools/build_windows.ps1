# Windows-only portable build; excludes all game binaries and private data.
param([string]$Python = $(if($env:CFR_BUILD_PYTHON){$env:CFR_BUILD_PYTHON}else{"python"}),
      [string]$BuildRoot = $(if($env:CFR_BUILD_DIR){$env:CFR_BUILD_DIR}else{""}))
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if(-not $BuildRoot) {
  $BuildRoot = Join-Path (Split-Path -Parent $Source) "Crash Forge Launcher Dist"
}
if(-not [IO.Path]::IsPathRooted($BuildRoot)) {
  $BuildRoot = Join-Path $Source $BuildRoot
}
[IO.Directory]::CreateDirectory($BuildRoot) | Out-Null
$distRoot = Join-Path $BuildRoot "dist"
$workRoot = Join-Path $BuildRoot "work"
$specRoot = Join-Path $BuildRoot "spec"
$releaseRoot = Join-Path $BuildRoot "release"
foreach($item in @($distRoot,$workRoot,$specRoot,$releaseRoot)) {
  [IO.Directory]::CreateDirectory($item) | Out-Null
}
$exeDir = Join-Path $distRoot "CrashForgeLauncher"
if(Test-Path -LiteralPath $exeDir) {
  Remove-Item -LiteralPath $exeDir -Recurse -Force
}
$featuredAsset = (Join-Path $Source "assets\news\latest_update.webp") + ";assets/news"
$historyAsset = (Join-Path $Source "assets\news\publications.json") + ";assets/news"
# If images are provided later, bundle them under their ORIGINAL version.
$newsArtArguments = @()
foreach($name in @("forge-news-v0.3.37.webp", "forge-news-v0.3.38.webp")) {
  $picture = Join-Path $Source ("assets\news\" + $name)
  if(Test-Path -LiteralPath $picture) {
    $newsArtArguments += @("--add-data", ($picture + ";assets/news"))
  }
}
Write-Output "Building main Windows launcher..."
& $Python -m PyInstaller --noconfirm --clean --noupx --onedir --windowed --contents-directory "_internal" --add-data $featuredAsset --add-data $historyAsset @newsArtArguments --name "CrashForgeLauncher" --icon (Join-Path $Source "assets\icons\cfr_icon.ico") --distpath $distRoot --workpath (Join-Path $workRoot "main") --specpath $specRoot (Join-Path $Source "launcher.py")
if($LASTEXITCODE -ne 0) {throw "Main launcher PyInstaller build failed"}
Write-Output "Building independent updater helper..."
& $Python -m PyInstaller --noconfirm --clean --noupx --onefile --windowed --name "ForgeLauncherUpdater" --icon (Join-Path $Source "assets\icons\cfr_icon.ico") --distpath (Join-Path $BuildRoot "updater") --workpath (Join-Path $workRoot "updater") --specpath $specRoot (Join-Path $Source "launcher_update_helper.py")
if($LASTEXITCODE -ne 0) {throw "Update helper PyInstaller build failed"}
Copy-Item -LiteralPath (Join-Path $BuildRoot "updater\ForgeLauncherUpdater.exe") -Destination (Join-Path $exeDir "ForgeLauncherUpdater.exe") -Force
Write-Output "Building bundled Crash Forge Model Importer v1.8..."
$modelImporterBackground = (Join-Path $Source "assets\Fondo.png") + ";assets"
$modelImporterIcon = (Join-Path $Source "assets\icons\cfr_icon.ico") + ";assets/icons"
& $Python -m PyInstaller --noconfirm --clean --noupx --onefile --windowed --name "CrashForgeModelImporter" --icon (Join-Path $Source "assets\icons\cfr_icon.ico") --add-data $modelImporterBackground --add-data $modelImporterIcon --distpath (Join-Path $BuildRoot "model_importer") --workpath (Join-Path $workRoot "model_importer") --specpath $specRoot (Join-Path $Source "companion_tools\model_importer\crash_forge_character_tool.py")
if($LASTEXITCODE -ne 0){throw "Model Importer build failed"}
# Importer is included in verified launcher ZIP and updated automatically.
$toolsTarget = Join-Path $exeDir "_internal\editor_tools"
[IO.Directory]::CreateDirectory($toolsTarget) | Out-Null
Copy-Item -LiteralPath (Join-Path $BuildRoot "model_importer\CrashForgeModelImporter.exe") -Destination (Join-Path $toolsTarget "CrashForgeModelImporter.exe") -Force
$assets = @(
  @{Source="assets\Fondo.png"; Target="assets\Fondo.png"},
  @{Source="assets\icons\cfr_icon.png"; Target="assets\icons\cfr_icon.png"},
  @{Source="assets\icons\cfr_icon.ico"; Target="assets\icons\cfr_icon.ico"},
  @{Source="assets\art\kart_sketch_icon.png"; Target="assets\art\kart_sketch_icon.png"}
)
foreach($asset in $assets) {
  $from = Join-Path $Source $asset.Source
  if(-not (Test-Path -LiteralPath $from)){throw "Missing launcher resource: $from"}
  $to = Join-Path $exeDir $asset.Target
  [IO.Directory]::CreateDirectory((Split-Path -Parent $to)) | Out-Null
  Copy-Item -LiteralPath $from -Destination $to -Force
}
foreach($file in @("launcher_version.txt","LAUNCHER_CHANGELOG.txt","forge_online_config.json")) {
  Copy-Item -LiteralPath (Join-Path $Source $file) -Destination (Join-Path $exeDir $file) -Force
}
$version = (Get-Content -LiteralPath (Join-Path $exeDir "launcher_version.txt") -Raw).Trim()
if($version -notmatch '^\d+\.\d+\.\d+$'){throw "Invalid launcher release version"}
Write-Output "Validating distributable package..."
& $Python (Join-Path $Source "release_tools\verify_bundle.py") $exeDir
if($LASTEXITCODE -ne 0){throw "Bundle validation failed"}
$zipName = "Crash-Forge-Launcher-Windows.zip"
$archive = Join-Path $releaseRoot $zipName
if(Test-Path -LiteralPath $archive){Remove-Item -LiteralPath $archive -Force}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($exeDir,$archive,[IO.Compression.CompressionLevel]::Optimal,$false)
& $Python (Join-Path $Source "release_tools\verify_bundle.py") $archive
if($LASTEXITCODE -ne 0){throw "Release ZIP verification failed"}
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$sidecar = Join-Path $releaseRoot ($zipName+".sha256")
[IO.File]::WriteAllText($sidecar,($hash+"  "+$zipName+[Environment]::NewLine),[Text.Encoding]::ASCII)
$size = (Get-Item -LiteralPath $archive).Length
Write-Output "READY: $archive"
Write-Output "VERSION: $version"
Write-Output "SIZE: $size"
Write-Output "SHA256: $hash"
Write-Output "Do not publish until the standalone GitHub launcher repo exists."
