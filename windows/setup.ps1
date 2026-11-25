# ComfyUI <-> DaVinci Resolve VFX köprüsü - Windows kurulumu
# Kullanım (PowerShell):  powershell -ExecutionPolicy Bypass -File windows\setup.ps1
# İsteğe bağlı:  -ExchangeDir "G:\My Drive\VFX_Exchange"  -ComfyUrl "http://127.0.0.1:8188"
param(
    [string]$ExchangeDir = "",
    [string]$ComfyUrl = "http://127.0.0.1:8188"
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

Write-Host "== 1) Python kontrolü" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python yok. Kuruluyor (winget)..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    Write-Host "Kurulumdan sonra PowerShell'i kapatıp açıp bu script'i tekrar çalıştır." -ForegroundColor Yellow
    exit 1
}
python --version

Write-Host "== 2) ffmpeg kontrolü (video kare işleme için)" -ForegroundColor Cyan
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
}

Write-Host "== 3) Exchange (bulut senkron) klasörü" -ForegroundColor Cyan
if (-not $ExchangeDir) {
    # Google Drive for Desktop varsa onu kullan (ücretsiz 15 GB)
    $gd = Get-PSDrive -PSProvider FileSystem | Where-Object { Test-Path "$($_.Root)My Drive" } | Select-Object -First 1
    if ($gd) { $ExchangeDir = "$($gd.Root)My Drive\VFX_Exchange" }
    else { $ExchangeDir = "$env:USERPROFILE\VFX_Exchange" ; Write-Host "Google Drive bulunamadı, yerel klasör kullanılıyor." -ForegroundColor Yellow }
}
New-Item -ItemType Directory -Force -Path "$ExchangeDir\to_comfy", "$ExchangeDir\from_comfy" | Out-Null
Write-Host "Exchange: $ExchangeDir"

Write-Host "== 4) Ayar dosyası" -ForegroundColor Cyan
$cfgDir = "$env:USERPROFILE\.comfy_vfx"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfgFile = "$cfgDir\config.json"
if (Test-Path $cfgFile) {
    Write-Host "Mevcut ayar korunuyor: $cfgFile"
} else {
    $cfg = [ordered]@{
        comfy_url = $ComfyUrl
        exchange_dir = $ExchangeDir.Replace('\', '/')
        poll_seconds = 1.5
        timeout_seconds = 3600
        ffmpeg = "ffmpeg"
        default_fps = 24
        resolve_append_to_timeline = $false
    }
    $cfg | ConvertTo-Json | Set-Content -Encoding UTF8 $cfgFile
    Write-Host "Yazıldı: $cfgFile"
}

Write-Host "== 5) DaVinci Resolve script'leri" -ForegroundColor Cyan
$resolveScripts = "$env:APPDATA\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"
New-Item -ItemType Directory -Force -Path $resolveScripts | Out-Null
Copy-Item "$Repo\resolve_scripts\*.py" $resolveScripts -Force
Write-Host "Kopyalandı -> $resolveScripts"
Write-Host "Resolve'u yeniden başlat: Workspace > Scripts > 'ComfyUI Import' / 'ComfyUI Send Timeline Range'"

Write-Host "== 6) ComfyUI bağlantı testi" -ForegroundColor Cyan
try { python "$Repo\tools\comfy_vfx.py" ping } catch { Write-Host "ComfyUI şu an kapalı - açınca 'python tools\comfy_vfx.py ping' ile test et." -ForegroundColor Yellow }

Write-Host "`nKurulum tamam." -ForegroundColor Green
