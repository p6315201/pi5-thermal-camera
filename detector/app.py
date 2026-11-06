#!/usr/bin/env python3
"""
RGB + тепловізор + YOLO -> веб-сторінка для аналізу.

Програма працює на Raspberry Pi і сама роздає веб-сторінку.
На ПК у тій самій мережі відкрийте http://<IP-адреса-Pi>:8000 (адреси друкуються при запуску).

Запуск на Pi (приклади):
    python app.py --rgb picam --thermal 0 --ncnn --imgsz 416   # CSI-камера + USB-тепловізор
    python app.py --rgb 0 --thermal 2 --ncnn                   # дві USB-камери
    python app.py --rgb flight_rgb.mp4 --thermal flight_ir.mp4 # записане відео
    python app.py --list-cameras                               # які камери бачить система
"""
import argparse
import collections
import csv
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DET_DIR = BASE_DIR / "detections"
SNAP_DIR = BASE_DIR / "snapshots"

# Групи, які показує сторінка. Кольори у BGR.
GROUPS = {
    "person":   {"label": "PERSON",   "color": (0, 210, 255)},
    "vehicle":  {"label": "VEHICLE",  "color": (80, 230, 80)},
    "aircraft": {"label": "AIRCRAFT", "color": (255, 140, 60)},
}
# Назва класу моделі -> група. Працює і для стандартної моделі COCO, і для донавченої (person/vehicle).
NAME_TO_GROUP = {
    "person": "person", "pedestrian": "person", "people": "person",
    "vehicle": "vehicle", "car": "vehicle", "truck": "vehicle", "bus": "vehicle", "van": "vehicle",
    "motorcycle": "vehicle", "motor": "vehicle", "bicycle": "vehicle", "train": "vehicle", "boat": "vehicle",
    "tricycle": "vehicle", "awning-tricycle": "vehicle", "machinery": "vehicle", "othervehicle": "vehicle",
    "airplane": "aircraft", "aircraft": "aircraft", "helicopter": "aircraft", "plane": "aircraft",
}


def class_groups(names):
    """{id класу моделі: група} за назвами класів моделі."""
    return {int(i): NAME_TO_GROUP[n.lower()] for i, n in names.items() if n.lower() in NAME_TO_GROUP}

PALETTES = {
    "whitehot": None,
    "blackhot": None,
    "inferno": cv2.COLORMAP_INFERNO,
    "jet": cv2.COLORMAP_JET,
}

running = True


# ---------------------------------------------------------------- налаштування
class Settings:
    def __init__(self, conf):
        self.lock = threading.Lock()
        self.data = {
            "conf": conf,
            "palette": "whitehot",
            "groups": {g: True for g in GROUPS},
            "paused": False,
            "save_crops": True,
        }

    def get(self):
        with self.lock:
            return {**self.data, "groups": dict(self.data["groups"])}

    def update(self, new):
        with self.lock:
            if "conf" in new:
                self.data["conf"] = float(min(max(float(new["conf"]), 0.01), 0.99))
            if new.get("palette") in PALETTES:
                self.data["palette"] = new["palette"]
            if isinstance(new.get("groups"), dict):
                for g, v in new["groups"].items():
                    if g in GROUPS:
                        self.data["groups"][g] = bool(v)
            for key in ("paused", "save_crops"):
                if key in new:
                    self.data[key] = bool(new[key])


# ---------------------------------------------------------------- журнал знахідок
class EventLog:
    """Зберігає вирізки знахідок (не частіше ніж раз на interval с на джерело+клас)."""

    def __init__(self, interval=2.0, keep=60):
        self.lock = threading.Lock()
        self.events = collections.deque(maxlen=keep)
        self.last_saved = {}
        self.interval = interval
        self.next_id = 1
        DET_DIR.mkdir(exist_ok=True)
        self.csv_path = DET_DIR / "log.csv"
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["time", "source", "group", "conf", "x1", "y1", "x2", "y2", "file"])

    def add(self, source, frame, dets):
        now = time.monotonic()
        best = {}
        for d in dets:
            g = d["group"]
            if g not in best or d["conf"] > best[g]["conf"]:
                best[g] = d
        for g, d in best.items():
            key = (source, g)
            if now - self.last_saved.get(key, 0) < self.interval:
                continue
            self.last_saved[key] = now
            crop = make_crop(frame, d["box"])
            stamp = datetime.now()
            fname = f"{stamp:%Y%m%d_%H%M%S_%f}_{source}_{g}.jpg"
            cv2.imwrite(str(DET_DIR / fname), crop)
            x1, y1, x2, y2 = (int(v) for v in d["box"])
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([stamp.isoformat(timespec="milliseconds"), source, g,
                                        f"{d['conf']:.3f}", x1, y1, x2, y2, fname])
            with self.lock:
                self.events.append({
                    "id": self.next_id, "time": stamp.strftime("%H:%M:%S"),
                    "source": source, "group": g, "conf": round(d["conf"], 3),
                    "url": f"/crops/{fname}",
                })
                self.next_id += 1

    def list(self, after=0):
        with self.lock:
            return [e for e in self.events if e["id"] > after]


def make_crop(frame, box, pad=0.35, min_side=96):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1 = int(max(0, x1 - bw * pad)); y1 = int(max(0, y1 - bh * pad))
    x2 = int(min(w, x2 + bw * pad)); y2 = int(min(h, y2 + bh * pad))
    crop = frame[y1:max(y2, y1 + 1), x1:max(x2, x1 + 1)]
    side = max(crop.shape[:2])
    if side < min_side:
        k = min_side / max(side, 1)
        crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
    return crop


# ---------------------------------------------------------------- обробка кадру
def thermal_to_gray(frame, clahe):
    """Тепловий кадр -> 8-біт сірий з розтяжкою контрасту (1-99 перцентиль) і CLAHE."""
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    g = gray.astype(np.float32)
    lo, hi = np.percentile(g, (1, 99))
    g = np.clip((g - lo) / max(hi - lo, 1e-6), 0, 1)
    gray = (g * 255).astype(np.uint8)
    return clahe.apply(gray)


def apply_palette(gray, name):
    if name == "blackhot":
        return cv2.cvtColor(255 - gray, cv2.COLOR_GRAY2BGR)
    cmap = PALETTES.get(name)
    if cmap is None:
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.applyColorMap(gray, cmap)


def draw_dets(img, dets):
    scale = max(img.shape[1] / 960, 0.6)
    th = max(int(round(2 * scale)), 1)
    for d in dets:
        x1, y1, x2, y2 = (int(v) for v in d["box"])
        color = GROUPS[d["group"]]["color"]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, th)
        text = f"{GROUPS[d['group']]['label']} {d['conf']:.2f}"
        (tw, tht), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, th)
        ty = y1 - 4 if y1 - tht - 8 > 0 else y2 + tht + 4
        cv2.rectangle(img, (x1, ty - tht - 4), (x1 + tw + 4, ty + 3), color, -1)
        cv2.putText(img, text, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * scale, (0, 0, 0), th, cv2.LINE_AA)


def text_frame(text, w=640, h=480):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (30, 26, 24)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.putText(img, text, ((w - tw) // 2, (h + th) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (150, 150, 150), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img)[1].tobytes()


class PiCamCapture:
    """CSI-камера Raspberry Pi через picamera2, з тим самим інтерфейсом, що й cv2.VideoCapture."""

    def __init__(self, index, size):
        self.cam = None
        try:
            from picamera2 import Picamera2
            self.cam = Picamera2(index)
            # RGB888 у picamera2 має порядок байтів B,G,R, тобто одразу підходить для OpenCV
            cfg = self.cam.create_video_configuration(main={"size": size, "format": "RGB888"}, buffer_count=4)
            self.cam.configure(cfg)
            self.cam.start()
        except Exception as e:  # немає picamera2 або камери
            print(f"[picam{index}] не вдалося відкрити: {e}")
            self.cam = None

    def isOpened(self):
        return self.cam is not None

    def read(self):
        try:
            return True, self.cam.capture_array("main")
        except Exception:
            return False, None

    def get(self, prop):
        return 0

    def set(self, *args):
        return False

    def release(self):
        if self.cam is not None:
            try:
                self.cam.stop()
                self.cam.close()
            except Exception:
                pass


def parse_size(text):
    w, h = text.lower().split("x")
    return int(w), int(h)


def open_capture(spec, picam_size=(1280, 720)):
    if spec.startswith("picam"):                 # picam, picam0, picam1
        return PiCamCapture(int(spec[5:] or 0), picam_size)
    if spec.isdigit():
        idx = int(spec)
        if sys.platform.startswith("win"):
            return cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if sys.platform.startswith("linux"):
            return cv2.VideoCapture(idx, cv2.CAP_V4L2)
        return cv2.VideoCapture(idx)
    return cv2.VideoCapture(spec)


def local_addresses(port):
    """Адреси, за якими сторінку можна відкрити з іншого комп'ютера в мережі."""
    import socket
    addrs = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))        # пакет не надсилається, лише вибір інтерфейсу
        addrs.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    host = socket.gethostname().split(".")[0]
    urls = [f"http://{a}:{port}" for a in addrs if not a.startswith("127.")]
    urls.append(f"http://{host}.local:{port}")
    return urls


def prepare_model(path, args):
    """За потреби один раз конвертує .pt у NCNN (швидше на процесорі Raspberry Pi)."""
    if not args.ncnn or not str(path).endswith(".pt"):
        return path
    import shutil
    # окрема папка для кожного imgsz; закінчення _ncnn_model потрібне Ultralytics для розпізнавання формату
    ncnn_dir = Path(f"{str(path)[:-3]}_{args.imgsz}_ncnn_model")
    if ncnn_dir.is_dir():
        return str(ncnn_dir)
    from ultralytics import YOLO
    print(f"Конвертую {path} у NCNN, imgsz={args.imgsz} (один раз, кілька хвилин)...", flush=True)
    out = YOLO(path).export(format="ncnn", imgsz=args.imgsz)
    shutil.move(str(out), str(ncnn_dir))
    return str(ncnn_dir)


# ---------------------------------------------------------------- джерело відео
class Source:
    def __init__(self, name, spec, thermal, args, settings, events):
        self.name, self.spec, self.thermal = name, spec, thermal
        self.args, self.settings, self.events = args, settings, events
        self.is_file = spec is not None and not spec.isdigit() and os.path.isfile(spec)
        self.lock = threading.Lock()
        self.cond = threading.Condition()
        self.frame, self.frame_id = None, 0
        self.raw_last, self.disp_last = None, None
        self.jpeg = None
        self.jpeg_id = 0
        self.status = "не підключено" if spec is None else "запуск"
        self.cap_fps = self.inf_fps = self.inf_ms = 0.0
        self.counts = {g: 0 for g in GROUPS}
        self.size = None
        self.model_ready = False
        self.error = None

    def start(self):
        if self.spec is None:
            return
        threading.Thread(target=self.capture_loop, daemon=True).start()
        threading.Thread(target=self.infer_loop, daemon=True).start()

    # --- захоплення: завжди тримаємо тільки найсвіжіший кадр
    def capture_loop(self):
        while running:
            cap = open_capture(self.spec, self.args.picam_size)
            if not cap.isOpened():
                self.status = "не вдалося відкрити"
                time.sleep(2)
                continue
            file_fps = cap.get(cv2.CAP_PROP_FPS) if self.is_file else 0
            period = 1.0 / file_fps if 0 < file_fps < 240 else 0
            self.status = "працює"
            fails, n, t0 = 0, 0, time.monotonic()
            while running:
                t_start = time.monotonic()
                if self.settings.get()["paused"]:
                    time.sleep(0.05)
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if self.is_file and fails < 5:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)   # відео по колу
                        continue
                    if fails >= 5:
                        self.status = "немає сигналу"
                        break
                    continue
                fails = 0
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
                n += 1
                el = time.monotonic() - t0
                if el >= 1.0:
                    self.cap_fps, n, t0 = n / el, 0, time.monotonic()
                if period:
                    time.sleep(max(0.0, period - (time.monotonic() - t_start)))
            cap.release()
            time.sleep(1)

    # --- детекція на найсвіжішому кадрі (старі кадри пропускаються)
    def infer_loop(self):
        try:
            self._infer_loop()
        except Exception as e:
            self.error = f"помилка моделі: {e}"
            print(f"[{self.name}] {self.error}", flush=True)

    def _infer_loop(self):
        from ultralytics import YOLO
        model_path = self.args.thermal_model if (self.thermal and self.args.thermal_model) else self.args.model
        model = YOLO(model_path, task="detect")   # окремий екземпляр на кожне джерело (потокобезпечно)
        id_to_group = class_groups(model.names)
        if not id_to_group:
            raise RuntimeError(f"у моделі немає відомих класів: {list(model.names.values())}")
        print(f"[{self.name}] модель {model_path}: {len(model.names)} класів, використовуються: {sorted(set(id_to_group.values()))}", flush=True)
        self.model_ready = True
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        last_id, n, t0 = -1, 0, time.monotonic()
        while running:
            with self.lock:
                frame, fid = self.frame, self.frame_id
            if frame is None or fid == last_id:
                time.sleep(0.003)
                continue
            last_id = fid
            s = self.settings.get()
            self.size = (frame.shape[1], frame.shape[0])

            if self.thermal:
                gray = thermal_to_gray(frame, clahe)
                inp = cv2.merge([gray, gray, gray])
                disp = apply_palette(gray, s["palette"])
            else:
                inp = frame
                disp = frame.copy()

            classes = [i for i, g in id_to_group.items() if s["groups"].get(g)]
            dets = []
            if classes:
                t = time.perf_counter()
                r = model.predict(inp, conf=s["conf"], imgsz=self.args.imgsz, classes=classes,
                                  device=self.args.device or None, verbose=False)[0]
                self.inf_ms = (time.perf_counter() - t) * 1000
                for b in r.boxes:
                    cls = int(b.cls[0])
                    if cls in id_to_group:
                        dets.append({"group": id_to_group[cls], "conf": float(b.conf[0]),
                                     "box": [float(v) for v in b.xyxy[0].tolist()]})

            self.counts = {g: sum(1 for d in dets if d["group"] == g) for g in GROUPS}
            if dets and s["save_crops"]:
                self.events.add(self.name, disp, dets)
            draw_dets(disp, dets)

            jpeg = cv2.imencode(".jpg", disp, [cv2.IMWRITE_JPEG_QUALITY, self.args.jpeg_quality])[1].tobytes()
            with self.cond:
                self.raw_last, self.disp_last = frame, disp
                self.jpeg = jpeg
                self.jpeg_id += 1
                self.cond.notify_all()

            n += 1
            el = time.monotonic() - t0
            if el >= 1.0:
                self.inf_fps, n, t0 = n / el, 0, time.monotonic()

    def mjpeg(self):
        last = -1
        while running:
            with self.cond:
                self.cond.wait_for(lambda: self.jpeg_id != last, timeout=1.0)
                jpeg, last = self.jpeg, self.jpeg_id
            if jpeg is None:
                jpeg = text_frame("NOT CONNECTED" if self.spec is None else "WAITING...")
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")

    def state(self):
        return {
            "configured": self.spec is not None, "spec": self.spec,
            "status": (self.error or
                       ("завантаження моделі" if self.spec is not None and self.status == "працює"
                        and not self.model_ready else self.status)),
            "cap_fps": round(self.cap_fps, 1), "inf_fps": round(self.inf_fps, 1),
            "inf_ms": round(self.inf_ms, 1), "counts": self.counts, "size": self.size,
        }


# ---------------------------------------------------------------- веб-сервер
def build_app(sources, settings, events):
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    @app.get("/stream/<name>")
    def stream(name):
        if name not in sources:
            return "not found", 404
        return Response(sources[name].mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/state")
    def state():
        after = int(request.args.get("after", 0))
        return jsonify({
            "sources": {k: v.state() for k, v in sources.items()},
            "settings": settings.get(),
            "events": events.list(after),
        })

    @app.post("/api/settings")
    def set_settings():
        settings.update(request.get_json(force=True, silent=True) or {})
        return jsonify(settings.get())

    @app.post("/api/snapshot")
    def snapshot():
        SNAP_DIR.mkdir(exist_ok=True)
        stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
        saved = []
        for name, src in sources.items():
            with src.cond:
                raw, disp = src.raw_last, src.disp_last
            if raw is not None:
                cv2.imwrite(str(SNAP_DIR / f"{stamp}_{name}_raw.png"), raw)
                cv2.imwrite(str(SNAP_DIR / f"{stamp}_{name}_det.jpg"), disp)
                saved.append(name)
        return jsonify({"saved": saved, "folder": str(SNAP_DIR)})

    @app.get("/crops/<path:fname>")
    def crops(fname):
        return send_from_directory(DET_DIR, fname)

    return app


def list_cameras(max_index=8):
    try:
        from picamera2 import Picamera2
        for i, info in enumerate(Picamera2.global_camera_info()):
            print(f"  [picam{i}] {info.get('Model')}  (CSI-камера Raspberry Pi)")
    except Exception:
        pass
    print("Перевіряю камери 0..%d ..." % (max_index - 1))
    for i in range(max_index):
        cap = open_capture(str(i))
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                print(f"  [{i}] {frame.shape[1]}x{frame.shape[0]}  fps={cap.get(cv2.CAP_PROP_FPS):.0f}")
        cap.release()


def main():
    p = argparse.ArgumentParser(description="RGB + тепловізор + YOLO у веб-сторінці")
    p.add_argument("--rgb", help="індекс USB-камери, picam / picam0 / picam1 (CSI), файл відео або URL")
    p.add_argument("--thermal", help="індекс USB-камери, picam..., файл відео або URL")
    p.add_argument("--picam-size", type=parse_size, default=(1280, 720), help="роздільність CSI-камери, напр. 1280x720")
    p.add_argument("--ncnn", action="store_true", help="конвертувати модель у NCNN (рекомендовано на Raspberry Pi)")
    p.add_argument("--model", default="yolo11n.pt", help="модель YOLO для RGB (і для тепла, якщо не задано --thermal-model)")
    p.add_argument("--thermal-model", default=None, help="окрема модель для тепловізора")
    p.add_argument("--conf", type=float, default=0.25, help="поріг впевненості")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="", help="'' = авто, 'cpu', '0' (GPU NVIDIA), 'mps' (Mac)")
    p.add_argument("--jpeg-quality", type=int, default=80)
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = доступно з інших комп'ютерів у мережі")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--browser", action="store_true", help="відкрити сторінку в браузері на цьому ж комп'ютері")
    p.add_argument("--list-cameras", action="store_true")
    p.add_argument("--prepare-only", action="store_true", help="лише підготувати модель (NCNN) і вийти")
    args = p.parse_args()
    args.rgb = args.rgb or None          # порожній рядок з config.env = камера не підключена
    args.thermal = args.thermal or None

    if args.list_cameras:
        list_cameras()
        return
    if args.prepare_only:
        print("Модель:", prepare_model(args.model, args))
        if args.thermal_model:
            print("Модель IR:", prepare_model(args.thermal_model, args))
        return
    if not args.rgb and not args.thermal:
        print("Вкажіть хоча б одне джерело: --rgb ... та/або --thermal ...  (див. --help)")
        print("Підказка: python app.py --list-cameras")
        return

    args.model = prepare_model(args.model, args)
    if args.thermal_model:
        args.thermal_model = prepare_model(args.thermal_model, args)

    settings = Settings(args.conf)
    events = EventLog()
    sources = {
        "rgb": Source("rgb", args.rgb, False, args, settings, events),
        "thermal": Source("thermal", args.thermal, True, args, settings, events),
    }
    for s in sources.values():
        s.start()

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print("\nСторінка на цьому пристрої:", url)
    if args.host in ("0.0.0.0", "::"):
        print("Відкрийте на ПК в тій самій мережі:")
        for u in local_addresses(args.port):
            print("   ", u)
    print(f"Знахідки: {DET_DIR}\nЗупинити: Ctrl+C\n", flush=True)
    if args.browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()

    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # без логу кожного запиту
    app = build_app(sources, settings, events)
    try:
        app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
    finally:
        global running
        running = False


if __name__ == "__main__":
    main()
