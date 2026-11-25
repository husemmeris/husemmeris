#!/bin/bash
# Mac (DaVinci Resolve tarafı) kurulumu
#   Zip'i aç, Terminal'de klasöre gir:   bash mac/setup_mac.sh
#   Drive klasörü bulunamazsa:            bash mac/setup_mac.sh "/Users/sen/Library/CloudStorage/GoogleDrive-xxx/My Drive/VFX_Exchange"
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
EXCHANGE="$1"

echo "== 1) Google Drive klasörü"
if [ -z "$EXCHANGE" ]; then
  for base in "$HOME"/Library/CloudStorage/GoogleDrive-*; do
    for n in "My Drive" "Drive'ım" "Mi unidad" "Meine Ablage"; do
      if [ -d "$base/$n" ]; then EXCHANGE="$base/$n/VFX_Exchange"; break 2; fi
    done
  done
fi
if [ -z "$EXCHANGE" ]; then
  echo "Google Drive for Desktop bulunamadı."
  echo "  https://www.google.com/drive/download/ adresinden kur, Windows'takiyle AYNI hesapla giriş yap,"
  echo "  sonra bu script'i tekrar çalıştır."
  exit 1
fi
mkdir -p "$EXCHANGE/to_comfy" "$EXCHANGE/from_comfy" "$EXCHANGE/requests"
echo "Exchange: $EXCHANGE"

echo "== 2) Ayar dosyası (~/.comfy_vfx/config.json)"
mkdir -p "$HOME/.comfy_vfx"
python3 - "$EXCHANGE" <<'PY' 2>/dev/null || cat > "$HOME/.comfy_vfx/config.json" <<EOF
import json, os, sys
p = os.path.expanduser("~/.comfy_vfx/config.json")
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg["exchange_dir"] = sys.argv[1]
cfg.setdefault("request_defaults", {"workflow": "img2img_sd15", "per_frame": True, "seed": 42,
                                    "max_frames": 0, "denoise": 0.45, "prompt": ""})
json.dump(cfg, open(p, "w"), indent=2, ensure_ascii=False)
PY
{"exchange_dir": "$EXCHANGE", "request_defaults": {"workflow": "img2img_sd15", "per_frame": true, "seed": 42, "max_frames": 0, "denoise": 0.45, "prompt": ""}}
EOF
cat "$HOME/.comfy_vfx/config.json"

echo "== 3) Komut satırı aracı (~/.comfy_vfx/tools)"
mkdir -p "$HOME/.comfy_vfx/tools"
cp "$SRC/tools/comfy_vfx.py" "$SRC/tools/comfy_request.py" "$HOME/.comfy_vfx/tools/"

echo "== 4) DaVinci Resolve script'leri"
DEST="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
mkdir -p "$DEST"
cp "$SRC/resolve_scripts/"*.py "$DEST/"
ls "$DEST"

echo "== 5) Python kontrolü (Resolve script'leri için gerekli)"
if [ -d "/Library/Frameworks/Python.framework/Versions" ]; then
  echo "python.org Python bulundu: $(ls /Library/Frameworks/Python.framework/Versions | grep -v Current | tr '\n' ' ')"
else
  echo "UYARI: Resolve, python.org'dan kurulan Python 3'ü arar. Script'ler menüde çalışmazsa"
  echo "       https://www.python.org/downloads/macos/ adresinden Python 3.12 kur ve Resolve'u yeniden başlat."
fi

echo "== 6) Windows worker durumu"
python3 "$HOME/.comfy_vfx/tools/comfy_request.py" status || true

cat <<'TXT'

=================== MAC KURULUMU TAMAM ===================
Resolve'u yeniden başlat. Workspace > Scripts altında:
  • ComfyUI Request (Windows Render) -> In/Out aralığını Windows'a gönderir, prompt sorar
  • ComfyUI Import                   -> biten işleri "ComfyUI VFX" bin'ine alır
  • ComfyUI Send Timeline Range      -> sadece render alıp to_comfy'ye koyar

Terminal'den (veya Mac'teki Claude Code'dan):
  python3 ~/.comfy_vfx/tools/comfy_request.py --workflow txt2img_sd15 --set prompt="fire explosion" --wait
  python3 ~/.comfy_vfx/tools/comfy_request.py status

İpucu: Finder'da VFX_Exchange'e sağ tık > "Çevrimdışı kullanılabilir" -> Resolve dosyaları beklemeden açar.
TXT
