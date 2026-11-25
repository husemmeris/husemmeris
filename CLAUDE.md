# ComfyUI ↔ DaVinci Resolve VFX bridge — instructions for Claude Code

The user runs this on Windows and speaks Turkish; reply in Turkish.
Goal: the user describes a VFX shot in words; you produce it with ComfyUI and deliver it to DaVinci Resolve.

## Pieces
- `tools/comfy_vfx.py` — stdlib-only CLI. Talks to ComfyUI's HTTP API (`comfy_url`), writes results to
  `<exchange_dir>/from_comfy/<timestamp>_<name>/` with a `job.json` manifest.
- `resolve_scripts/` — installed into Resolve's `Fusion\Scripts\Utility`. The user runs them from
  **Workspace > Scripts** (free Resolve does not allow external scripting, so you cannot drive Resolve directly):
  - `ComfyUI Import` — imports every new job into the "ComfyUI VFX" bin.
  - `ComfyUI Send Timeline Range` — renders the timeline In/Out to `<exchange_dir>/to_comfy/*.mp4`.
- Config: `%USERPROFILE%\.comfy_vfx\config.json` (`comfy_url`, `exchange_dir`, ...). `COMFY_URL` env var overrides.
- `exchange_dir` is normally inside Google Drive for Desktop, so results sync to any PC running Resolve.

## Workflow you follow
1. `python tools/comfy_vfx.py ping` — if it fails, tell the user to start ComfyUI (local) or the Kaggle notebook (`cloud/`)
   and update `comfy_url`.
2. Pick a workflow from `workflows/` (run `placeholders --workflow X` to see its parameters and defaults).
   Check the model names in defaults exist in the user's ComfyUI (`GET {comfy_url}/object_info/CheckpointLoaderSimple`);
   override with `--set checkpoint=...` if needed.
3. Source footage: a file the user names, or the newest file in `<exchange_dir>/to_comfy/`.
4. Run, e.g.
   - still: `python tools/comfy_vfx.py run --workflow workflows/img2img_sd15.json --input shot.png --set prompt="..." --set denoise=0.5`
   - video: add `--per-frame --seed 1234` (fixed seed = less flicker). Test first with `--max-frames 5`.
   - generate plate: `python tools/comfy_vfx.py run --workflow workflows/txt2img_sd15.json --set prompt="..." --set width=1024 --set height=576`
5. Tell the user: "Resolve'da Workspace > Scripts > ComfyUI Import çalıştır."

## New workflows
The user can build any workflow in ComfyUI and save it with **Workflow > Export (API)** into `workflows/`.
Make it reusable by replacing values with `{{prompt}}`, `{{input}}`, `{{seed}}`, etc., and add a
`"_meta_comfy_vfx": {"description": "...", "defaults": {...}}` key. Alternatively set any node field directly:
`--set 6.inputs.denoise=0.3`. Workflows using custom nodes (VideoHelperSuite, AnimateDiff...) work as long as
those nodes are installed in ComfyUI; any output file listed in history is downloaded.
