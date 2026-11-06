#!/usr/bin/env python3
"""
Донавчання YOLO на датасеті з prepare_data.py + оцінка + експорт у NCNN для Raspberry Pi.

Приклади (на ПК з відеокартою NVIDIA або в Google Colab):
    python train.py --target thermal                       # YOLO11s, 100 епох, 640 px
    python train.py --target rgb --model yolo11n.pt
    python train.py --target thermal --epochs 1 --imgsz 320 --model yolo11n.pt   # швидка перевірка

Результат у папці trained/:
    sar_thermal.pt                    - модель
    sar_thermal_416_ncnn_model/       - готова для Pi (і _320_ncnn_model)
    sar_thermal_metrics.txt           - точність по класах
Скопіюйте їх у папку thermal_viewer на Pi і вкажіть у config.env:
    ARGS="--ncnn --imgsz 416 --thermal-model sar_thermal.pt"
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target", choices=["thermal", "rgb"], required=True)
    p.add_argument("--model", default="yolo11s.pt", help="стартова модель: yolo11n.pt (швидша) або yolo11s.pt (точніша)")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640, help="розмір при навчанні")
    p.add_argument("--batch", type=float, default=-1, help="-1 = автопідбір під пам'ять GPU")
    p.add_argument("--device", default=None, help="0 = перша GPU, cpu = процесор")
    p.add_argument("--export-imgsz", type=int, nargs="+", default=[416, 320], help="розміри NCNN-моделей для Pi")
    p.add_argument("--time", type=float, default=None, help="ліміт часу в годинах (кількість епох підбирається сама)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--resume", action="store_true", help="продовжити перерване навчання")
    args = p.parse_args()
    if not 0 < args.batch < 1:          # 0.7 = частка пам'яті GPU, інакше ціле число
        args.batch = int(args.batch)

    from ultralytics import YOLO

    data = ROOT / "datasets" / f"sar_{args.target}.yaml"
    if not data.exists():
        raise SystemExit(f"Немає {data}. Спочатку: python prepare_data.py --target {args.target}")
    name = f"sar_{args.target}"
    thermal = args.target == "thermal"

    if args.resume:
        model = YOLO(ROOT / "runs" / name / "weights" / "last.pt")
        model.train(resume=True)
    else:
        model = YOLO(args.model)
        model.train(
            data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
            device=args.device, project=str(ROOT / "runs"), name=name, exist_ok=True,
            time=args.time, workers=args.workers,
            patience=30,               # зупинка, якщо 30 епох без покращення
            # аугментації під зйомку згори
            flipud=0.5, fliplr=0.5,    # згори немає «верху» і «низу»
            degrees=10.0, scale=0.5, translate=0.1,
            mosaic=1.0, close_mosaic=10,
            # тепловізор: кольору немає, тому тон і насиченість не змінюємо
            hsv_h=0.0 if thermal else 0.015,
            hsv_s=0.0 if thermal else 0.7,
            hsv_v=0.4,
        )

    best = ROOT / "runs" / name / "weights" / "best.pt"
    out = ROOT / "trained"
    out.mkdir(exist_ok=True)
    final = out / f"{name}.pt"
    shutil.copy2(best, final)

    # ---- оцінка на окремій тестовій вибірці (якщо є), інакше на val
    model = YOLO(final)
    split = "test" if "test:" in data.read_text() else "val"
    m = model.val(data=str(data), split=split, imgsz=args.imgsz, device=args.device, plots=False)
    lines = [f"Модель: {final.name}   вибірка: {split}   imgsz: {args.imgsz}", ""]
    lines.append(f"{'клас':<10}{'precision':>10}{'recall':>10}{'mAP50':>10}{'mAP50-95':>10}")
    per_class = {int(c): m.box.class_result(k) for k, c in enumerate(m.box.ap_class_index)}
    for i, cname in model.names.items():
        pr, rc, ap50, ap = per_class.get(int(i), (0, 0, 0, 0))
        lines.append(f"{cname:<10}{pr:>10.3f}{rc:>10.3f}{ap50:>10.3f}{ap:>10.3f}")
    lines.append(f"{'всього':<10}{m.box.mp:>10.3f}{m.box.mr:>10.3f}{m.box.map50:>10.3f}{m.box.map:>10.3f}")
    lines += ["", "recall = яка частка об'єктів знайдена; precision = яка частка тривог справжня."]
    report = "\n".join(lines)
    (out / f"{name}_metrics.txt").write_text(report, encoding="utf-8")
    print("\n" + report)

    # ---- експорт у NCNN з назвами, які шукає thermal_viewer/app.py
    for sz in args.export_imgsz:
        dst = out / f"{name}_{sz}_ncnn_model"
        if dst.exists():
            shutil.rmtree(dst)
        exported = YOLO(final).export(format="ncnn", imgsz=sz)
        shutil.move(str(exported), str(dst))
        print("NCNN:", dst)

    print(f"\nГотово. Скопіюйте вміст {out} у папку thermal_viewer на Raspberry Pi.")


if __name__ == "__main__":
    main()
