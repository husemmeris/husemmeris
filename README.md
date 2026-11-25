# ComfyUI → DaVinci Resolve VFX Köprüsü (ücretsiz)

Claude Code'a Türkçe olarak "bu klibe ateş efekti ekle" dersin. Claude ComfyUI'de üretir, sonuç bulut
klasörüne (Google Drive) düşer, DaVinci Resolve'da tek tıkla Media Pool'a gelir.

```
 Sen ──► Claude Code (Windows) ──► comfy_vfx.py ──HTTP──► ComfyUI (kendi GPU'n  veya  Kaggle ücretsiz GPU)
                                         │
                                         ▼
                        Google Drive / VFX_Exchange / from_comfy / <iş>/ (PNG dizisi + job.json)
                                         │  (senkron, ücretsiz 15 GB)
                                         ▼
           DaVinci Resolve ► Workspace ► Scripts ► "ComfyUI Import"  ──►  "ComfyUI VFX" bin'i

 Ters yön: Resolve ► Scripts ► "ComfyUI Send Timeline Range" ──► VFX_Exchange/to_comfy/*.mp4 ──► Claude/ComfyUI
```

## Maliyet: 0 TL
| Parça | Ücretsiz seçenek |
|---|---|
| Video düzenleme | DaVinci Resolve (ücretsiz sürüm) |
| AI üretim | ComfyUI (açık kaynak) + SD 1.5 / SDXL / açık modeller |
| GPU | Kendi NVIDIA kartın (6 GB+ VRAM) **veya** Kaggle (haftada ~30 saat ücretsiz T4) |
| Bulut aktarım | Google Drive for Desktop (15 GB ücretsiz) — istersen Syncthing/OneDrive da olur |
| Araçlar | Python, ffmpeg (ücretsiz) |

Tek ücretli kısım: Claude Code'u kullanmak için bir Claude aboneliği gerekir (zaten kullanıyorsun).

## Kurulum (Windows)
1. **DaVinci Resolve** (ücretsiz) kur.
2. **ComfyUI**: [ComfyUI Desktop / Portable](https://github.com/comfyanonymous/ComfyUI) indir, çalıştır
   (varsayılan adres `http://127.0.0.1:8188`). Bir checkpoint koy: `models/checkpoints/v1-5-pruned-emaonly.safetensors`.
   *GPU'n zayıfsa:* `cloud/ComfyUI_Kaggle_Tunnel.ipynb` dosyasını Kaggle'da aç, çıkan `https://...trycloudflare.com` adresini kullan.
3. **Google Drive for Desktop** kur (bulut aktarım için; aynı PC'de çalışacaksan şart değil).
4. **Claude Code**'u kur: PowerShell'de `irm https://claude.ai/install.ps1 | iex` (veya Claude Desktop uygulaması).
5. Bu repoyu klonla ve kurulum script'ini çalıştır:
   ```powershell
   git clone https://github.com/husemmeris/husemmeris.git
   cd husemmeris
   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
   ```
   Script: Python/ffmpeg kontrol eder, `VFX_Exchange` klasörünü Google Drive'da açar,
   `%USERPROFILE%\.comfy_vfx\config.json` yazar, Resolve script'lerini kopyalar.
6. Resolve'u yeniden başlat. **Workspace > Scripts** altında iki script görünür.
   (Resolve script'leri için Python 3 kurulu olmalı — setup bunu kontrol eder.)

## Kullanım
Repo klasöründe `claude` yaz ve konuş:

> "Resolve'dan to_comfy'ye attığım son klibe sinematik duman ve kıvılcım efekti ver, önce 5 karelik test yap."

> "1920x1080'e yakın, gün batımında fütüristik bir şehir matte painting'i üret."

> "Bu PNG'yi 4x upscale et."

Claude `CLAUDE.md`'deki talimatlarla doğru workflow'u seçer, çalıştırır; bitince Resolve'da
**Workspace > Scripts > ComfyUI Import** de. Görüntü dizileri tek klip olarak, prompt bilgisi klip yorumunda gelir.

Elle de kullanabilirsin:
```powershell
python tools\comfy_vfx.py ping
python tools\comfy_vfx.py run --workflow workflows\img2img_sd15.json --input klip.mp4 --per-frame --seed 42 --set prompt="fire, embers" --max-frames 5
python tools\comfy_vfx.py watch --workflow workflows\img2img_sd15.json --per-frame --seed 42 --set prompt="..."   # to_comfy'yi otomatik işler
```

## Kendi workflow'ların
ComfyUI'de istediğin workflow'u kur (AnimateDiff, ControlNet, rotoscope/arka plan silme, relight...),
**Workflow > Export (API)** ile `workflows/` içine kaydet. Değişmesini istediğin değerleri `{{prompt}}`, `{{input}}`,
`{{seed}}` gibi yer tutucularla değiştir ya da Claude'a "bu workflow'u şablona çevir" de.
Video çıktı veren node'lar (ör. VideoHelperSuite) da desteklenir — history'deki her çıktı indirilir.

## Sınırlar (dürüstçe)
- Resolve **ücretsiz** sürümü dışarıdan script ile kontrol edilemez; bu yüzden içe alma, Resolve menüsünden tek tıkla yapılır.
  Resolve Studio'da aynı script'ler harici olarak da çalıştırılabilir.
- Kare kare işleme (`--per-frame`) basit ve sağlamdır ama titreme olabilir; sabit seed ve düşük `denoise` (0.3–0.5) kullan.
  Daha tutarlı video için AnimateDiff/video modelli workflow'lar ekle.
- Kaggle oturum adresi her seferinde değişir ve haftalık GPU kotası vardır.

## Dosyalar
- `tools/comfy_vfx.py` — ComfyUI API istemcisi (yalnızca standart Python)
- `workflows/` — `img2img_sd15`, `txt2img_sd15`, `upscale_model` (sadece çekirdek ComfyUI node'ları)
- `resolve_scripts/` — Resolve'da çalışan içe alma / dışa gönderme script'leri
- `windows/setup.ps1` — Windows kurulumu
- `cloud/ComfyUI_Kaggle_Tunnel.ipynb` — ücretsiz bulut GPU'da ComfyUI
- `CLAUDE.md` — Claude Code'un bu sistemi nasıl kullanacağı
