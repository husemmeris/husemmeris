#!/usr/bin/env python3
"""
comfy_vfx.py - ComfyUI <-> DaVinci Resolve köprüsü (yalnızca Python standart kütüphanesi).

Claude Code (veya sen) bu aracı çalıştırır:
  1. Workflow JSON'unu (ComfyUI "Export (API)" formatı) yükler,
  2. {{prompt}}, {{input}}, {{seed}} gibi yer tutucuları doldurur,
  3. ComfyUI sunucusuna (yerel veya bulut tüneli) gönderir, bitmesini bekler,
  4. Çıktıları exchange klasörüne (ör. Google Drive) from_comfy/<iş_adı>/ altına indirir,
  5. job.json manifest'i yazar -> DaVinci'deki "ComfyUI Import" script'i bunu içe alır.

Komutlar:
  python comfy_vfx.py ping
  python comfy_vfx.py run  --workflow workflows/img2img_sd15.json --input shot.png --set prompt="fire explosion"
  python comfy_vfx.py run  --workflow workflows/img2img_sd15.json --input clip.mp4 --per-frame --set prompt="..."
  python comfy_vfx.py watch --workflow workflows/img2img_sd15.json --per-frame --set prompt="..."
  python comfy_vfx.py placeholders --workflow workflows/img2img_sd15.json
"""
from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".mxf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".exr", ".tif", ".tiff", ".bmp"}

DEFAULT_CONFIG = {
    "comfy_url": "http://127.0.0.1:8188",
    "exchange_dir": str(Path.home() / "VFX_Exchange"),
    "poll_seconds": 1.5,
    "timeout_seconds": 3600,
    "ffmpeg": "ffmpeg",
    "default_fps": 24,
}


# --------------------------------------------------------------------------- config
def config_path() -> Path:
    env = os.environ.get("COMFY_VFX_CONFIG")
    if env:
        return Path(env)
    return Path.home() / ".comfy_vfx" / "config.json"


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    p = config_path()
    if p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8-sig")))
    if os.environ.get("COMFY_URL"):
        cfg["comfy_url"] = os.environ["COMFY_URL"]
    cfg["comfy_url"] = cfg["comfy_url"].rstrip("/")
    return cfg


def exchange_dirs(cfg: dict) -> tuple[Path, Path]:
    root = Path(os.path.expandvars(os.path.expanduser(cfg["exchange_dir"])))
    to_comfy, from_comfy = root / "to_comfy", root / "from_comfy"
    to_comfy.mkdir(parents=True, exist_ok=True)
    from_comfy.mkdir(parents=True, exist_ok=True)
    return to_comfy, from_comfy


# --------------------------------------------------------------------------- HTTP
class Comfy:
    def __init__(self, url: str):
        self.url = url
        self.client_id = uuid.uuid4().hex

    def _req(self, path: str, data: bytes | None = None, headers: dict | None = None, timeout=60):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise SystemExit(f"ComfyUI HTTP {e.code} {path}: {body[:2000]}")
        except urllib.error.URLError as e:
            raise SystemExit(f"ComfyUI'ye ulaşılamadı ({self.url}): {e.reason}. Sunucu açık mı?")

    def get_json(self, path: str):
        return json.loads(self._req(path))

    def system_stats(self):
        return self.get_json("/system_stats")

    def upload(self, file: Path) -> str:
        """Dosyayı ComfyUI input klasörüne yükler, workflow'da kullanılacak adı döndürür."""
        boundary = "----comfyvfx" + uuid.uuid4().hex
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{file.name}\"\r\n"
             f"Content-Type: {ctype}\r\n\r\n").encode(),
            file.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        res = json.loads(self._req("/upload/image", b"".join(parts),
                                   {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                   timeout=600))
        name = res["name"]
        return f"{res['subfolder']}/{name}" if res.get("subfolder") else name

    def queue(self, workflow: dict) -> str:
        body = json.dumps({"prompt": workflow, "client_id": self.client_id}).encode()
        res = json.loads(self._req("/prompt", body, {"Content-Type": "application/json"}))
        if res.get("node_errors"):
            raise SystemExit("Workflow hatası: " + json.dumps(res["node_errors"], indent=2)[:3000])
        return res["prompt_id"]

    def wait(self, prompt_id: str, poll: float, timeout: float) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            hist = self.get_json(f"/history/{prompt_id}")
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise SystemExit("ComfyUI çalıştırma hatası: " + json.dumps(msgs, indent=2)[:3000])
                if status.get("completed", True):
                    return entry
            time.sleep(poll)
        raise SystemExit(f"Zaman aşımı ({timeout}s): {prompt_id}")

    def download(self, item: dict, dest: Path):
        q = urllib.parse.urlencode({"filename": item["filename"],
                                    "subfolder": item.get("subfolder", ""),
                                    "type": item.get("type", "output")})
        dest.write_bytes(self._req(f"/view?{q}", timeout=600))


def output_items(history_entry: dict) -> list[dict]:
    """Tüm node çıktılarındaki dosyaları toplar (SaveImage 'images', VHS 'gifs', vb.)."""
    items = []
    for node_id, out in sorted(history_entry.get("outputs", {}).items(), key=lambda kv: kv[0]):
        for key, val in out.items():
            if isinstance(val, list):
                for it in val:
                    if isinstance(it, dict) and "filename" in it and it.get("type", "output") == "output":
                        items.append(it)
    return items


# --------------------------------------------------------------------------- workflow templating
PH = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def coerce(v: str):
    for t in (int, float):
        try:
            return t(v)
        except ValueError:
            pass
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def fill(obj, values: dict):
    if isinstance(obj, dict):
        return {k: fill(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fill(v, values) for v in obj]
    if isinstance(obj, str):
        m = PH.fullmatch(obj.strip())
        if m and m.group(1) in values:
            return values[m.group(1)]  # tip korunur (int seed vb.)
        return PH.sub(lambda mm: str(values.get(mm.group(1), mm.group(0))), obj)
    return obj


def find_placeholders(obj, acc=None) -> set:
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for v in obj.values():
            find_placeholders(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            find_placeholders(v, acc)
    elif isinstance(obj, str):
        acc.update(PH.findall(obj))
    return acc


def load_workflow(path: Path) -> dict:
    wf = json.loads(path.read_text(encoding="utf-8-sig"))
    if "nodes" in wf and "links" in wf:
        raise SystemExit(f"{path} UI formatında. ComfyUI'de Workflow > Export (API) ile kaydet.")
    meta = wf.pop("_meta_comfy_vfx", {}) or {}
    return wf, dict(meta.get("defaults", {}))


def apply_sets(wf: dict, values: dict, sets: list[str]):
    """--set key=value  -> {{key}} ; --set 6.inputs.text=value -> doğrudan node alanı."""
    for s in sets:
        if "=" not in s:
            raise SystemExit(f"--set biçimi key=value olmalı: {s}")
        k, v = s.split("=", 1)
        if re.fullmatch(r"\d+\.inputs\.[\w.]+", k):
            node, _, field = k.split(".", 2)
            if node not in wf:
                raise SystemExit(f"Node {node} workflow'da yok")
            wf[node]["inputs"][field] = coerce(v)
        else:
            values[k] = coerce(v)


# --------------------------------------------------------------------------- ffmpeg helpers
def probe_fps(cfg, video: Path) -> float:
    ffprobe = str(Path(cfg["ffmpeg"]).with_name("ffprobe")) if os.sep in cfg["ffmpeg"] else "ffprobe"
    try:
        out = subprocess.check_output([ffprobe, "-v", "error", "-select_streams", "v:0",
                                       "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0",
                                       str(video)], text=True).strip()
        n, d = out.split("/")
        return round(float(n) / float(d), 3)
    except Exception:
        return float(cfg["default_fps"])


def extract_frames(cfg, video: Path, out_dir: Path, every: int = 1, max_frames: int = 0) -> list[Path]:
    if not shutil.which(cfg["ffmpeg"]) and not Path(cfg["ffmpeg"]).exists():
        raise SystemExit("ffmpeg bulunamadı. Windows: winget install Gyan.FFmpeg")
    vf = [f"select='not(mod(n\\,{every}))'"] if every > 1 else []
    cmd = [cfg["ffmpeg"], "-v", "error", "-y", "-i", str(video)]
    if vf:
        cmd += ["-vf", ",".join(vf), "-vsync", "0"]
    if max_frames:
        cmd += ["-frames:v", str(max_frames)]
    cmd += [str(out_dir / "src_%05d.png")]
    subprocess.check_call(cmd)
    return sorted(out_dir.glob("src_*.png"))


def encode_preview(cfg, frames_pattern: Path, fps: float, out: Path):
    try:
        subprocess.check_call([cfg["ffmpeg"], "-v", "error", "-y", "-framerate", str(fps),
                               "-i", str(frames_pattern), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                               "-crf", "16", str(out)])
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- core job logic
def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")[:60] or "job"


def run_once(comfy: Comfy, cfg: dict, wf_tpl: dict, values: dict) -> list[tuple[dict, bytes | None]]:
    wf = fill(copy.deepcopy(wf_tpl), values)
    left = find_placeholders(wf)
    if left:
        raise SystemExit(f"Doldurulmamış yer tutucular: {sorted(left)}  (--set ile ver)")
    pid = comfy.queue(wf)
    print(f"  kuyruğa alındı: {pid}", flush=True)
    entry = comfy.wait(pid, cfg["poll_seconds"], cfg["timeout_seconds"])
    return output_items(entry)


def render_frames(cfg, comfys: list, wf_tpl: dict, values: dict, frames: list[Path], out_dir: Path,
                  progress=None) -> str:
    """Kareleri tüm ComfyUI örneklerine (her GPU'da bir tane) paylaştırır."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock, done, exts = threading.Lock(), [0], set()
    todo = list(enumerate(frames, 1))

    def worker(gi: int, comfy: Comfy):
        vals = dict(values)
        vals["prefix"] = f"{values.get('prefix', 'comfy_vfx')}_g{gi}"  # GPU'lar aynı dosyaya yazmasın
        while True:
            with lock:
                if not todo:
                    return
                i, fr = todo.pop(0)
            vals["input"] = comfy.upload(fr)
            items = [it for it in run_once(comfy, cfg, wf_tpl, vals)
                     if Path(it["filename"]).suffix.lower() in IMAGE_EXT]
            if not items:
                raise SystemExit("Workflow görüntü çıktısı vermedi (SaveImage node'u var mı?)")
            ext = Path(items[-1]["filename"]).suffix.lower()
            comfy.download(items[-1], out_dir / f"frame_{i:05d}{ext}")
            with lock:
                exts.add(ext)
                done[0] += 1
                print(f"[{done[0]}/{len(frames)}] kare {i} (GPU örneği {gi})", flush=True)
                if progress:
                    progress(done[0], len(frames))

    if len(comfys) > 1:
        print(f"{len(comfys)} ComfyUI örneğine paylaştırılıyor", flush=True)
    with ThreadPoolExecutor(len(comfys)) as ex:
        futs = [ex.submit(worker, gi, c) for gi, c in enumerate(comfys)]
        for f in futs:
            f.result()  # hata varsa yükselt
    if len(exts) != 1:
        raise SystemExit(f"Karışık çıktı uzantıları: {exts}")
    return exts.pop()


def run_job(cfg: dict, workflow: Path, inp: Path | None, sets: list[str], name: str | None,
            per_frame: bool, every: int, max_frames: int, seed: int | None, mp4: bool,
            progress=None, urls: list[str] | None = None) -> Path:
    urls = urls or cfg.get("comfy_urls") or [cfg["comfy_url"]]
    comfys = [Comfy(u) for u in urls]
    comfy = comfys[0]
    _, from_comfy = exchange_dirs(cfg)
    wf_tpl, values = load_workflow(workflow)
    apply_sets(wf_tpl, values, sets)
    values.setdefault("seed", seed if seed is not None else random.randint(0, 2**31 - 1))
    values.setdefault("prefix", "comfy_vfx")

    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = name or (inp.stem if inp else workflow.stem)
    job_dir = from_comfy / f"{stamp}_{safe_name(base)}"
    n = 2
    while job_dir.exists() or job_dir.with_name(job_dir.name + ".partial").exists():
        job_dir = from_comfy / f"{stamp}_{safe_name(base)}_{n}"
        n += 1
    tmp_dir = job_dir.with_name(job_dir.name + ".partial")
    tmp_dir.mkdir(parents=True)

    fps = float(cfg["default_fps"])
    manifest = {"name": base, "workflow": workflow.name, "created": stamp,
                "values": {k: v for k, v in values.items() if k != "input"},
                "source": str(inp) if inp else None}

    if inp and per_frame and inp.suffix.lower() in VIDEO_EXT:
        fps = probe_fps(cfg, inp) / max(every, 1)
        with tempfile.TemporaryDirectory() as td:
            frames = extract_frames(cfg, inp, Path(td), every, max_frames)
            print(f"{len(frames)} kare işlenecek ({fps} fps)", flush=True)
            ext = render_frames(cfg, comfys, wf_tpl, values, frames, tmp_dir, progress)
        manifest.update(type="sequence", pattern=f"frame_%05d{ext}", start=1, end=len(frames), fps=fps)
    else:
        if inp:
            values["input"] = comfy.upload(inp)
            print(f"yüklendi: {values['input']}", flush=True)
        items = run_once(comfy, cfg, wf_tpl, values)
        if not items:
            raise SystemExit("Workflow hiç çıktı üretmedi.")
        imgs = [it for it in items if Path(it["filename"]).suffix.lower() in IMAGE_EXT]
        others = [it for it in items if it not in imgs]
        files = []
        if len(imgs) > 1:  # batch -> görüntü dizisi
            ext = Path(imgs[0]["filename"]).suffix.lower()
            for i, it in enumerate(imgs, 1):
                comfy.download(it, tmp_dir / f"frame_{i:05d}{ext}")
            manifest.update(type="sequence", pattern=f"frame_%05d{ext}", start=1, end=len(imgs), fps=fps)
        else:
            manifest["type"] = "files"
            for it in imgs + others:
                dst = tmp_dir / Path(it["filename"]).name
                comfy.download(it, dst)
                files.append(dst.name)
            manifest["files"] = files

    if manifest["type"] == "sequence" and mp4:
        if encode_preview(cfg, tmp_dir / manifest["pattern"], manifest["fps"], tmp_dir / "preview.mp4"):
            manifest["preview"] = "preview.mp4"

    (tmp_dir / "job.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_dir.rename(job_dir)  # atomik: Resolve yarım işi görmez
    print(f"HAZIR -> {job_dir}", flush=True)
    return job_dir


# --------------------------------------------------------------------------- commands
def cmd_ping(cfg, _a):
    s = Comfy(cfg["comfy_url"]).system_stats()
    print(json.dumps({"comfy_url": cfg["comfy_url"],
                      "comfyui": s.get("system", {}).get("comfyui_version"),
                      "devices": [d.get("name") for d in s.get("devices", [])],
                      "exchange_dir": str(exchange_dirs(cfg)[0].parent)}, indent=2, ensure_ascii=False))


def cmd_placeholders(_cfg, a):
    wf = json.loads(Path(a.workflow).read_text(encoding="utf-8-sig"))
    meta = wf.get("_meta_comfy_vfx", {})
    print(json.dumps({"placeholders": sorted(find_placeholders(load_workflow(Path(a.workflow))[0])),
                      "info": meta}, indent=2, ensure_ascii=False))


def cmd_run(cfg, a):
    inp = Path(a.input) if a.input else None
    if inp and not inp.exists():
        raise SystemExit(f"Girdi yok: {inp}")
    run_job(cfg, Path(a.workflow), inp, a.set or [], a.name, a.per_frame, a.every,
            a.max_frames, a.seed, not a.no_mp4)


def cmd_watch(cfg, a):
    to_comfy, _ = exchange_dirs(cfg)
    done_dir = to_comfy / "_done"
    done_dir.mkdir(exist_ok=True)
    print(f"İzleniyor: {to_comfy}  (Ctrl+C ile çık)", flush=True)
    sizes: dict = {}
    while True:
        for f in sorted(to_comfy.iterdir()):
            if not f.is_file() or f.suffix.lower() not in VIDEO_EXT | IMAGE_EXT:
                continue
            sz = f.stat().st_size
            if sizes.get(f) != sz:  # hâlâ yazılıyor / senkronize oluyor
                sizes[f] = sz
                continue
            print(f"\nYeni dosya: {f.name}", flush=True)
            try:
                run_job(cfg, Path(a.workflow), f, a.set or [], f.stem, a.per_frame, a.every,
                        a.max_frames, a.seed, not a.no_mp4)
                shutil.move(str(f), done_dir / f.name)
            except SystemExit as e:
                print(f"HATA: {e}", flush=True)
                shutil.move(str(f), done_dir / (f.stem + ".FAILED" + f.suffix))
            sizes.pop(f, None)
        time.sleep(3)


def main(argv=None):
    p = argparse.ArgumentParser(description="ComfyUI <-> DaVinci Resolve VFX köprüsü")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="ComfyUI bağlantısını test et")
    ph = sub.add_parser("placeholders", help="workflow'daki {{yer_tutucular}}ı listele")
    ph.add_argument("--workflow", required=True)
    for nm in ("run", "watch"):
        sp = sub.add_parser(nm)
        sp.add_argument("--workflow", required=True)
        if nm == "run":
            sp.add_argument("--input", help="görüntü veya video (yoksa txt2img)")
            sp.add_argument("--name", help="iş/klip adı")
        sp.add_argument("--set", action="append", help="key=value veya 6.inputs.text=value")
        sp.add_argument("--per-frame", action="store_true", help="videoyu karelere bölüp her kareyi işle")
        sp.add_argument("--every", type=int, default=1, help="her N karede bir işle")
        sp.add_argument("--max-frames", type=int, default=0, help="test için kare sınırı")
        sp.add_argument("--seed", type=int, help="sabit seed (kareler arası tutarlılık için önerilir)")
        sp.add_argument("--no-mp4", action="store_true", help="önizleme mp4 üretme")
    a = p.parse_args(argv)
    cfg = load_config()
    {"ping": cmd_ping, "placeholders": cmd_placeholders, "run": cmd_run, "watch": cmd_watch}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
