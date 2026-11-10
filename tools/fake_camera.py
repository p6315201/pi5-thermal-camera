#!/usr/bin/env python3
"""
fake_camera.py - заглушка замість програми camera: слухає UDP 127.0.0.1:1111 і друкує
команди, які надсилає rc.mav.py / rc.msp.py ("shut", "img <яскравість> <контраст> <agc>").
Запускай ТІЛЬКИ коли справжня camera зупинена (порт один): sudo systemctl stop camera
"""
import socket
import time

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 1111))
print("[cam] слухаю 127.0.0.1:1111", flush=True)
t0 = time.time()
while True:
    data, _ = s.recvfrom(1024)
    msg = data.decode(errors="replace")
    note = ""
    p = msg.split()
    if p and p[0] == "img" and len(p) == 4:
        note = f"   -> яскравість={p[1]} контраст={p[2]} agc={p[3]}"
    elif msg == "shut":
        note = "   -> калібрування шатером"
    print(f"[cam {time.time() - t0:6.1f}s] {msg}{note}", flush=True)
