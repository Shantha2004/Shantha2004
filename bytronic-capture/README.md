# Bytronic image capture (replacement for the deleted .bat)

Captures images from the Basler camera and saves them for model training.

## Install on the Bytronic PC
Copy `capture.bat` and the `capture-worker/` folder into the project root
(next to `main.py` and `calibrate.py`). It uses the existing `.venv` and
`requirements.txt` (pypylon, opencv-python, PyYAML); nothing new to install.

```
project/
├── main.py
├── calibrate.py
├── capture.bat              <- new
├── capture-worker/          <- new
│   ├── config.yaml
│   └── app/capture_main.py
├── camera-worker/ ...
└── dataset/raw/<date>/<label>/*.png + metadata.csv   (created automatically)
```

## Use
Stop `main.py` first. A Basler camera can only be opened by one program at a time.

| Command | What it does |
|---|---|
| `capture.bat` | Live preview, **SPACE** saves a frame, **Q** quits |
| `capture.bat --label ok` / `--label ng` | Save into a class subfolder |
| `capture.bat --mode interval --interval 2` | Auto-save every 2 s |
| `capture.bat --mode interval --max-images 200 --preview` | 200 images, with live view |
| `capture.bat --exposure-us 5000 --gain 0` | Override camera exposure/gain |

Defaults are in `capture-worker/config.yaml`. To reproduce the production
camera settings exactly, save them from pylon Viewer as a `.pfs` file and set `pfs_file`.
