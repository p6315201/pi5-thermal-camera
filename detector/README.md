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
.venv/bin/python app.py --rgb picam --thermal 0 --ncnn --imgsz 416 --thermal-model sar_thermal_n.pt
```

## Моделі

| Камера | Модель | Що знаходить |
|---|---|---|
| тепловізор | `sar_thermal_n` (YOLO11n, **за замовчуванням**, швидка) | person, vehicle |
| тепловізор | `sar_thermal` (YOLO11s, трохи точніша, у ~2.5 раза повільніша) | person, vehicle |
| RGB | `yolo11n` (стандартна COCO) | person, vehicle, aircraft |

Обидві теплові моделі донавчені на HIT-UAV + VisDrone. Для кожної є готові NCNN-версії для Pi:
`<модель>_416_ncnn_model` і `<модель>_320_ncnn_model` (швидша). Для 320 у `config.env` поставте `--imgsz 320`.
Перемкнути на 11s: `--thermal-model sar_thermal.pt`.

Точність на 579 тестових теплових кадрах HIT-UAV (висота 60–130 м), NCNN, поріг 0.25
(знайдено / тривоги справжні):

| Модель | person | vehicle | час кадру* |
|---|---|---|---|
| `sar_thermal_n` 416 | 78% / 80% | 86% / 82% | 28 мс |
| `sar_thermal` 416 | 80% / 83% | 84% / 86% | 76 мс |
| `sar_thermal_n` 320 | 65% / 75% | 79% / 80% | 22 мс |
| `sar_thermal` 320 | 68% / 77% | 78% / 85% | 47 мс |
| стандартна `yolo11n` | 4% / 3% | — | — |

\* виміряно на Mac (CPU); на Raspberry Pi 5 приблизно у 2–3 рази довше. Деталі в `model_metrics/`.
