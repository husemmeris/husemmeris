# Mac'te DaVinci + Windows'ta ComfyUI render makinesi (Google Drive üzerinden, ücretsiz)

Mac'te DaVinci Resolve'da çalışırken bir efekt istersin. Windows bilgisayar işi alır, ComfyUI'de render eder,
sonucu Google Drive üzerinden Mac'e gönderir. İki bilgisayarın aynı ağda olması gerekmez.

```
 MAC (DaVinci Resolve)                         GOOGLE DRIVE / VFX_Exchange                  WINDOWS (render PC)
 ─────────────────────                         ───────────────────────────                  ───────────────────
 Scripts > ComfyUI Request ── In/Out render ──► to_comfy/klip.mp4
            (prompt penceresi) ── iş isteği ──► requests/<id>.json  ──────────────────────► render_worker (arka planda)
                                                                                              │ ComfyUI kapalıysa açar
                                                                                              │ kare kare render
                                               from_comfy/<iş>/frame_*.png + job.json ◄──────┘ 15 dk boşta kalınca kapatır
 Scripts > ComfyUI Import ◄─────────────────── (senkron)
   └► "ComfyUI VFX" bin'i                      requests/<id>.status.json (ilerleme: 12/48 ...)
```

## Maliyet: 0 TL
DaVinci Resolve (ücretsiz), ComfyUI ve açık modeller, Google Drive (15 GB ücretsiz), Python, ffmpeg.

## 1) Windows (render bilgisayarı)
Gerekenler: NVIDIA ekran kartı (6 GB+ VRAM önerilir), modeller için ~15 GB boş yer.

1. Zip'i aç (ör. `C:\Users\sen\Downloads\comfy-davinci-vfx`).
2. Zip'teki **`KUR_WINDOWS.bat`** dosyasına çift tıkla ve yönetici iznini onayla. Her şey **X:\ComfyVFX** klasörüne kurulur.
   Elle çalıştırmak ya da başka bir disk seçmek istersen yönetici PowerShell'de:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\install_render_pc.ps1 -InstallDir X:\ComfyVFX
   ```
   Kurulum sırası:
   - 7-Zip, Git, ffmpeg ve Google Drive'ı kurar (winget ile).
   - **ComfyUI portable**'ın (NVIDIA) son sürümünü `X:\ComfyVFX` altına kurar (X: yoksa C:). ComfyUI-Manager ve VideoHelperSuite eklentilerini ekler.
   - SD 1.5 ve RealESRGAN x4 modellerini indirir. SDXL de istersen `-SDXL` ekle.
   - Google Drive'a giriş yapmanı bekler. **Mac'teki ile aynı Google hesabı** olmalı.
   - **Render worker**'ı Görev Zamanlayıcı'ya ekler. Worker her oturum açılışında arka planda kendiliğinden başlar.
   - Fişteyken uykuyu kapatır. İstemezsen `-AllowSleep` ekle.
   - ComfyUI'yi açıp bir test görseli üretir ve tekrar kapatır.
3. Bitti. Windows açık ve oturum açık kaldığı sürece istekleri işler.

## 2) Mac (DaVinci tarafı)
1. [Google Drive for Desktop](https://www.google.com/drive/download/) kur ve aynı hesapla giriş yap.
2. Resolve script'leri için [Python 3](https://www.python.org/downloads/macos/) kur (python.org sürümü).
3. Terminal'de:
   ```bash
   cd ~/Downloads/comfy-davinci-vfx
   bash mac/setup_mac.sh
   ```
4. Resolve'u yeniden başlat.
5. İpucu: Finder'da `VFX_Exchange` klasörüne sağ tık > **Çevrimdışı kullanılabilir**. Böylece dosyalar hemen iner.

## Kullanım (Mac'te)
1. Timeline'da efekt istediğin aralığı **I** ve **O** ile işaretle. Kısa tut, her kare ayrı render edilir.
2. **Workspace > Scripts > ComfyUI Request (Windows Render)**
   - Workflow'u seç, prompt'u yaz (ör. `thick cinematic smoke, glowing embers`).
   - Önce **Test kare = 5** ile dene. İyiyse 0 yap (tüm aralık).
   - **Denoise**: 0.3 hafif değişim, 0.6+ güçlü değişim.
3. Windows render alır. Durumu görmek ya da sonucu almak için **Workspace > Scripts > ComfyUI Import** çalıştır.
   Biten işler "ComfyUI VFX" bin'ine düşer, devam edenler ilerlemesiyle listelenir.

Terminal'den veya Mac'teki Claude Code'dan da iş gönderebilirsin:
```bash
python3 ~/.comfy_vfx/tools/comfy_request.py --workflow txt2img_sd15 --set prompt="matte painting, city at dusk" --wait
python3 ~/.comfy_vfx/tools/comfy_request.py --workflow upscale_model --input ~/Desktop/kare.png --wait
python3 ~/.comfy_vfx/tools/comfy_request.py status      # worker çevrimiçi mi, kuyruk ne durumda
```

## Hazır workflow'lar
| Ad | Ne yapar | Girdi |
|---|---|---|
| `img2img_sd15` | Kareyi prompt'a göre dönüştürür (duman, ateş, stil, atmosfer) | Timeline aralığı / görsel |
| `txt2img_sd15` | Sıfırdan plate, arka plan, matte painting, doku üretir | Yok |
| `upscale_model` | 4x AI büyütme | Timeline aralığı / görsel |

Yeni workflow eklemek için ComfyUI'de kur (Windows'ta `X:\ComfyVFX\ComfyUI_windows_portable\run_nvidia_gpu.bat` ile aç).
Sonra **Workflow > Export (API)** ile `X:\ComfyVFX\bridge\workflows\` içine kaydet. Değişecek değerleri `{{prompt}}`,
`{{input}}`, `{{seed}}` ile değiştir. Worker'ı yeniden başlatınca (ya da Windows'u yeniden açınca) Mac'teki listede görünür.

## Sorun giderme
- **Worker log'u** (Windows): `%USERPROFILE%\.comfy_vfx\worker.log`. **ComfyUI log'u**: `comfyui.log`.
- **Worker'ı yeniden başlatmak** (Windows PowerShell):
  `Stop-ScheduledTask "ComfyVFX Render Worker"; Start-ScheduledTask "ComfyVFX Render Worker"`
- **"Worker çevrimdışı" uyarısı**: Windows kapalı, uykuda ya da Drive senkronu durmuş olabilir. İstek kaybolmaz, kuyrukta bekler.
- **Gecikme**: Drive senkronu genelde birkaç saniye ile 1 dakika arasında sürer. Büyük kliplerde yükleme süresi eklenir.
- **Kareler arası titreme**: sabit seed kullan, denoise'u düşür (0.3–0.45). Daha akıcı sonuç için ileride AnimateDiff workflow'u eklenebilir.

## Dosyalar
- `windows/install_render_pc.ps1`: Windows render bilgisayarı kurulumu.
- `mac/setup_mac.sh`: Mac kurulumu.
- `tools/render_worker.py`: Windows'ta Drive kuyruğunu işleyen worker. ComfyUI'yi gerektiğinde açar ve kapatır.
- `tools/comfy_request.py`: Mac'ten iş gönderme ve durum sorgulama.
- `tools/comfy_vfx.py`: ComfyUI API istemcisi. Yalnızca standart Python kullanır.
- `resolve_scripts/`: Resolve menü script'leri (Request, Import, Send Timeline Range).
- `workflows/`: ComfyUI workflow şablonları.
- `cloud/ComfyUI_Kaggle_Tunnel.ipynb`: Windows'ta GPU yoksa ücretsiz bulut GPU seçeneği.
- `windows/setup.ps1`: eski tek bilgisayar kurulumu. ComfyUI ve Resolve aynı PC'deyse kullanılır.
