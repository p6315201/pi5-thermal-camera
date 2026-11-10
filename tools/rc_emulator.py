#!/usr/bin/env python3
"""
rc_emulator.py - емулятор пульта: удає польотник і шле MAVLink HEARTBEAT + RC_CHANNELS,
щоб перевірити rc.mav.py і камеру без справжнього пульта/польотника.

Два режими:
  без прапорців  - сам слухає UDP 127.0.0.1:14551 (замість mavlink-router).
                   Перед запуском зупини роутер: sudo systemctl stop mavlink-router
  --router       - шле через працюючий mavlink-router (порт 14550), роутер пересилає
                   у скрипт на 14551. Польотник при цьому краще від'єднати/вимкнути,
                   інакше його справжні канали змішаються з емульованими.

Команди (вводь і тисни Enter):
  7 1900        канал 7 = 1900 (будь-який канал 1..18, значення 800..2200)
  shut          перемкнути канал шатера (ch7) 1000 <-> 2000
  bright 1700   яскравість (ch9)
  agc 1550      AGC (ch13)
  contr 1400    контраст (ch6)
  demo          автоматичний сценарій: яскравість, контраст, AGC, шатер
  show          показати поточні канали
  q             вихід
"""
import argparse
import sys
import threading
import time
from pymavlink import mavutil

NAMES = {"bright": 9, "agc": 13, "contr": 6}
CH_SHUT = 7


class Emulator:
    def __init__(self, via_router):
        url = "udpout:127.0.0.1:14550" if via_router else "udpin:127.0.0.1:14551"
        self.mav = mavutil.mavlink_connection(url, source_system=1, source_component=1)
        self.ch = [1500] * 18
        self.ch[CH_SHUT - 1] = 1000
        self.lock = threading.Lock()
        self.run = True
        self.t0 = time.time()
        self.client_seen = via_router
        print(f"[emu] {url}")
        if not via_router:
            print("[emu] чекаю на rc.mav.py (він має підключитись до 14551)...")

    def set(self, n, pwm):
        if not (1 <= n <= 18 and 800 <= pwm <= 2200):
            print("[emu] канал 1..18, значення 800..2200")
            return
        with self.lock:
            self.ch[n - 1] = pwm
        print(f"[emu] ch{n} = {pwm}")

    def loop(self):
        last_hb = 0.0
        while self.run:
            m = self.mav.recv_match(blocking=False)   # у режимі udpin так дізнаємось адресу клієнта
            while m is not None:
                if not self.client_seen:
                    self.client_seen = True
                    print("[emu] rc.mav.py підключився, шлю канали")
                m = self.mav.recv_match(blocking=False)
            now = time.time()
            if now - last_hb > 1.0:
                self.mav.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 0, 0,
                                            mavutil.mavlink.MAV_STATE_STANDBY)
                last_hb = now
            with self.lock:
                c = list(self.ch)
            self.mav.mav.rc_channels_send(int((now - self.t0) * 1000), 18, *c, 255)
            time.sleep(0.2)

    def demo(self):
        steps = [("яскравість вниз", 9, 1000), ("яскравість вгору", 9, 1900), ("яскравість середина", 9, 1500),
                 ("контраст мін", 6, 1000), ("контраст макс", 6, 1950),
                 ("AGC 0", 13, 1000), ("AGC 3", 13, 1550), ("AGC 5", 13, 1900),
                 ("ШАТЕР", CH_SHUT, 2000), ("шатер назад (ще рано, <5 c - ігнорується)", CH_SHUT, 1000)]
        for name, n, pwm in steps:
            print(f"[demo] {name}")
            self.set(n, pwm)
            time.sleep(2.0)
        print("[demo] чекаю 5 c і ще раз шатер")
        time.sleep(5.0)
        self.set(CH_SHUT, 2000)
        time.sleep(2.5)
        print("[demo] кінець")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", action="store_true", help="слати через mavlink-router (порт 14550)")
    ap.add_argument("--demo", action="store_true", help="виконати сценарій і вийти")
    a = ap.parse_args()
    e = Emulator(a.router)
    threading.Thread(target=e.loop, daemon=True).start()
    if a.demo:
        while not e.client_seen:
            time.sleep(0.2)
        time.sleep(1.5)
        e.demo()
        return
    print(__doc__.split("Команди")[1])
    for line in sys.stdin:
        p = line.split()
        if not p:
            continue
        try:
            if p[0] in ("q", "quit", "exit"):
                break
            elif p[0] == "show":
                print("[emu]", {i + 1: v for i, v in enumerate(e.ch)})
            elif p[0] == "demo":
                e.demo()
            elif p[0] == "shut":
                e.set(CH_SHUT, 2000 if e.ch[CH_SHUT - 1] < 1500 else 1000)
            elif p[0] in NAMES:
                e.set(NAMES[p[0]], int(p[1]))
            else:
                e.set(int(p[0]), int(p[1]))
        except (ValueError, IndexError):
            print("[emu] не зрозумів. Приклад: 9 1700 | shut | demo | show | q")


if __name__ == "__main__":
    main()
