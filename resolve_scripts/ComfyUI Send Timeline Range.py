"""
DaVinci Resolve -> Workspace > Scripts > ComfyUI Send Timeline Range

Aktif timeline'ın In/Out aralığını (yoksa tamamını) H.264 MP4 olarak
exchange/to_comfy klasörüne render eder. Oradan:
  - Claude Code'a "to_comfy'deki son klibe şu efekti uygula" dersin, ya da
  - "python comfy_vfx.py watch ..." çalışıyorsa otomatik işlenir.
Sonuç "ComfyUI Import" script'i ile geri gelir.
Ücretsiz Resolve'da çalışır (H.264, en fazla UHD).
"""
import json
import os
import time


def get_resolve():
    g = globals()
    if g.get("resolve"):
        return g["resolve"]
    if g.get("bmd"):
        return g["bmd"].scriptapp("Resolve")
    try:
        import DaVinciResolveScript as dvr  # noqa
        return dvr.scriptapp("Resolve")
    except Exception:
        return None


def load_config():
    path = os.environ.get("COMFY_VFX_CONFIG") or os.path.join(os.path.expanduser("~"), ".comfy_vfx", "config.json")
    cfg = {"exchange_dir": os.path.join(os.path.expanduser("~"), "VFX_Exchange")}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    return cfg


def main():
    resolve = get_resolve()
    if not resolve:
        print("Resolve API bulunamadı. Resolve içinden Workspace > Scripts menüsünden çalıştır.")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("Açık timeline yok.")
        return
    cfg = load_config()
    out_dir = os.path.join(os.path.expandvars(os.path.expanduser(cfg["exchange_dir"])), "to_comfy")
    os.makedirs(out_dir, exist_ok=True)

    name = "".join(c if c.isalnum() else "_" for c in timeline.GetName()) + time.strftime("_%H%M%S")
    settings = {"TargetDir": out_dir, "CustomName": name, "ExportVideo": True, "ExportAudio": False}

    mark = None
    try:
        mark = timeline.GetMarkInOut()  # Resolve 19+
    except Exception:
        pass
    video_mark = (mark or {}).get("video") or {}
    if "in" in video_mark and "out" in video_mark:
        start = timeline.GetStartFrame()
        mi, mo = video_mark["in"], video_mark["out"]
        if mi < start:  # göreli değer döndüyse mutlak kareye çevir
            mi, mo = mi + start, mo + start
        settings.update(SelectAllFrames=False, MarkIn=mi, MarkOut=mo)
        print("In/Out aralığı render ediliyor.")
    else:
        settings["SelectAllFrames"] = True
        print("In/Out yok -> tüm timeline render ediliyor.")

    project.SetCurrentRenderFormatAndCodec("mp4", "H264")
    project.SetRenderSettings(settings)
    job_id = project.AddRenderJob()
    if not job_id:
        print("Render işi eklenemedi.")
        return
    project.StartRendering([job_id], False)
    while project.IsRenderingInProgress():
        time.sleep(0.5)
    status = project.GetRenderJobStatus(job_id)
    project.DeleteRenderJob(job_id)
    print("Render: %s -> %s" % (status.get("JobStatus"), os.path.join(out_dir, name + ".mp4")))


main()
