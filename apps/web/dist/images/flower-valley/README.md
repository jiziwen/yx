# Flower Valley visual references

Downloaded on **2026-11-06** from the public flower-valley scene on
[Gladeye](https://www.gladeye.com/). The scene was identified through the
[MotionSites Flower Valley / Fernhollow reference](https://motionsites.ai/?prompt=fernhollow).

| Local file | Original public URL |
| --- | --- |
| `pool-summer.png` | https://www.gladeye.com/valley/flowers/pool_summer.png |
| `pool-winter.png` | https://www.gladeye.com/valley/flowers/pool_winter.png |
| `terrain.png` | https://www.gladeye.com/valley/terrain.png |
| `camera-path.json` | Derived from https://www.gladeye.com/valley/camera-path07.glb |

Both PNG sprite atlases are the original 1500 × 1312 RGBA images, arranged in
eight columns and seven rows. The summer atlas contains flowers, foliage, and
fallen leaves; the winter atlas contains scattered petals, foliage, and light
fragments. The PNGs are copied without image changes.

`camera-path.json` retains the 200 position and quaternion rotation samples from
the source GLB as nested `positions` and `rotations` arrays, rounded to six decimal
places. The original samples span 0–8.291667 seconds at 24 fps; the renderer
controls progress independently to reproduce the scene's slow camera travel.

The application uses its own renderer and local assets. It does not load or
execute the original site's compiled JavaScript bundles or remote scripts.
This file records provenance only and makes no claim about licensing or reuse
permissions.
