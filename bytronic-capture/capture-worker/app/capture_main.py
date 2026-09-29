"""
Image capture tool for collecting model-training data on the Bytronic PC.

Grabs frames from the Basler camera (pypylon) and saves them to disk,
together with a metadata CSV, so they can be labelled and used for training.

Modes:
  manual    live preview; SPACE / S saves a frame, Q / ESC quits
  interval  saves a frame every --interval seconds (optionally with preview)

The camera can only be opened by one process at a time, so stop main.py
(camera-worker) before running this.
"""
import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import yaml

APP_DIR = Path(__file__).parent
DEFAULT_CONFIG = APP_DIR.parent / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [capture] - %(levelname)s - %(message)s",
)


# --------------------------------------------------------------------------- #
# Camera sources
# --------------------------------------------------------------------------- #
class BaslerCamera:
    def __init__(self, cfg: dict):
        from pypylon import pylon

        self.pylon = pylon
        tl = pylon.TlFactory.GetInstance()
        devices = tl.EnumerateDevices()
        if not devices:
            raise RuntimeError("No Basler camera found. Check cable/power and pylon Viewer.")

        serial = str(cfg.get("serial") or "").strip()
        if serial:
            matches = [d for d in devices if d.GetSerialNumber() == serial]
            if not matches:
                found = ", ".join(d.GetSerialNumber() for d in devices)
                raise RuntimeError(f"Camera {serial} not found. Available: {found}")
            device = matches[0]
        else:
            device = devices[0]

        self.cam = pylon.InstantCamera(tl.CreateDevice(device))
        self.cam.Open()
        logging.info(
            f"Opened {device.GetModelName()} (serial {device.GetSerialNumber()})"
        )

        pfs = cfg.get("pfs_file")
        if pfs:
            pfs_path = (APP_DIR.parent / pfs).resolve()
            logging.info(f"Loading camera features from {pfs_path}")
            pylon.FeaturePersistence.Load(str(pfs_path), self.cam.GetNodeMap(), True)

        if cfg.get("exposure_us") is not None:
            self._try_set(["ExposureAuto"], "Off")
            self._try_set(["ExposureTime", "ExposureTimeAbs"], float(cfg["exposure_us"]))
        if cfg.get("gain") is not None:
            self._try_set(["GainAuto"], "Off")
            self._try_set(["Gain", "GainRaw"], cfg["gain"])

        self.is_mono = str(self.cam.PixelFormat.GetValue()).startswith("Mono")
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = (
            pylon.PixelType_Mono8 if self.is_mono else pylon.PixelType_BGR8packed
        )
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def _try_set(self, names, value):
        # Feature names differ between camera generations (e.g. ExposureTime vs ExposureTimeAbs)
        for name in names:
            try:
                getattr(self.cam, name).SetValue(value)
                logging.info(f"Set {name} = {value}")
                return
            except Exception:
                continue
        logging.warning(f"Could not set any of {names} to {value}")

    def read(self):
        res = self.cam.RetrieveResult(5000, self.pylon.TimeoutHandling_ThrowException)
        try:
            if not res.GrabSucceeded():
                logging.warning(f"Grab failed: {res.GetErrorDescription()}")
                return None
            return self.converter.Convert(res).GetArray()
        finally:
            res.Release()

    def settings(self) -> dict:
        info = {}
        for name in ("ExposureTime", "ExposureTimeAbs", "Gain", "GainRaw", "PixelFormat"):
            try:
                info[name] = getattr(self.cam, name).GetValue()
            except Exception:
                pass
        return info

    def close(self):
        try:
            if self.cam.IsGrabbing():
                self.cam.StopGrabbing()
            self.cam.Close()
        except Exception:
            pass


class OpenCVCamera:
    """USB webcam / video file, useful for testing without the Basler camera."""

    def __init__(self, cfg: dict):
        src = cfg.get("opencv_source", 0)
        self.cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open OpenCV source {src!r}")

    def read(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def settings(self) -> dict:
        return {}

    def close(self):
        self.cap.release()


def open_camera(cfg: dict):
    source = cfg.get("source", "basler")
    if source == "basler":
        return BaslerCamera(cfg)
    if source == "opencv":
        return OpenCVCamera(cfg)
    raise ValueError(f"Unknown camera source {source!r} (use 'basler' or 'opencv')")


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #
class ImageWriter:
    def __init__(self, output_dir: Path, prefix: str, label: str, ext: str):
        session = datetime.now().strftime("%Y-%m-%d")
        sub = Path(session) / label if label else Path(session)
        self.dir = output_dir / sub
        self.dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.label = label
        self.ext = ext.lstrip(".").lower()
        self.count = 0

        self.csv_path = self.dir / "metadata.csv"
        new_file = not self.csv_path.exists()
        self.csv_file = open(self.csv_path, "a", newline="")
        self.csv = csv.writer(self.csv_file)
        if new_file:
            self.csv.writerow(["filename", "timestamp", "label", "width", "height", "camera_settings"])

    def save(self, frame, settings: dict) -> Path:
        ts = datetime.now()
        name = f"{self.prefix}_{ts.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.{self.ext}"
        path = self.dir / name
        if not cv2.imwrite(str(path), frame):
            raise IOError(f"Failed to write {path}")
        h, w = frame.shape[:2]
        self.csv.writerow([name, ts.isoformat(timespec="milliseconds"), self.label, w, h, settings])
        self.csv_file.flush()
        self.count += 1
        logging.info(f"[{self.count}] saved {path}")
        return path

    def close(self):
        self.csv_file.close()


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def show_preview(frame, writer: ImageWriter, mode: str, scale: float) -> int:
    view = frame if scale == 1.0 else cv2.resize(frame, None, fx=scale, fy=scale)
    if view.ndim == 2:
        view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
    else:
        view = view.copy()
    hint = "SPACE/S: save  Q/ESC: quit" if mode == "manual" else "Q/ESC: quit"
    cv2.putText(view, f"saved: {writer.count}   {hint}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.imshow("Capture", view)
    return cv2.waitKey(1) & 0xFF


def run(cfg: dict):
    output_dir = Path(cfg["output_dir"])
    if not output_dir.is_absolute():
        output_dir = (APP_DIR.parent / output_dir).resolve()

    try:
        camera = open_camera(cfg)
    except Exception as e:
        logging.error(f"Camera open failed: {e}")
        logging.error("If main.py / camera-worker is running, stop it first - "
                      "the camera can only be used by one program at a time.")
        sys.exit(1)

    writer = ImageWriter(output_dir, cfg["prefix"], cfg.get("label") or "", cfg["format"])
    logging.info(f"Saving images to {writer.dir}")

    mode = cfg["mode"]
    preview = cfg["preview"] or mode == "manual"
    max_images = int(cfg.get("max_images") or 0)
    interval = float(cfg["interval"])
    last_save = 0.0

    try:
        while True:
            frame = camera.read()
            if frame is None:
                continue

            key = show_preview(frame, writer, mode, float(cfg["preview_scale"])) if preview else -1
            if key in (ord("q"), 27):
                break

            if mode == "manual" and key in (ord(" "), ord("s")):
                writer.save(frame, camera.settings())
            elif mode == "interval" and time.monotonic() - last_save >= interval:
                writer.save(frame, camera.settings())
                last_save = time.monotonic()

            if max_images and writer.count >= max_images:
                logging.info(f"Reached max_images={max_images}")
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()
        writer.close()
        if preview:
            cv2.destroyAllWindows()
        logging.info(f"Done. {writer.count} image(s) saved to {writer.dir}")


def load_config(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Capture training images from the camera.")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="YAML config file")
    p.add_argument("--mode", choices=["manual", "interval"])
    p.add_argument("--interval", type=float, help="seconds between saves (interval mode)")
    p.add_argument("--max-images", type=int, help="stop after N images (0 = unlimited)")
    p.add_argument("--label", help="subfolder/class name, e.g. ok, ng, scratch")
    p.add_argument("--output-dir", help="root folder for saved images")
    p.add_argument("--prefix", help="filename prefix")
    p.add_argument("--format", choices=["png", "bmp", "jpg", "tiff"])
    p.add_argument("--source", choices=["basler", "opencv"])
    p.add_argument("--serial", help="Basler camera serial number")
    p.add_argument("--exposure-us", type=float)
    p.add_argument("--gain", type=float)
    p.add_argument("--preview", action="store_true", default=None, help="show live window in interval mode")
    args = p.parse_args(argv)

    cfg = {
        "mode": "manual", "interval": 1.0, "max_images": 0, "label": "",
        "output_dir": "../dataset/raw", "prefix": "img", "format": "png",
        "source": "basler", "serial": "", "pfs_file": "", "exposure_us": None, "gain": None,
        "opencv_source": 0, "preview": False, "preview_scale": 0.5,
    }
    cfg_path = Path(args.config)
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg.update(yaml.safe_load(f) or {})
    else:
        logging.warning(f"Config {cfg_path} not found, using defaults")

    for key, value in vars(args).items():
        if key != "config" and value is not None:
            cfg[key] = value
    return cfg


if __name__ == "__main__":
    run(load_config())
