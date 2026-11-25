"""
DaVinci Resolve -> Workspace > Scripts > ComfyUI Import

Exchange klasöründeki from_comfy/<iş>/job.json manifest'lerini okur ve henüz
içe alınmamış ComfyUI çıktılarını "ComfyUI VFX" bin'ine ekler.
Görüntü dizileri (frame_00001.png ...) tek klip olarak gelir.
Resolve'un ÜCRETSİZ sürümünde çalışır (script Resolve içinden çalıştırıldığı için).

Ayar: %USERPROFILE%\\.comfy_vfx\\config.json  ->  {"exchange_dir": "G:/My Drive/VFX_Exchange", ...}
İsteğe bağlı: "resolve_append_to_timeline": true  -> yeni klipleri aktif timeline'ın sonuna ekler.
"""
import json
import os

BIN_NAME = "ComfyUI VFX"


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


def get_bin(media_pool, name):
    root = media_pool.GetRootFolder()
    for sub in root.GetSubFolderList() or []:
        if sub.GetName() == name:
            return sub
    return media_pool.AddSubFolder(root, name)


def main():
    resolve = get_resolve()
    if not resolve:
        print("Resolve API bulunamadı. Bu script'i Resolve içinden Workspace > Scripts menüsünden çalıştır.")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    media_pool = project.GetMediaPool()
    cfg = load_config()
    from_comfy = os.path.join(os.path.expandvars(os.path.expanduser(cfg["exchange_dir"])), "from_comfy")
    if not os.path.isdir(from_comfy):
        print("Klasör yok: " + from_comfy)
        return

    # Proje bazlı takip: aynı iş başka projeye de alınabilsin
    marker_name = ".imported_" + "".join(c if c.isalnum() else "_" for c in project.GetName())
    target_bin = get_bin(media_pool, BIN_NAME)
    media_pool.SetCurrentFolder(target_bin)

    new_items = []
    for job in sorted(os.listdir(from_comfy)):
        job_dir = os.path.join(from_comfy, job)
        manifest = os.path.join(job_dir, "job.json")
        if job.endswith(".partial") or not os.path.isfile(manifest):
            continue
        if os.path.exists(os.path.join(job_dir, marker_name)):
            continue
        with open(manifest, "r", encoding="utf-8-sig") as f:
            m = json.load(f)

        items = []
        if m.get("type") == "sequence":
            first = os.path.join(job_dir, m["pattern"] % m["start"])
            last = os.path.join(job_dir, m["pattern"] % m["end"])
            if not (os.path.exists(first) and os.path.exists(last)):
                print("Henüz senkronize olmadı, atlandı: " + job)
                continue
            if m["start"] == m["end"]:
                items = media_pool.ImportMedia([first]) or []
            else:
                items = media_pool.ImportMedia([{
                    "FilePath": os.path.join(job_dir, m["pattern"]),
                    "StartIndex": m["start"], "EndIndex": m["end"]}]) or []
        else:
            paths = [os.path.join(job_dir, f) for f in m.get("files", [])]
            if not all(os.path.exists(p) for p in paths):
                print("Henüz senkronize olmadı, atlandı: " + job)
                continue
            items = media_pool.ImportMedia(paths) or []

        for it in items:
            try:
                it.SetClipProperty("Comments", "ComfyUI | " + m.get("workflow", "") + " | " +
                                   str(m.get("values", {}).get("prompt", ""))[:200])
            except Exception:
                pass
        if items:
            new_items.extend(items)
            open(os.path.join(job_dir, marker_name), "w").close()
            print("İçe alındı: %s (%d klip)" % (job, len(items)))
        else:
            print("İçe alınamadı: " + job)

    if new_items and cfg.get("resolve_append_to_timeline"):
        if project.GetCurrentTimeline():
            media_pool.AppendToTimeline(new_items)
            print("Timeline'a eklendi.")
    print("Bitti. Yeni klip: %d -> bin '%s'" % (len(new_items), BIN_NAME))


main()
