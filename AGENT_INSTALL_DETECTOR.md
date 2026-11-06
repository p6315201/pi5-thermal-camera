# Завдання для агента: встановити пошук людей і техніки (YOLO, тепловізор + RGB) на Raspberry Pi 5

Ти працюєш **на Raspberry Pi 5** (shell з sudo, є інтернет). Мета: Pi бере кадри з тепловізора
і RGB-камери, шукає на них людей і техніку моделлю YOLO, сам роздає веб-сторінку з відео та
списком знахідок. Оператор відкриває її з ПК у браузері. Призначення: пошуково-рятувальні польоти,
допомога оператору помічати людей і загублену техніку.

Усе потрібне лежить у цьому репозиторії:

| Шлях | Що це |
|---|---|
| `detector/app.py`, `index.html` | програма і веб-сторінка |
| `detector/setup_pi.sh` | встановлення + автозапуск (systemd `thermal-viewer`) |
| `detector/config.env.example` | шаблон налаштувань (камери, параметри) → `config.env` |
| `detector/sar_thermal.pt` | модель для тепловізора (YOLO11s, класи `person`, `vehicle`) |
| `detector/sar_thermal_416_ncnn_model/`, `_320_ncnn_model/` | вона ж, готова для CPU Pi (NCNN FP16) |
| `detector/yolo11n.pt` + `yolo11n_*_ncnn_model/` | стандартна COCO-модель для RGB-камери |
| `detector/model_metrics/` | результати перевірки точності |
| `detector/SHA256SUMS` | контрольні суми моделей |
| `training/` | скрипти донавчання (запускаються на ПК з GPU або в Colab, **не на Pi**) |

`AGENT_INSTRUCTIONS.md` у цьому ж репозиторії — **окреме** завдання (запуск SPI-тепловізора
Tiny1-C через `/usr/bin/camera`). Не виконуй його, якщо користувач про це не просив.

## 1. Перевір систему

```bash
cat /etc/os-release | grep -E "PRETTY_NAME|VERSION_CODENAME"
```
```bash
uname -m
```
```bash
free -h && df -h ~
```
Потрібно: Raspberry Pi OS 64-bit (`aarch64`), Bookworm або новіша, ≥2 ГБ вільного місця.
Якщо `armv7l` (32-біт) — зупинись і повідом: ultralytics/NCNN потрібна 64-бітна ОС.

## 2. Отримай файли

```bash
sudo apt update && sudo apt install -y git
```
```bash
git clone https://github.com/p6315201/pi5-thermal-camera.git ~/pi5-thermal-camera
```
Якщо репозиторій уже є — `git -C ~/pi5-thermal-camera pull`.
```bash
cd ~/pi5-thermal-camera/detector && sha256sum -c SHA256SUMS
```
Усі рядки мають бути `OK`. Якщо ні — файл моделі пошкоджений: повтори `git pull`, не запускай з ним.

## 3. Знайди камери

Підключи камери, потім:
```bash
ls -l /dev/video* 2>/dev/null; rpicam-hello --list-cameras 2>/dev/null || libcamera-hello --list-cameras
```
```bash
sudo apt install -y v4l-utils && v4l2-ctl --list-devices
```
- **Тепловізор з USB (UVC)** — це `/dev/videoN`; потрібен індекс N, на якому реально йдуть кадри
  (у одного пристрою буває кілька `/dev/video*`, кадри зазвичай на першому).
- **CSI-камера Raspberry Pi** — у `config.env` пишеться `picam` (або `picam0` / `picam1`).
- Після кроку 4 точніше перевірити так: `.venv/bin/python app.py --list-cameras`.

**Увага щодо Tiny1-C по SPI** (з `AGENT_INSTRUCTIONS.md`): він не створює `/dev/video*`, його читає
лише `/usr/bin/camera`, і детектор напряму з ним не працює. Не намагайся одночасно відкрити SPI
двома програмами. Якщо тепловізор саме такий — повідом користувачу і спитай, що робити далі.

## 4. Встанови

```bash
cd ~/pi5-thermal-camera/detector && chmod +x setup_pi.sh && ./setup_pi.sh
```
Скрипт ставить пакети (`python3-picamera2` тощо), створює `.venv`, встановлює `requirements.txt`
+ `ncnn`, підхоплює готові NCNN-моделі і вмикає сервіс `thermal-viewer` з автозапуском.
Встановлення pip-пакетів на Pi триває 5–15 хв. Якщо падає на якомусь пакеті — покажи помилку
користувачу; не змінюй версії навмання.

## 5. Налаштуй камери

Відредагуй `~/pi5-thermal-camera/detector/config.env` (`setup_pi.sh` створює його з `config.env.example`):
```
RGB=picam        # або індекс USB-камери, або порожньо, якщо RGB немає
THERMAL=0        # індекс тепловізора з кроку 3, або порожньо
ARGS="--ncnn --imgsz 416 --thermal-model sar_thermal.pt --port 8000"
```
```bash
sudo systemctl restart thermal-viewer
```

## 6. Перевір роботу

```bash
systemctl status thermal-viewer --no-pager
```
```bash
journalctl -u thermal-viewer -n 50 --no-pager
```
```bash
curl -s http://127.0.0.1:8000/api/state | head -c 800; echo
```
Очікувано: сервіс `active (running)`, у лозі немає помилок відкриття камери, `/api/state`
повертає JSON з камерами і FPS. Сторінка з ПК у тій самій мережі:
`http://<IP-Pi>:8000` (IP: `hostname -I`) або `http://<hostname>.local:8000`.

Перевірка без камер (якщо камери ще не підключені):
```bash
sudo systemctl stop thermal-viewer
```
```bash
cd ~/pi5-thermal-camera/detector && .venv/bin/python app.py --thermal <файл.mp4> --ncnn --imgsz 416 --thermal-model sar_thermal.pt --port 8000
```

## 7. Швидкість

Орієнтовно на CPU Pi 5 (одна камера): `sar_thermal` 416 px ≈ 6–9 FPS, 320 px ≈ 10–14 FPS.
З двома камерами — приблизно вдвічі менше на кожну. Якщо FPS замалий:
- у `config.env` поставити `--imgsz 320` (готова модель `sar_thermal_320_ncnn_model` вже є);
- перевірити охолодження: `vcgencmd measure_temp` і `vcgencmd get_throttled` (має бути `0x0`).

## 8. Що НЕ робити

- Не видаляй і не перезаписуй файли моделей (`*.pt`, `*_ncnn_model/`).
- Не запускай донавчання на Pi (`training/` — для ПК з GPU або Google Colab).
- Не змінюй `config.txt`/`cmdline.txt` і не встановлюй нічого поза кроками вище без згоди користувача.

## 9. Звіт користувачу

Повідом: версію ОС, які камери знайдено і з якими індексами, статус сервісу `thermal-viewer`,
відповідь `/api/state` (FPS по камерах), адресу сторінки для ПК і будь-які помилки з логу.

---

### Довідка: точність моделі `sar_thermal`

579 тестових теплових кадрів HIT-UAV (висота 60–130 м), NCNN FP16, 416 px, поріг 0.25:

| Клас | Знайдено (recall) | Тривоги справжні (precision) |
|---|---|---|
| person | 80% | 83% |
| vehicle | 84% | 86% |

Стандартна `yolo11n` на тих самих кадрах: 4% і 3%. Модель навчена на відкритих даних HIT-UAV
та VisDrone; на власних кадрах з вашої камери точність може відрізнятися — додайте їх у
`training/own_data/` і донавчіть (див. `training/README.md`).
