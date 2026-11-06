# Пошук RGB + тепловізор на Raspberry Pi 5

Raspberry Pi бере кадри з обох камер, запускає YOLO і сам роздає веб-сторінку.
На ПК у тій самій мережі сторінку відкривають у браузері: `http://<IP-Pi>:8000` або `http://<ім'я-Pi>.local:8000`.

## Встановлення на Pi (один раз)

1. Скопіюйте цю папку на Pi, наприклад у `~/thermal_viewer`.
2. Запустіть:
   ```bash
   cd ~/thermal_viewer && ./setup_pi.sh
   ```
   Скрипт встановить пакети, підготує модель (NCNN) і ввімкне автозапуск при старті Pi.

## Налаштування

Камери і параметри задаються в `config.env`, після змін:
```bash
sudo systemctl restart thermal-viewer
```
Які камери бачить Pi: `.venv/bin/python app.py --list-cameras`
Лог роботи: `journalctl -u thermal-viewer -f`

## Ручний запуск (без автозапуску)

```bash
sudo systemctl stop thermal-viewer
.venv/bin/python app.py --rgb picam --thermal 0 --ncnn --imgsz 416 --thermal-model sar_thermal.pt
```

## Моделі

| Камера | Модель | Що знаходить |
|---|---|---|
| тепловізор | `sar_thermal` (YOLO11s, донавчена на HIT-UAV + VisDrone) | person, vehicle |
| RGB | `yolo11n` (стандартна COCO) | person, vehicle, aircraft |

Готові NCNN-версії для Pi: `sar_thermal_416_ncnn_model` (за замовчуванням) і `sar_thermal_320_ncnn_model` (швидша).
Для 320 у `config.env` поставте `--imgsz 320`.

Точність на 579 тестових теплових кадрах HIT-UAV (висота 60–130 м), NCNN 416:
люди знайдено 80% (тривоги справжні 83%), техніка 84% (86%).
Стандартна yolo11n на тих самих кадрах: 4% і 3%. Деталі в `model_metrics/`.
