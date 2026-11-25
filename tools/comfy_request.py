#!/usr/bin/env python3
"""
comfy_request.py - Mac'ten (veya herhangi bir makineden) Windows render makinesine iş gönderir.
Google Drive üzerinden çalışır; iki bilgisayarın aynı ağda olması gerekmez.

  python3 comfy_request.py --workflow img2img_sd15 --input ~/Desktop/klip.mp4 --per-frame --seed 42 \
        --set prompt="cinematic smoke, embers" --wait
  python3 comfy_request.py status            # son işler + worker çevrimiçi mi
  python3 comfy_request.py --workflow txt2img_sd15 --set prompt="matte painting" --wait

Sonuç: VFX_Exchange/from_comfy/<iş>/  ->  Resolve'da Workspace > Scripts > ComfyUI Import
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comfy_vfx import coerce, exchange_dirs, load_config, safe_name  # noqa: E402


def worker_state(root: Path) -> str:
    hb = root / "worker_heartbeat.json"
    if not hb.exists():
        return "worker hiç görülmedi (Windows'ta kurulum yapıldı mı?)"
    try:
        d = json.loads(hb.read_text(encoding="utf-8-sig"))
    except Exception:
        return "heartbeat okunamadı"
    age = time.time() - d.get("epoch", 0)
    tag = "ÇEVRİMİÇİ" if age < 300 else "ÇEVRİMDIŞI?"
    return f"{tag} - {d.get('worker')} son görülme {d.get('last_seen')} (Drive gecikmesi olabilir)"


def submit(root: Path, a) -> Path:
    req_dir = root / "requests"
    req_dir.mkdir(exist_ok=True)
    rid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    req = {"id": rid, "workflow": a.workflow, "set": {}, "per_frame": a.per_frame,
           "every": a.every, "max_frames": a.max_frames, "name": a.name}
    if a.seed is not None:
        req["seed"] = a.seed
    for s in a.set or []:
        k, v = s.split("=", 1)
        req["set"][k] = coerce(v)
    if a.input:
        src = Path(a.input).expanduser().resolve()
        try:
            rel = src.relative_to(root)  # zaten Drive klasöründe
        except ValueError:
            dst = root / "to_comfy" / f"{rid}_{safe_name(src.stem)}{src.suffix.lower()}"
            print(f"Drive'a kopyalanıyor: {dst.name}")
            shutil.copy2(src, dst)
            rel = dst.relative_to(root)
        req["input"] = rel.as_posix()
        req["name"] = req["name"] or src.stem
    path = req_dir / f"{rid}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(req, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    print(f"İstek gönderildi: {rid}")
    return req_dir / f"{rid}.status.json"


def wait(status_file: Path, timeout: float):
    start, last = time.time(), None
    while time.time() - start < timeout:
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8-sig"))
            except Exception:
                st = None
            if st:
                cur = (st["state"], st.get("progress"))
                if cur != last:
                    print(f"  durum: {st['state']} {st.get('progress') or ''}", flush=True)
                    last = cur
                if st["state"] == "done":
                    print(f"HAZIR -> {st['output']}\nResolve: Workspace > Scripts > ComfyUI Import")
                    return 0
                if st["state"] == "error":
                    print("HATA: " + st.get("error", ""))
                    return 1
        time.sleep(3)
    print("Bekleme süresi doldu; iş arka planda sürüyor olabilir ('status' ile bak).")
    return 2


def main():
    p = argparse.ArgumentParser(description="Windows render makinesine iş gönder")
    p.add_argument("cmd", nargs="?", default="submit", choices=["submit", "status"])
    p.add_argument("--workflow", help="workflows/ içindeki ad, ör. img2img_sd15")
    p.add_argument("--input")
    p.add_argument("--name")
    p.add_argument("--set", action="append")
    p.add_argument("--per-frame", action="store_true")
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--max-frames", type=int, default=0)
    p.add_argument("--seed", type=int)
    p.add_argument("--wait", action="store_true", help="bitene kadar bekle")
    p.add_argument("--timeout", type=float, default=6 * 3600)
    a = p.parse_args()
    root = exchange_dirs(load_config())[0].parent
    print("Worker: " + worker_state(root))
    if a.cmd == "status":
        files = sorted((root / "requests").glob("*.status.json"), key=lambda f: f.stat().st_mtime)[-10:]
        pending = [f.name for f in (root / "requests").glob("*.json")
                   if not f.name.endswith(".status.json")]
        print(f"Kuyrukta bekleyen: {len(pending)}")
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            print(f"  {d['id']}: {d['state']} {d.get('progress') or ''} {d.get('output') or d.get('error') or ''}")
        return
    if not a.workflow:
        p.error("--workflow gerekli")
    sf = submit(root, a)
    if a.wait:
        sys.exit(wait(sf, a.timeout))


if __name__ == "__main__":
    main()
