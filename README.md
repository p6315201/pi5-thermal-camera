# pi5-thermal-camera

Тепловізор і пошук людей та техніки на Raspberry Pi 5 для пошуково-рятувальних польотів.

| Що | Де | Інструкція |
|---|---|---|
| Детектор YOLO (тепловізор + RGB), веб-сторінка для ПК | `detector/` | [AGENT_INSTALL_DETECTOR.md](AGENT_INSTALL_DETECTOR.md), [detector/README.md](detector/README.md) |
| Донавчання моделі (ПК з GPU / Colab) | `training/` | [training/README.md](training/README.md) |
| Тепловізор InfiRay Tiny1-C по SPI + I2C | `files/`, `tiny1c_spi.py` | [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) |

Швидкий старт детектора на Pi 5 (Raspberry Pi OS 64-bit):
```bash
git clone https://github.com/p6315201/pi5-thermal-camera.git ~/pi5-thermal-camera
cd ~/pi5-thermal-camera/detector && ./setup_pi.sh
```
Сторінка: `http://<IP-Pi>:8000`.
