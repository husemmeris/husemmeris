# =====================================================================================
#  Windows RENDER BİLGİSAYARI kurulumu  (ComfyUI + Drive render worker)
#
#  Zip'i aç, klasörde PowerShell'i YÖNETİCİ olarak aç ve:
#     powershell -ExecutionPolicy Bypass -File windows\install_render_pc.ps1
#
#  Seçenekler:
#     -InstallDir "D:\ComfyVFX"     (varsayılan: C:\ComfyVFX  - modeller büyük, boş yeri olan diski seç)
#     -ExchangeDir "G:\My Drive\VFX_Exchange"   (otomatik bulunamazsa)
#     -SDXL                          (SDXL modelini de indir, ~7 GB, 8 GB+ VRAM önerilir)
#     -SkipModels                    (modelleri indirme)
#     -AllowSleep                    (bilgisayarın uyku ayarına dokunma)
#
#  Tekrar çalıştırmak güvenlidir: var olanı atlar, eksikleri tamamlar.
# =====================================================================================
param(
    [string]$InstallDir = "C:\ComfyVFX",
    [string]$ExchangeDir = "",
    [switch]$SDXL,
    [switch]$SkipModels,
    [switch]$AllowSleep
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest'i çok hızlandırır
$Src = Split-Path -Parent $PSScriptRoot

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Warn($t) { Write-Host "UYARI: $t" -ForegroundColor Yellow }
function RefreshPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function WingetInstall($id, $cmd) {
    if ($cmd -and (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Host "$id zaten var."; return }
    Write-Host "Kuruluyor: $id"
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements | Out-Host
    RefreshPath
}
function Download($url, $dest) {
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1MB)) { Write-Host "Var: $(Split-Path $dest -Leaf)"; return }
    Write-Host "İndiriliyor: $(Split-Path $dest -Leaf)"
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    & curl.exe -L --fail --retry 5 -C - -o "$dest.part" $url
    if ($LASTEXITCODE -ne 0) { throw "İndirme başarısız: $url" }
    Move-Item -Force "$dest.part" $dest
}

# ------------------------------------------------------------------------------------
Step "1) Ekran kartı"
$gpu = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
Write-Host ($gpu -join ", ")
$nvidia = $gpu | Where-Object { $_ -match "NVIDIA" }
if (-not $nvidia) {
    Warn "NVIDIA kart bulunamadı. ComfyUI CPU'da çok yavaş çalışır. AMD için ComfyUI'nin AMD/DirectML sürümü gerekir."
} else {
    try { nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader } catch { Warn "nvidia-smi yok: NVIDIA sürücüsünü güncelle." }
}

Step "2) Gerekli araçlar (winget)"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "winget yok. Microsoft Store'dan 'App Installer'ı kur ve tekrar dene." }
WingetInstall "7zip.7zip" $null
WingetInstall "Git.Git" "git"
WingetInstall "Gyan.FFmpeg" "ffmpeg"
$sevenZip = @("$env:ProgramFiles\7-Zip\7z.exe", "${env:ProgramFiles(x86)}\7-Zip\7z.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenZip) { throw "7-Zip bulunamadı." }
$ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ffmpeg) { $ffmpeg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName }
Write-Host "ffmpeg: $ffmpeg"

Step "3) ComfyUI (portable, NVIDIA)"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$portable = Join-Path $InstallDir "ComfyUI_windows_portable"
if (-not (Test-Path "$portable\ComfyUI\main.py")) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest" -Headers @{ "User-Agent" = "comfy-vfx-installer" }
    $asset = $rel.assets | Where-Object { $_.name -match '^ComfyUI_windows_portable_nvidia.*\.7z$' } | Select-Object -First 1
    if (-not $asset) { throw "ComfyUI portable paketi bulunamadı (release: $($rel.tag_name))." }
    Write-Host "Sürüm: $($rel.tag_name)  ($([math]::Round($asset.size/1GB,2)) GB)"
    $archive = Join-Path $InstallDir $asset.name
    Download $asset.browser_download_url $archive
    & $sevenZip x $archive "-o$InstallDir" -y | Out-Null
    if (-not (Test-Path "$portable\ComfyUI\main.py")) { throw "Arşiv açıldı ama ComfyUI bulunamadı." }
    Remove-Item $archive
} else { Write-Host "ComfyUI zaten kurulu: $portable" }
$py = "$portable\python_embeded\python.exe"
$pyw = "$portable\python_embeded\pythonw.exe"

Step "4) Eklentiler (ComfyUI-Manager, VideoHelperSuite)"
$nodes = "$portable\ComfyUI\custom_nodes"
foreach ($repo in @("ltdrdata/ComfyUI-Manager", "Kosinkadink/ComfyUI-VideoHelperSuite")) {
    $dir = Join-Path $nodes ($repo.Split("/")[1])
    if (-not (Test-Path $dir)) { git clone --depth 1 "https://github.com/$repo" $dir }
    else { git -C $dir pull --ff-only 2>$null | Out-Null }
    if (Test-Path "$dir\requirements.txt") { & $py -s -m pip install -q -r "$dir\requirements.txt" }
}

Step "5) Modeller"
$models = "$portable\ComfyUI\models"
if (-not $SkipModels) {
    Download "https://huggingface.co/Comfy-Org/stable-diffusion-v1-5-archive/resolve/main/v1-5-pruned-emaonly.safetensors" "$models\checkpoints\v1-5-pruned-emaonly.safetensors"
    Download "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" "$models\upscale_models\RealESRGAN_x4plus.pth"
    if ($SDXL) { Download "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" "$models\checkpoints\sd_xl_base_1.0.safetensors" }
} else { Write-Host "Atlandı." }

Step "6) Google Drive"
WingetInstall "Google.GoogleDrive" $null
function Find-MyDrive {
    foreach ($d in Get-PSDrive -PSProvider FileSystem) {
        foreach ($n in @("My Drive", "Drive'ım", "Mi unidad", "Meine Ablage")) {
            $p = Join-Path $d.Root $n
            if (Test-Path $p) { return $p }
        }
    }
    return $null
}
if (-not $ExchangeDir) {
    $md = Find-MyDrive
    if (-not $md) {
        Warn "Google Drive klasörü bulunamadı. Drive uygulamasını aç, Google hesabınla giriş yap (Mac'teki ile AYNI hesap)."
        Read-Host "Giriş yapıp Drive (G:) göründükten sonra Enter'a bas"
        $md = Find-MyDrive
    }
    if (-not $md) { throw "Drive yine bulunamadı. Script'i -ExchangeDir 'G:\My Drive\VFX_Exchange' ile çalıştır." }
    $ExchangeDir = Join-Path $md "VFX_Exchange"
}
foreach ($sub in @("to_comfy", "from_comfy", "requests")) { New-Item -ItemType Directory -Force -Path (Join-Path $ExchangeDir $sub) | Out-Null }
Write-Host "Exchange: $ExchangeDir"

Step "7) Köprü dosyaları ve ayarlar"
$bridge = Join-Path $InstallDir "bridge"
New-Item -ItemType Directory -Force -Path $bridge | Out-Null
foreach ($d in @("tools", "workflows", "resolve_scripts")) { Copy-Item -Recurse -Force "$Src\$d" $bridge }
Copy-Item -Force "$Src\CLAUDE.md", "$Src\README.md" $bridge -ErrorAction SilentlyContinue
$cfgDir = "$env:USERPROFILE\.comfy_vfx"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfgFile = "$cfgDir\config.json"
$cfg = [ordered]@{}
if (Test-Path $cfgFile) { (Get-Content $cfgFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $cfg[$_.Name] = $_.Value } }
$cfg["comfy_url"] = "http://127.0.0.1:8188"
$cfg["exchange_dir"] = $ExchangeDir.Replace('\', '/')
$cfg["ffmpeg"] = $(if ($ffmpeg) { $ffmpeg.Replace('\', '/') } else { "ffmpeg" })
$cfg["comfy_dir"] = $portable.Replace('\', '/')
$cfg["comfy_start"] = @($py.Replace('\', '/'), "-s", "ComfyUI/main.py", "--windows-standalone-build", "--listen", "127.0.0.1", "--port", "8188")
if (-not $cfg.Contains("comfy_idle_minutes")) { $cfg["comfy_idle_minutes"] = 15 }
if (-not $cfg.Contains("timeout_seconds")) { $cfg["timeout_seconds"] = 3600 }
if (-not $cfg.Contains("default_fps")) { $cfg["default_fps"] = 24 }
# BOM'suz UTF-8 yaz
[IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
Write-Host "Ayar: $cfgFile"

Step "8) Render worker'ı otomatik başlat (oturum açılışında, arka planda)"
$taskName = "ComfyVFX Render Worker"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$bridge\tools\render_worker.py`"" -WorkingDirectory $bridge
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName
Write-Host "Görev kuruldu ve başlatıldı: '$taskName'"

if (-not $AllowSleep) {
    Step "9) Fişteyken uyku kapatılıyor (render sırasında uyumasın)"
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
}

Step "10) Test: ComfyUI açılıyor ve kapanıyor"
$cv = "$bridge\tools\comfy_vfx.py"
$proc = Start-Process -FilePath $py -ArgumentList @("-s", "ComfyUI\main.py", "--windows-standalone-build", "--listen", "127.0.0.1", "--port", "8188") `
    -WorkingDirectory $portable -PassThru -WindowStyle Minimized
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep 2
    try { Invoke-RestMethod "http://127.0.0.1:8188/system_stats" -TimeoutSec 2 | Out-Null; $ok = $true; break } catch {}
}
if ($ok) {
    & $py $cv ping
    if (-not $SkipModels) {
        Write-Host "Örnek görsel üretiliyor (txt2img)..."
        & $py $cv run --workflow "$bridge\workflows\txt2img_sd15.json" --name kurulum_testi --set prompt="cinematic volumetric smoke, dark background" --no-mp4
    }
} else { Warn "ComfyUI 6 dakikada açılmadı. $portable\run_nvidia_gpu.bat ile elle açıp hatayı kontrol et." }
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue

Write-Host "`n=================== KURULUM TAMAM ===================" -ForegroundColor Green
Write-Host "ComfyUI : $portable   (worker gerektiğinde kendisi açar, $($cfg['comfy_idle_minutes']) dk boşta kalınca kapatır)"
Write-Host "Drive   : $ExchangeDir"
Write-Host "Log     : $cfgDir\worker.log"
Write-Host "Mac'te  : mac/setup_mac.sh çalıştır (aynı Google hesabı)."
Write-Host "Not     : Drive'da VFX_Exchange klasörüne sağ tık > 'Çevrimdışı kullanılabilir' yap (daha hızlı senkron)."
