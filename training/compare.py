#!/usr/bin/env python3
"""
Порівнює моделі на тестовій вибірці за однаковими правилами (класи person / vehicle),
зокрема стандартну COCO-модель, класи якої зводяться до person/vehicle за назвами.

    python compare.py --data datasets/sar_thermal.yaml --models yolo11n.pt trained/sar_thermal.pt --imgsz 640
"""
import argparse
from pathlib import Path

import numpy as np

GROUP = {"person": 0, "pedestrian": 0, "people": 0,
         "vehicle": 1, "car": 1, "truck": 1, "bus": 1, "van": 1, "motorcycle": 1, "bicycle": 1,
         "train": 1, "boat": 1, "motor": 1, "tricycle": 1, "awning-tricycle": 1}
NAMES = ["person", "vehicle"]


def iou(a, b):
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


def ap101(rec, prec):
    mpre = np.concatenate(([1.0], prec, [0.0]))
    mrec = np.concatenate(([0.0], rec, [1.0]))
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    x = np.linspace(0, 1, 101)
    return float(getattr(np, "trapezoid", getattr(np, "trapz", None))(np.interp(x, mrec, mpre), x))


def evaluate(model_path, images, imgsz, conf_report):
    from ultralytics import YOLO
    model = YOLO(model_path, task="detect")
    cmap = {int(i): GROUP[n.lower()] for i, n in model.names.items() if n.lower() in GROUP}
    preds = {0: [], 1: []}     # (conf, is_tp)
    n_gt = {0: 0, 1: 0}
    for img in images:
        r = model.predict(str(img), imgsz=imgsz, conf=0.001, iou=0.6, max_det=300, verbose=False,
                          classes=list(cmap))[0]
        h, w = r.orig_shape
        lbl = img.parent.parent.parent / "labels" / img.parent.name / f"{img.stem}.txt"
        gt = np.loadtxt(lbl, ndmin=2) if lbl.exists() and lbl.stat().st_size else np.zeros((0, 5))
        boxes = r.boxes.xyxy.cpu().numpy(); confs = r.boxes.conf.cpu().numpy()
        cls = np.array([cmap[int(c)] for c in r.boxes.cls.cpu().numpy()], dtype=int)
        for c in (0, 1):
            g = gt[gt[:, 0] == c]
            gb = np.stack([(g[:, 1] - g[:, 3] / 2) * w, (g[:, 2] - g[:, 4] / 2) * h,
                           (g[:, 1] + g[:, 3] / 2) * w, (g[:, 2] + g[:, 4] / 2) * h], 1) if len(g) else np.zeros((0, 4))
            n_gt[c] += len(gb)
            m = cls == c
            pb, pc = boxes[m], confs[m]
            order = np.argsort(-pc); pb, pc = pb[order], pc[order]
            used = np.zeros(len(gb), bool)
            ious = iou(pb, gb) if len(pb) and len(gb) else np.zeros((len(pb), 0))
            for k in range(len(pb)):
                tp = False
                if ious.shape[1]:
                    cand = np.where((ious[k] >= 0.5) & ~used)[0]
                    if len(cand):
                        j = cand[np.argmax(ious[k, cand])]; used[j] = True; tp = True
                preds[c].append((pc[k], tp))
    res = {}
    for c in (0, 1):
        arr = sorted(preds[c], key=lambda t: -t[0])
        conf = np.array([a[0] for a in arr]); tp = np.array([a[1] for a in arr], float)
        ctp, cfp = np.cumsum(tp), np.cumsum(1 - tp)
        rec = ctp / max(n_gt[c], 1); prec = ctp / np.maximum(ctp + cfp, 1e-9)
        k = (conf >= conf_report).sum()
        res[NAMES[c]] = dict(ap50=ap101(rec, prec) if len(arr) else 0.0,
                             recall=float(rec[k - 1]) if k else 0.0,
                             precision=float(prec[k - 1]) if k else 0.0, n=n_gt[c])
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--split", default="test")
    p.add_argument("--conf", type=float, default=0.25, help="поріг для recall/precision")
    p.add_argument("--out", default=None, help="зберегти таблицю у файл")
    args = p.parse_args()
    d = dict(l.split(": ", 1) for l in Path(args.data).read_text(encoding="utf-8").splitlines()
             if ": " in l and not l.startswith(" "))   # простий розбір нашого yaml
    images = sorted((Path(d["path"]) / d[args.split]).glob("*.jpg"))
    lines = [f"Вибірка: {args.split} ({len(images)} кадрів), imgsz {args.imgsz}, поріг {args.conf}, IoU 0.5", "",
             f"{'модель':<28}{'клас':<9}{'знайдено':>10}{'тривоги OK':>12}{'AP50':>8}"]
    for mp in args.models:
        r = evaluate(mp, images, args.imgsz, args.conf)
        for cname, v in r.items():
            lines.append(f"{Path(mp).name:<28}{cname:<9}{v['recall']:>9.0%}{v['precision']:>12.0%}{v['ap50']:>8.3f}")
    lines += ["", "знайдено = recall (частка справжніх об'єктів, які модель знайшла)",
              "тривоги OK = precision (частка рамок, що справді є об'єктом)"]
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
