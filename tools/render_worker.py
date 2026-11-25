#!/usr/bin/env python3
"""
render_worker.py - Windows render makinesi (oturum açılışında otomatik başlar).

Google Drive'daki  VFX_Exchange/requests/*.json  isteklerini izler.
Mac'teki DaVinci (veya comfy_request.py) bir istek bıraktığında:
  1. ComfyUI kapalıysa başlatır (sadece gerektiğinde çalışır),
  2. işi comfy_vfx ile render eder -> VFX_Exchange/from_comfy/<iş>/,
  3. durumu requests/<id>.status.json dosyasına yazar (Mac buradan takip eder),
  4. bir süre iş gelmezse kendi başlattığı ComfyUI'yi kapatır (GPU/RAM boşalır).

İstek biçimi (requests/<id>.json):
  {"id": "...", "workflow": "img2img_sd15", "input": "to_comfy/klip.mp4",
   "set": {"prompt": "..."}, "per_frame": true, "seed": 42, "every": 1,
   "max_frames": 0, "name": "shot01"}
"input" exchange köküne göre görelidir (Mac ve Windows'ta yollar farklı olduğu için).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comfy_vfx as cv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / "workflows"


def log(msg: str):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    try:
        logf = Path.home() / ".comfy_vfx" / "worker.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        with logf.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class ComfyProcess:
    """ComfyUI'yi gerektiğinde başlatır, boşta kalınca kapatır."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.last_used = time.time()

    def alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.cfg["comfy_url"] + "/system_stats", timeout=3):
                return True
        except Exception:
            return False

    def ensure(self):
        self.last_used = time.time()
        if self.alive():
            return
        cmd = self.cfg.get("comfy_start")
        if not cmd:
            raise SystemExit("ComfyUI kapalı ve config'te 'comfy_start' yok.")
        log("ComfyUI başlatılıyor...")
        logf = open(Path.home() / ".comfy_vfx" / "comfyui.log", "a", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(cmd, cwd=self.cfg.get("comfy_dir") or None,
                                     stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
        for _ in range(240):  # en fazla 4 dk (ilk açılışta model taraması uzun sürebilir)
            if self.proc.poll() is not None:
                raise SystemExit("ComfyUI açılamadı, bkz. ~/.comfy_vfx/comfyui.log")
            if self.alive():
                log("ComfyUI hazır.")
                return
            time.sleep(1)
        raise SystemExit("ComfyUI 4 dakikada açılmadı.")

    def maybe_stop(self):
        idle = float(self.cfg.get("comfy_idle_minutes", 15)) * 60
        if self.proc and self.proc.poll() is None and time.time() - self.last_used > idle:
            log("Boşta -> ComfyUI kapatılıyor.")
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


def resolve_workflow(name: str) -> Path:
    p = Path(name)
    if not p.suffix:
        p = p.with_suffix(".json")
    if not p.is_absolute():
        p = WORKFLOWS / p.name
    if not p.exists():
        raise SystemExit(f"Workflow yok: {p.name}. Mevcut: {[w.stem for w in WORKFLOWS.glob('*.json')]}")
    return p


def wait_synced(path: Path, timeout=1800) -> Path:
    """Drive dosyayı indirip bitirene kadar bekler (boyut sabitlenene kadar)."""
    start, last = time.time(), -1
    while time.time() - start < timeout:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last:
                return path
            last = size
        time.sleep(3)
    raise SystemExit(f"Girdi dosyası Drive'dan gelmedi: {path}")


def process(cfg: dict, comfy: ComfyProcess, req_file: Path, root: Path):
    req = json.loads(req_file.read_text(encoding="utf-8-sig"))
    rid = req.get("id") or req_file.stem
    status_file = req_file.with_name(rid + ".status.json")
    status = {"id": rid, "state": "running", "started": time.strftime("%Y-%m-%d %H:%M:%S"),
              "worker": os.environ.get("COMPUTERNAME", "worker"), "progress": None}
    write_json(status_file, status)
    log(f"İş başladı: {rid} ({req.get('workflow')})")

    def progress(i, n):
        status["progress"] = f"{i}/{n}"
        if i == 1 or i % 5 == 0 or i == n:
            write_json(status_file, status)

    try:
        wf = resolve_workflow(req["workflow"])
        inp = None
        if req.get("input"):
            inp = wait_synced(root / req["input"])
        comfy.ensure()
        sets = [f"{k}={v}" for k, v in (req.get("set") or {}).items()]
        job_dir = cv.run_job(cfg, wf, inp, sets, req.get("name") or rid, bool(req.get("per_frame")),
                             int(req.get("every", 1)), int(req.get("max_frames", 0)),
                             req.get("seed"), not req.get("no_mp4", False), progress=progress)
        status.update(state="done", output=f"from_comfy/{job_dir.name}",
                      finished=time.strftime("%Y-%m-%d %H:%M:%S"))
        log(f"İş bitti: {rid} -> {job_dir.name}")
    except BaseException as e:  # SystemExit dahil: worker ölmesin
        if isinstance(e, KeyboardInterrupt):
            raise
        status.update(state="error", error=str(e) or traceback.format_exc()[-1500:],
                      finished=time.strftime("%Y-%m-%d %H:%M:%S"))
        log(f"İş HATA: {rid}: {status['error']}")
    finally:
        comfy.last_used = time.time()
        write_json(status_file, status)
        done = req_file.parent / "_done"
        done.mkdir(exist_ok=True)
        shutil.move(str(req_file), done / req_file.name)


def publish_workflows(root: Path):
    """Mac'teki Resolve diyaloğu hangi workflow'ların olduğunu buradan okur."""
    cat = []
    for wf in sorted(WORKFLOWS.glob("*.json")):
        try:
            meta = json.loads(wf.read_text(encoding="utf-8-sig")).get("_meta_comfy_vfx", {})
            tpl, _ = cv.load_workflow(wf)
            cat.append({"name": wf.stem, "description": meta.get("description", ""),
                        "needs_input": "input" in cv.find_placeholders(tpl),
                        "defaults": meta.get("defaults", {})})
        except Exception as e:  # bozuk workflow worker'ı durdurmasın
            log(f"Workflow okunamadı {wf.name}: {e}")
    write_json(root / "workflows.json", {"workflows": cat})


def main():
    cfg = cv.load_config()
    to_comfy, _ = cv.exchange_dirs(cfg)
    root = to_comfy.parent
    req_dir = root / "requests"
    req_dir.mkdir(exist_ok=True)
    comfy = ComfyProcess(cfg)
    publish_workflows(root)
    log(f"Worker hazır. İzlenen klasör: {req_dir}")
    write_json(root / "worker_heartbeat.json", {"worker": os.environ.get("COMPUTERNAME", "worker"),
                                                 "since": time.strftime("%Y-%m-%d %H:%M:%S")})
    beat = 0.0
    while True:
        reqs = sorted((p for p in req_dir.glob("*.json")
                       if not p.name.endswith(".status.json") and not p.name.endswith(".tmp")),
                      key=lambda p: p.stat().st_mtime)
        for r in reqs:
            try:
                process(cfg, comfy, r, root)
            except json.JSONDecodeError:
                pass  # henüz tam senkronize olmamış, sonraki turda dene
        if time.time() - beat > 60:  # Mac "worker çevrimiçi mi?" diye buradan bakar
            beat = time.time()
            write_json(root / "worker_heartbeat.json",
                       {"worker": os.environ.get("COMPUTERNAME", "worker"),
                        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"), "epoch": int(beat),
                        "comfy_running": comfy.alive()})
        comfy.maybe_stop()
        time.sleep(float(cfg.get("worker_poll_seconds", 5)))


if __name__ == "__main__":
    main()
