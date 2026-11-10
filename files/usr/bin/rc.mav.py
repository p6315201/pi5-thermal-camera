#!/usr/bin/python3
"""
rc.mav.py - керування тепловізором з пульта через MAVLink.

ВІДТВОРЕНИЙ скрипт: оригінальний /bin/rc.py з Pi Zero 2 видалено з образу.
Логіка каналів узята з rc.msp.py (MSP-версія, яка збереглась), транспорт -
MAVLink через mavlink-router (UDP-сервер 127.0.0.1:14551, endpoint "script").
На залізі НЕ перевірявся.

Канали (нумерація з 1, як у MAVLink RC_CHANNELS):
  ch7  - шатер (калібрування) при зміні положення перемикача
  ch9  - яскравість
  ch13 - AGC   (застосовується після першої зміни)
  ch6  - контраст (застосовується після першої зміни)
Команди йдуть у програму camera по UDP 127.0.0.1:1111: "shut", "img <br> <contr> <agc>".
"""
import socket
import time
from pymavlink import mavutil

ROUTER = "udpout:127.0.0.1:14551"
CAMERA = ("127.0.0.1", 1111)
CH_SHUT, CH_BRIGHT, CH_AGC, CH_CONTR = 7, 9, 13, 6
DEF_AGC, DEF_BRIGHT, DEF_CONTR = 2, 58, 80
SHUT_MIN_INTERVAL = 5.0


def step(x, edges, values=None):
    i = 0
    while i < len(edges) and edges[i] <= x:
        i += 1
    return values[i] if values else i


def shut_pos(x):
    return step(x, [1300, 1800])


def brightness(x):
    return step(x, [1100, 1300, 1480, 1520, 1600, 1800], [48, 58, 68, 78, 88, 98, 108])


def agc(x):
    return step(x, [1100, 1300, 1500, 1600, 1800])


def contrast(x):
    return step(x, [1100, 1150, 1200, 1250, 1300, 1350, 1400, 1450, 1500, 1550, 1600, 1750, 1800, 1850, 1900],
                [60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130, 135])


def main():
    cam = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(msg):
        cam.sendto(msg.encode(), CAMERA)

    def send_img(b, c, a):
        send(f"img {b} {c} {a}")

    mav = mavutil.mavlink_connection(ROUTER, source_system=255, source_component=191)

    def hello():
        # роутер у режимі Server дізнається нашу адресу з першого пакета
        mav.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                               mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)

    hello()
    cur = (DEF_BRIGHT, DEF_CONTR, DEF_AGC)
    send_img(*cur)
    img_agc, img_contr = DEF_AGC, DEF_CONTR
    last_agc_pwm = last_contr_pwm = 0
    last_shut_pos = -1
    last_shut_time = 0.0
    last_hello = last_request = 0.0

    while True:
        now = time.time()
        if now - last_hello > 1.0:
            hello()
            last_hello = now
        if now - last_request > 5.0 and mav.target_system:
            # попросити польотник слати RC_CHANNELS 5 разів/с
            mav.mav.command_long_send(mav.target_system, mav.target_component,
                                      mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                      mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 200000, 0, 0, 0, 0, 0)
            last_request = now

        m = mav.recv_match(type=["RC_CHANNELS", "HEARTBEAT"], blocking=True, timeout=1.0)
        if m is None:
            continue
        if m.get_type() == "HEARTBEAT":
            # запам'ятати польотник (не наземну станцію), щоб просити в нього RC_CHANNELS
            if not mav.target_system and m.autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID:
                mav.target_system, mav.target_component = m.get_srcSystem(), m.get_srcComponent()
            continue

        def ch(n):
            return getattr(m, f"chan{n}_raw", 0) or 0

        agc_pwm, contr_pwm = ch(CH_AGC), ch(CH_CONTR)
        if last_agc_pwm == 0:
            last_agc_pwm = agc_pwm
        elif agc_pwm != last_agc_pwm:
            last_agc_pwm = agc_pwm
            img_agc = agc(agc_pwm)
        if last_contr_pwm == 0:
            last_contr_pwm = contr_pwm
        elif contr_pwm != last_contr_pwm:
            last_contr_pwm = contr_pwm
            img_contr = contrast(contr_pwm)

        new = (brightness(ch(CH_BRIGHT)), img_contr, img_agc)
        if new != cur:
            cur = new
            send_img(*cur)

        pos = shut_pos(ch(CH_SHUT))
        if pos != last_shut_pos:
            first = last_shut_pos == -1
            last_shut_pos = pos
            if not first and time.time() - last_shut_time > SHUT_MIN_INTERVAL:
                send("shut")
                last_shut_time = time.time()
                time.sleep(1)
                send_img(*cur)


if __name__ == "__main__":
    main()
