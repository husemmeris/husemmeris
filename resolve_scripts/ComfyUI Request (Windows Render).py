"""
DaVinci Resolve (Mac) -> Workspace > Scripts > ComfyUI Request (Windows Render)

1. Aktif timeline'ın In/Out aralığını (yoksa tümünü) Google Drive'daki VFX_Exchange/to_comfy'ye render eder.
   (txt2img gibi girdi gerektirmeyen workflow'larda render atlanır.)
2. Bir pencere açar: workflow, prompt, kare kare, seed, test kare sayısı.
3. VFX_Exchange/requests/ içine iş bırakır. Windows'taki render_worker bunu görür, ComfyUI'de render alır,
   sonucu from_comfy/'ye koyar.
4. İş bitince Workspace > Scripts > ComfyUI Import ile içe al.

Ücretsiz Resolve'da çalışır.
"""
import json
import os
import time
import uuid


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


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def ask(resolve, workflows, defaults):
    """Fusion UIManager ile form. Kullanılamazsa varsayılanları döndürür."""
    try:
        fu = resolve.Fusion()
        ui = fu.UIManager
        disp = bmd.UIDispatcher(ui)  # noqa: F821  (Resolve ortamında global)
    except Exception:
        print("Pencere açılamadı; config'teki request_defaults kullanılıyor.")
        return defaults

    names = [w["name"] for w in workflows] or ["img2img_sd15"]
    win = disp.AddWindow({"ID": "ComfyReq", "WindowTitle": "ComfyUI -> Windows Render",
                          "Geometry": [200, 200, 560, 330]}, [
        ui.VGroup({"Spacing": 6}, [
            ui.HGroup([ui.Label({"Text": "Workflow", "Weight": 0.25}),
                       ui.ComboBox({"ID": "wf", "Weight": 0.75})]),
            ui.Label({"ID": "desc", "Text": "", "WordWrap": True}),
            ui.Label({"Text": "Prompt (ne istiyorsun?)"}),
            ui.TextEdit({"ID": "prompt", "PlainText": defaults.get("prompt", "")}),
            ui.HGroup([ui.CheckBox({"ID": "pf", "Text": "Kare kare (video)", "Checked": defaults.get("per_frame", True)}),
                       ui.Label({"Text": "Seed"}), ui.LineEdit({"ID": "seed", "Text": str(defaults.get("seed", 42))}),
                       ui.Label({"Text": "Test kare (0=hepsi)"}),
                       ui.LineEdit({"ID": "maxf", "Text": str(defaults.get("max_frames", 0))})]),
            ui.HGroup([ui.Label({"Text": "Denoise (0.2 hafif - 0.7 güçlü)"}),
                       ui.LineEdit({"ID": "denoise", "Text": str(defaults.get("denoise", 0.45))})]),
            ui.HGroup([ui.Button({"ID": "ok", "Text": "Gönder"}), ui.Button({"ID": "cancel", "Text": "İptal"})]),
        ])])
    it = win.GetItems()
    for n in names:
        it["wf"].AddItem(n)
    if defaults.get("workflow") in names:
        it["wf"].CurrentIndex = names.index(defaults["workflow"])
    result = {}

    def show_desc(ev=None):
        i = it["wf"].CurrentIndex
        it["desc"].Text = workflows[i].get("description", "") if i < len(workflows) else ""

    def on_ok(ev):
        result.update(workflow=names[it["wf"].CurrentIndex], prompt=it["prompt"].PlainText.strip(),
                      per_frame=bool(it["pf"].Checked), seed=it["seed"].Text, max_frames=it["maxf"].Text,
                      denoise=it["denoise"].Text)
        disp.ExitLoop()

    def on_cancel(ev):
        disp.ExitLoop()

    win.On.wf.CurrentIndexChanged = show_desc
    win.On.ok.Clicked = on_ok
    win.On.cancel.Clicked = on_cancel
    win.On.ComfyReq.Close = on_cancel
    show_desc()
    win.Show()
    disp.RunLoop()
    win.Hide()
    return result or None


def render_range(project, timeline, out_dir, name):
    settings = {"TargetDir": out_dir, "CustomName": name, "ExportVideo": True, "ExportAudio": False}
    mark = None
    try:
        mark = timeline.GetMarkInOut()
    except Exception:
        pass
    vm = (mark or {}).get("video") or {}
    if "in" in vm and "out" in vm:
        start = timeline.GetStartFrame()
        mi, mo = vm["in"], vm["out"]
        if mi < start:
            mi, mo = mi + start, mo + start
        settings.update(SelectAllFrames=False, MarkIn=mi, MarkOut=mo)
        print("In/Out aralığı render ediliyor (%d kare)." % (mo - mi + 1))
    else:
        settings["SelectAllFrames"] = True
        print("In/Out yok -> tüm timeline render ediliyor. (Kısa bir aralık için I/O işaretle.)")
    project.SetCurrentRenderFormatAndCodec("mp4", "H264")
    project.SetRenderSettings(settings)
    job = project.AddRenderJob()
    if not job:
        return None
    project.StartRendering([job], False)
    while project.IsRenderingInProgress():
        time.sleep(0.5)
    st = project.GetRenderJobStatus(job)
    project.DeleteRenderJob(job)
    if st.get("JobStatus") != "Complete":
        print("Render başarısız: %s" % st)
        return None
    return os.path.join(out_dir, name + ".mp4")


def main():
    resolve = get_resolve()
    if not resolve:
        print("Resolve içinden Workspace > Scripts menüsünden çalıştır.")
        return
    cfg = load_config()
    root = os.path.expanduser(cfg["exchange_dir"])
    req_dir = os.path.join(root, "requests")
    to_comfy = os.path.join(root, "to_comfy")
    for d in (req_dir, to_comfy):
        if not os.path.isdir(d):
            os.makedirs(d)

    hb = load_json(os.path.join(root, "worker_heartbeat.json"), {})
    if not hb:
        print("UYARI: Windows worker hiç görülmedi. Windows'ta kurulumu yap / bilgisayarı aç.")
    elif time.time() - hb.get("epoch", 0) > 600:
        print("UYARI: Windows worker 10 dakikadır sinyal vermiyor (%s). İstek kuyrukta bekler." % hb.get("last_seen"))

    workflows = load_json(os.path.join(root, "workflows.json"), {}).get("workflows", [])
    defaults = {"workflow": "img2img_sd15", "per_frame": True, "seed": 42, "max_frames": 0,
                "denoise": 0.45, "prompt": ""}
    defaults.update(cfg.get("request_defaults", {}))
    form = ask(resolve, workflows, defaults)
    if not form:
        print("İptal edildi.")
        return

    wf_info = next((w for w in workflows if w["name"] == form["workflow"]), {"needs_input": True})
    rid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    req = {"id": rid, "workflow": form["workflow"], "set": {},
           "per_frame": bool(form.get("per_frame")), "name": None}
    if form.get("prompt"):
        req["set"]["prompt"] = form["prompt"]
    for key, cast in (("seed", int), ("max_frames", int)):
        try:
            req[key] = cast(form.get(key))
        except (TypeError, ValueError):
            pass
    try:
        req["set"]["denoise"] = float(form.get("denoise"))
    except (TypeError, ValueError):
        pass

    project = resolve.GetProjectManager().GetCurrentProject()
    if wf_info.get("needs_input", True):
        timeline = project.GetCurrentTimeline()
        if not timeline:
            print("Açık timeline yok.")
            return
        name = "".join(c if c.isalnum() else "_" for c in timeline.GetName()) + "_" + rid
        clip = render_range(project, timeline, to_comfy, name)
        if not clip:
            print("Render alınamadı, istek gönderilmedi.")
            return
        req["input"] = "to_comfy/" + os.path.basename(clip)
        req["name"] = timeline.GetName()
        if not req["per_frame"]:
            print("Not: video girdisi kare kare işlenmezse workflow ilk kareyi alır.")

    tmp = os.path.join(req_dir, rid + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(req, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(req_dir, rid + ".json"))
    print("İstek Windows'a gönderildi: %s (%s)" % (rid, req["workflow"]))
    print("Bitince: Workspace > Scripts > ComfyUI Import. Durum: VFX_Exchange/requests/%s.status.json" % rid)


main()
