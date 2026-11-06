#!/usr/bin/env python3
"""
Запасний читач InfiRay Tiny1-C по SPI + I2C для Raspberry Pi 5.
Відтворює протокол оригінальної програми /usr/bin/camera з Pi Zero 2:

  I2C (/dev/i2c-1) через libiruvc.so:
      vdcmd_init_by_type(2); vdcmd_set_polling_wait_time(10000)
      register_i2c_device_node("/dev/i2c-1")
      preview_start({path=0, source=0, width=256, height=192, fps=25, mode=8})
  SPI (/dev/spidev0.0): mode 3, 8 біт, 31.2 MHz
      кадр = 256*192*2 = 98304 байт YUYV (YUV422)
      транзакції по 4096 байт, full-duplex:
        1-ша: tx[0]=0xAA, з rx відкинути перші 512 байт (заголовок) -> 3584 байти даних
        далі: tx[0]=0x55, брати по 4096 байт, поки не набереться 98304

Використання:
  python3 tiny1c_spi.py --save frame.png     # зберегти один кадр
  python3 tiny1c_spi.py --show               # вікно з живим відео (потрібен робочий стіл)
  python3 tiny1c_spi.py --no-i2c --save x.png  # якщо стрім уже запущено (напр. програмою camera)
"""
import argparse, ctypes, sys, time
import numpy as np
import spidev

W, H, FPS = 256, 192, 25
FRAME = W * H * 2
PKT = 4096
HDR = 512


class PreviewStartParam(ctypes.Structure):
    _fields_ = [("path", ctypes.c_uint8), ("source", ctypes.c_uint8),
                ("width", ctypes.c_uint16), ("height", ctypes.c_uint16),
                ("fps", ctypes.c_uint8), ("mode", ctypes.c_uint8)]


def i2c_start(lib_path="/usr/lib/libiruvc.so", dev=b"/dev/i2c-1"):
    lib = ctypes.CDLL(lib_path)
    lib.vdcmd_init_by_type(2)
    lib.vdcmd_set_polling_wait_time(10000)
    lib.register_i2c_device_node(ctypes.c_char_p(dev))
    p = PreviewStartParam(0, 0, W, H, FPS, 8)
    rc = lib.preview_start(ctypes.byref(p))
    if rc < 0:
        sys.exit(f"preview_start failed: {rc} (перевір I2C: i2cdetect -y 1)")
    return lib


def spi_open(bus=0, dev=0, speed=31_200_000):
    s = spidev.SpiDev()
    s.open(bus, dev)
    s.mode = 3
    s.bits_per_word = 8
    s.max_speed_hz = speed
    return s


def read_frame(spi, first_cmd=0xAA):
    out = bytearray()
    tx = [0] * PKT
    tx[0] = first_cmd
    rx = spi.xfer2(tx)
    out += bytes(rx[HDR:])
    tx[0] = 0x55
    while len(out) < FRAME:
        rx = spi.xfer2(tx)
        out += bytes(rx[:min(PKT, FRAME - len(out))])
    return np.frombuffer(bytes(out), np.uint8).reshape(H, W, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-i2c", action="store_true")
    ap.add_argument("--save")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--bus", type=int, default=0)
    ap.add_argument("--speed", type=int, default=31_200_000)
    a = ap.parse_args()

    import cv2
    lib = None if a.no_i2c else i2c_start()
    time.sleep(0.5)
    spi = spi_open(a.bus, 0, a.speed)
    try:
        while True:
            yuyv = read_frame(spi)
            bgr = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUYV)
            if a.save:
                cv2.imwrite(a.save, cv2.resize(bgr, (W * 3, H * 3), interpolation=cv2.INTER_NEAREST))
                print("saved", a.save, "Y min/max:", yuyv[..., 0].min(), yuyv[..., 0].max())
                break
            if a.show:
                cv2.imshow("Tiny1-C", cv2.resize(bgr, (W * 3, H * 3)))
                if cv2.waitKey(1) == 27:
                    break
    finally:
        spi.close()
        if lib is not None:
            lib.i2c_stop_stream(0)


if __name__ == "__main__":
    main()
