#!/usr/bin/env python3
"""
Збирає датасет для донавчання в єдиному форматі YOLO з двома класами:
    0 = person   (люди)
    1 = vehicle  (техніка: авто, вантажівки, автобуси, мото, велосипеди тощо)

Джерела:
    hituav     HIT-UAV: тепловізор 640x512 з дрона, 60-130 м, день/ніч (~2900 кадрів, ~200 МБ)
    visdrone   VisDrone2019: RGB з дрона, дрібні об'єкти (~8600 кадрів, ~2 ГБ)
    own        ваші власні кадри: own_data/<target>/images + labels (YOLO, класи 0/1 як вище)

Приклади:
    python prepare_data.py --target thermal --sources hituav visdrone own
    python prepare_data.py --target rgb     --sources visdrone own
    python prepare_data.py --target thermal --sources hituav --limit 100   # швидка перевірка

Для --target thermal кадри VisDrone перетворюються в сірі (форми об'єктів згори),
кольорові аугментації при навчанні вимикаються в train.py.
"""
import argparse
import json
import random
import shutil
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent
NAMES = {0: "person", 1: "vehicle"}

# Відповідність класів джерела -> наші класи (None = пропустити)
HITUAV_MAP = {0: 0, 1: 1, 2: 1, 3: 1, 4: None}           # Person, Car, Bicycle, OtherVehicle, DontCare
VISDRONE_MAP = {0: 0, 1: 0, 2: 1, 3: 1, 4: 1, 5: 1,      # pedestrian, people, bicycle, car, van, truck,
                6: 1, 7: 1, 8: 1, 9: 1}                  # tricycle, awning-tricycle, bus, motor

HIT_REPO = "suojiashun/HIT-UAV-Infrared-Thermal-Dataset"
HIT_RAW = f"https://raw.githubusercontent.com/{HIT_REPO}/main/"


def remap_label(src, dst, mapping):
    lines = []
    if src.exists():
        for line in src.read_text().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            new = mapping.get(int(float(parts[0])))
            if new is not None:
                lines.append(" ".join([str(new)] + parts[1:]))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def put_image(src, dst, gray=False, max_side=None):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not gray and not max_side:
        shutil.copy2(src, dst)
        return
    img = cv2.imread(str(src), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if max_side and max(img.shape[:2]) > max_side:
        k = max_side / max(img.shape[:2])
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(dst.with_suffix(".jpg")), img, [cv2.IMWRITE_JPEG_QUALITY, 92])


# ------------------------------------------------------------------ HIT-UAV
def fetch(url, dst):
    if dst.exists() and dst.stat().st_size > 0:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            dst.write_bytes(data)
            return
        except Exception as e:
            if attempt == 3:
                print(f"  не вдалося: {url} ({e})")


def download_hituav(raw_dir, limit=None):
    """Качає зображення і YOLO-розмітку HIT-UAV поштучно з GitHub (без git і без 400 МБ архіву)."""
    print("HIT-UAV: отримую список файлів...")
    api = f"https://api.github.com/repos/{HIT_REPO}/git/trees/main?recursive=1"
    with urllib.request.urlopen(api, timeout=60) as r:
        tree = json.load(r)["tree"]
    jobs = []
    for split in ("train", "val", "test"):
        imgs = sorted(t["path"] for t in tree if t["path"].startswith(f"normal_json/{split}/")
                      and t["path"].endswith(".jpg"))
        if limit:
            imgs = imgs[: max(1, limit if split == "train" else limit // 4)]
        for p in imgs:
            stem = Path(p).stem
            jobs.append((HIT_RAW + p, raw_dir / "images" / split / f"{stem}.jpg"))
            jobs.append((HIT_RAW + f"yolo_labels/{split}/{stem}.txt", raw_dir / "labels" / split / f"{stem}.txt"))
    print(f"HIT-UAV: завантажую {len(jobs) // 2} кадрів...")
    with ThreadPoolExecutor(32) as ex:
        for i, _ in enumerate(ex.map(lambda j: fetch(*j), jobs), 1):
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)}")
    return raw_dir


def add_hituav(out, args):
    raw = download_hituav(ROOT / "datasets" / "raw" / "hituav", args.limit)
    n = 0
    for split, dst_split in (("train", "train"), ("val", "val"), ("test", "test")):
        for img in sorted((raw / "images" / split).glob("*.jpg")):
            name = f"hit_{img.stem}"
            put_image(img, out / "images" / dst_split / f"{name}.jpg")
            remap_label(raw / "labels" / split / f"{img.stem}.txt", out / "labels" / dst_split / f"{name}.txt",
                        HITUAV_MAP)
            n += 1
    print(f"HIT-UAV: додано {n} кадрів")


# ------------------------------------------------------------------ VisDrone
def add_visdrone(out, args):
    from ultralytics.data.utils import check_det_dataset
    print("VisDrone: перевіряю/завантажую (~2 ГБ, один раз)...")
    info = check_det_dataset("VisDrone.yaml", autodownload=True)
    root = Path(info["path"])
    gray = args.target == "thermal"
    n = 0
    for split, dst_split in (("train", "train"), ("val", "val"), ("test", "test")):
        imgs = sorted((root / "images" / split).glob("*.jpg"))
        if args.limit:
            imgs = imgs[: args.limit if split == "train" else max(1, args.limit // 4)]
        for img in imgs:
            name = f"vis_{img.stem}"
            put_image(img, out / "images" / dst_split / f"{name}.jpg", gray=gray, max_side=1344)
            remap_label(root / "labels" / split / f"{img.stem}.txt", out / "labels" / dst_split / f"{name}.txt",
                        VISDRONE_MAP)
            n += 1
    print(f"VisDrone: додано {n} кадрів" + (" (у сірому)" if gray else ""))


# ------------------------------------------------------------------ власні дані
def add_own(out, args):
    src = ROOT / "own_data" / args.target
    imgs = sorted(p for p in (src / "images").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"))
    if not imgs:
        print(f"Власні дані: у {src / 'images'} нічого немає, пропускаю")
        return
    random.Random(0).shuffle(imgs)
    n_val = max(1, int(len(imgs) * 0.15))
    for i, img in enumerate(imgs):
        split = "val" if i < n_val else "train"
        # власні кадри найцінніші: дублюємо їх у train, щоб модель бачила їх частіше
        copies = 1 if split == "val" else args.own_repeat
        for c in range(copies):
            name = f"own_{img.stem}" + (f"_r{c}" if c else "")
            put_image(img, out / "images" / split / f"{name}.jpg",
                      gray=(args.target == "thermal"))
            lbl_src = src / "labels" / f"{img.stem}.txt"
            lbl_dst = out / "labels" / split / f"{name}.txt"
            lbl_dst.parent.mkdir(parents=True, exist_ok=True)
            if lbl_src.exists():
                shutil.copy2(lbl_src, lbl_dst)
            else:
                lbl_dst.write_text("")   # кадр без розмітки = негативний приклад (нічого немає)
    print(f"Власні дані: {len(imgs)} кадрів ({n_val} у val, train x{args.own_repeat})")


def main():
    p = argparse.ArgumentParser(description="Підготовка датасету person/vehicle")
    p.add_argument("--target", choices=["thermal", "rgb"], required=True, help="для якої камери модель")
    p.add_argument("--sources", nargs="+", default=None, choices=["hituav", "visdrone", "own"])
    p.add_argument("--limit", type=int, default=None, help="обмежити кількість кадрів (для перевірки)")
    p.add_argument("--own-repeat", type=int, default=3, help="скільки разів дублювати власні кадри в train")
    args = p.parse_args()
    if args.sources is None:
        args.sources = ["hituav", "visdrone", "own"] if args.target == "thermal" else ["visdrone", "own"]

    out = ROOT / "datasets" / f"sar_{args.target}"
    if out.exists():
        shutil.rmtree(out)
    for src in args.sources:
        {"hituav": add_hituav, "visdrone": add_visdrone, "own": add_own}[src](out, args)

    for split in ("train", "val"):
        if not any((out / "images" / split).glob("*")):
            sys.exit(f"Помилка: немає кадрів у {split}. Перевірте джерела.")
    has_test = any((out / "images" / "test").glob("*"))

    yaml_path = ROOT / "datasets" / f"sar_{args.target}.yaml"
    yaml_path.write_text(
        f"path: {out.as_posix()}\ntrain: images/train\nval: images/val\n"
        + ("test: images/test\n" if has_test else "")
        + "names:\n" + "".join(f"  {k}: {v}\n" for k, v in NAMES.items()),
        encoding="utf-8")

    counts = {s: len(list((out / "images" / s).glob("*"))) for s in ("train", "val", "test")}
    objs = [0, 0]
    for lbl in (out / "labels" / "train").glob("*.txt"):
        for line in lbl.read_text().splitlines():
            objs[int(line.split()[0])] += 1
    print(f"\nГотово: {yaml_path}")
    print(f"  кадрів: train {counts['train']}, val {counts['val']}, test {counts['test']}")
    print(f"  об'єктів у train: person {objs[0]}, vehicle {objs[1]}")


if __name__ == "__main__":
    main()
