#!/usr/bin/env bash
# Встановлення на Raspberry Pi 5 (Raspberry Pi OS 64-bit) + автозапуск при ввімкненні.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
[ -f config.env ] || cp config.env.example config.env

echo "== Системні пакети =="
sudo apt update
sudo apt install -y python3-venv python3-picamera2 libgl1

echo "== Python-оточення =="
# --system-site-packages, щоб у venv був доступний picamera2 з системи
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt ncnn pnnx

echo "== Конвертація моделі в NCNN =="
set -a; . ./config.env; set +a
.venv/bin/python app.py $ARGS --prepare-only

echo "== Автозапуск =="
sed "s|__DIR__|$DIR|g; s|__USER__|$USER|g" thermal-viewer.service | sudo tee /etc/systemd/system/thermal-viewer.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now thermal-viewer

echo
echo "Готово. Сторінка з ПК: http://$(hostname -I | awk '{print $1}'):8000  або  http://$(hostname).local:8000"
echo "Лог:        journalctl -u thermal-viewer -f"
echo "Камери:     .venv/bin/python app.py --list-cameras"
echo "Налаштування: config.env, потім  sudo systemctl restart thermal-viewer"
