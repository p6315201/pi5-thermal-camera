# Завдання для агента: запустити тепловізор InfiRay Tiny1-C (SPI + I2C) на Raspberry Pi 5

Ти працюєш **на Raspberry Pi 5** (shell з sudo). Мета — відтворити робочу систему, яка раніше
працювала на Raspberry Pi Zero 2 W (дрон, FPV-тепловізор, вивід на композитне відео PAL,
керування з пульта через MSP/UART). Усе нижче отримано аналізом образу SD-карти Zero 2.

## 0. Що було на Zero 2 (факти з образу)

- ОС: Raspberry Pi OS **Debian 12 Bookworm, arm64**, ядро 6.1.
- `config.txt`: `dtparam=i2c_arm=on`, `dtparam=spi=on`, `enable_uart=1`,
  `dtoverlay=vc4-fkms-v3d,composite`, `sdtv_mode=2` (PAL), `dtoverlay=pi3-disable-bt`.
- `cmdline.txt` — без змін (spidev.bufsiz НЕ змінювався: транзакції по 4096 байт = дефолт).
- Програма камери: `/usr/bin/camera` (ELF aarch64, зібрана з InfiRay SDK «libirsample 1.2.0»,
  RUNPATH `/home/pi/ir/spi_i2c.03g/libs`, але бібліотеки лежали в `/usr/lib`).
  - Бібліотеки: `/usr/lib/libiruvc.so libirtemp.so libirprocess.so libirparse.so`
    (+ системні `libopencv_core.so.406`, `libopencv_videoio.so.406`, `libusb-1.0`).
  - Сервіс `camera.service` → `ExecStart=/bin/camera`, `Restart=always`, `WantedBy=local-fs.target`.
- Протокол, який використовує `camera` (з дизасемблювання):
  - **I2C** `/dev/i2c-1`: `vdcmd_init_by_type(2)`, `vdcmd_set_polling_wait_time(10000)`,
    `register_i2c_device_node("/dev/i2c-1")`, `preview_start({0,0,256,192,25,8})`.
  - **SPI** `/dev/spidev0.0`, **mode 3**, 8 біт, **31 200 000 Гц**.
    Кадр 256×192 YUYV = 98 304 байт; транзакції по 4096 байт; перша з `tx[0]=0xAA`
    і першими 512 байтами rx як заголовок, далі `tx[0]=0x55`.
  - Вивід: GStreamer `appsrc ! videoconvert ! kmssink sync=false render-rectangle=<0,0,768,576>`.
  - **UDP-керування** на порту **1111** (localhost): команди `shut` (калібрування шатером),
    `img <brightness> <contrast> <agc>`, `zoom ...`.
- `mspcontrol.service` → `/bin/rc.msp.py`: читає RC-канали з польотника по MSP
  (`/dev/serial0`, 115200, бібліотека YAMSPy) і шле UDP-команди в `camera`.
  `camcontrol.service` і `mavlink-router` були вимкнені — їх не переносити.

Файли з образу лежать у пакеті поруч з цією інструкцією: `files/usr/bin/`, `files/usr/lib/`,
`files/systemd/`, `files/zero2-config.txt`, контрольні суми в `files/SHA256SUMS`.

## 1. Апаратне підключення (перевір, НЕ перепаюй без підтвердження користувача)

| Tiny1-C | Pi 5 фіз. пін | GPIO |
|---|---|---|
| 5V | 2 (або 4) | — |
| 3.3V | 1 | — |
| GND | 6 | — |
| SDA | 3 | GPIO2 (I2C1) |
| SCL | 5 | GPIO3 (I2C1) |
| MOSI | 19 | GPIO10 |
| MISO | 21 | GPIO9 |
| SCK | 23 | GPIO11 |
| CS | 24 | GPIO8 (CE0) |

Розпіновка 40-pin у Pi 5 така сама, як у Zero 2. Польотник (MSP): TX/RX на піни 8/10 (GPIO14/15).

## 2. Перевір ОС

```bash
cat /etc/os-release | grep VERSION_CODENAME
```
```bash
uname -m
```
- Потрібно `bookworm` + `aarch64`, тоді оригінальний бінарник запуститься як є
  (він залинкований з OpenCV **4.6** = `libopencv-*406`, які є саме в Bookworm).
- Якщо `trixie` або новіша — `libopencv_*.so.406` не буде. Варіанти: (а) поставити
  Raspberry Pi OS Bookworm 64-bit (Legacy) — найнадійніше; (б) пропустити кроки 4–5 і
  використовувати `tiny1c_spi.py` (крок 6). Не намагайся підсовувати symlink 410→406 — ABI різний.
  Повідом користувачу, який варіант обрано.

## 3. Увімкни інтерфейси

```bash
sudo raspi-config nonint do_i2c 0
```
```bash
sudo raspi-config nonint do_spi 0
```
```bash
sudo raspi-config nonint do_serial_hw 0
```
```bash
sudo raspi-config nonint do_serial_cons 1
```

Відредагуй `/boot/firmware/config.txt` (зроби бекап `config.txt.bak`), секція `[all]`:
```
dtparam=i2c_arm=on
dtparam=spi=on
dtparam=uart0=on
enable_uart=1
```
- **НЕ** копіюй `vc4-fkms-v3d` і `pi3-disable-bt` із Zero 2 — на Pi 5 вони не працюють.
  На Pi 5 лишається `dtoverlay=vc4-kms-v3d`.
- Композит (якщо відео йде на FPV-передавач по аналогу): на Pi 5 композитний вихід — тестові пади
  біля HDMI, не роз'єм. Увімкнення: `dtoverlay=vc4-kms-v3d,composite` у config.txt і
  `video=Composite-1:720x576@50ie` в кінець рядка `/boot/firmware/cmdline.txt`.
  Перевір це в актуальній документації Raspberry Pi перед застосуванням і спитай користувача,
  чи потрібен саме композит (а не HDMI).

```bash
sudo reboot
```

Після перезавантаження:
```bash
ls -l /dev/spidev0.0 /dev/i2c-1 /dev/ttyAMA0
```
```bash
sudo apt install -y i2c-tools && i2cdetect -y 1
```
Камера має з'явитися на шині (запиши адресу). Якщо `/dev/spidev0.0` немає, але є
`/dev/spidev10.0` — повідом користувача (бінарник жорстко відкриває `/dev/spidev0.0`).

## 4. Встанови залежності (тільки Bookworm)

```bash
sudo apt update
```
```bash
sudo apt install -y libusb-1.0-0 libopencv-core406 libopencv-videoio406 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad python3-spidev python3-opencv python3-numpy
```

## 5. Перенеси оригінальну програму

З каталогу пакета:
```bash
(cd files && sha256sum -c SHA256SUMS)
```
```bash
sudo install -m 755 files/usr/bin/camera /usr/bin/camera
```
```bash
sudo install -m 644 files/usr/lib/libir*.so /usr/lib/ && sudo ldconfig
```
```bash
ldd /usr/bin/camera | grep "not found" || echo OK
```
Якщо щось `not found` — доінсталюй пакет, що це дає (`apt-file search <lib>`), не підміняй версії.

Тестовий запуск у терміналі (спочатку вручну, не сервісом):
```bash
sudo /usr/bin/camera </dev/null
```
Очікуваний вивід — версії бібліотек, без `init spi failed!` / `ir camera stream on failed!`.
Перевір керування:
```bash
echo -n shut | nc -u -w1 127.0.0.1 1111
```
```bash
echo -n "img 78 80 1" | nc -u -w1 127.0.0.1 1111
```
(у логах `camera` має бути `got SHUT command` / `got IMG command`).

Відомий ризик: `kmssink` на Pi 5 може не знайти дисплей (на Pi 5 два DRM-пристрої, card0/card1).
Якщо зображення немає, а помилок SPI немає — камера працює, проблема у виводі; повідом користувачу
та перевір `tiny1c_spi.py --save` (крок 6), що кадри реально приходять.

## 6. Перевірка / запасний варіант: tiny1c_spi.py

Скрипт повторює той самий протокол на Python (I2C через `libiruvc.so` за допомогою ctypes).
Не запускай одночасно з `camera` (обидва ходять у SPI) — спершу зупини сервіс.
```bash
sudo systemctl stop camera 2>/dev/null; sudo python3 tiny1c_spi.py --save /tmp/frame.png
```
Успіх: у `/tmp/frame.png` видно теплову картинку, `Y min/max` не `0 0` і не `255 255`.
Якщо картинка «зсунута» або сміття — спробуй `--speed 20000000`; збережи кадр і покажи користувачу.

## 7. Автозапуск камери

```bash
sudo install -m 644 files/systemd/camera.service /usr/lib/systemd/system/camera.service
```
`camera.service` містить `ExecStart=/bin/camera` — на Pi OS `/bin` → `/usr/bin`, тож працює.
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now camera
```
```bash
systemctl status camera --no-pager
```

## 8. Керування з польотника (MSP), якщо потрібне

```bash
sudo apt install -y git python3-serial
```
```bash
git clone https://github.com/ricardodeazambuja/YAMSPy.git ~/YAMSPy && cd ~/YAMSPy && sudo pip3 install --break-system-packages .
```
```bash
sudo install -m 755 files/usr/bin/rc.msp.py /usr/bin/rc.msp.py
```
**Важливо для Pi 5:** `/dev/serial0` на Pi 5 вказує на окремий debug-UART (ttyAMA10), а не на
GPIO14/15. У `/usr/bin/rc.msp.py` заміни
`serial_port = "/dev/serial0"` → `serial_port = "/dev/ttyAMA0"`
(перевір, що `/dev/ttyAMA0` існує після `dtparam=uart0=on`).
```bash
sudo install -m 644 files/systemd/mspcontrol.service /usr/lib/systemd/system/
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now mspcontrol
```
Примітка: `rc.msp.py` читає `/home/pi/config.txt` (формат `agc N\nbrightness N\ncontrast N`).
На Zero 2 скрипт мав баг і перезаписував цей файл рядком `aaa` — тоді діють дефолти (2, 58, 80).
Не виправляй без запиту користувача, лише повідом.

## 9. Звіт користувачу

Повідом: версію ОС, адресу I2C з `i2cdetect`, чи стартує `camera` без помилок,
чи `tiny1c_spi.py` зберіг нормальний кадр, чи є відео на дисплеї/композиті, статус сервісів.
Не роби незворотних змін (перепайка, перепрошивка модуля, видалення файлів) без підтвердження.

## 10. Додатково знайдено в образі Zero 2 (другий прохід)

- `files/usr/bin/gsttest` — тестова програма GStreamer з образу (`videotestsrc ! videoconvert !
  video/x-raw,format=I420 ! kmssink`). Запусти її ПЕРЕД `camera`, щоб перевірити, що `kmssink`
  взагалі малює на дисплей Pi 5: `sudo install -m 755 files/usr/bin/gsttest /usr/bin/ && sudo gsttest`.
  Є тестова картинка — вивід працює; немає — проблема у виводі, а не в камері.
- `files/libs_version.txt` — версії SDK: libirsample 1.2.0, libirprocess 0.8.2, libirparse 0.3.1,
  libirtemp 0.13.4 alpha, **libiruvc asic2121w 1.10.6 alpha**. `camera` сама перезаписує цей файл
  як `../libs_version.txt` відносно робочого каталогу.
- `/etc/modules` на Zero 2 містив `i2c-dev` — переконайся, що модуль завантажений (`lsmod | grep i2c_dev`).
- Вихідний код програми камери (`/root/spi_i2c.03/` — include, libs, build/sample; архів
  `spi_i2c.03c.tar.gz`) і MAVLink-версія пульта (`/root/soft/rc.py`, `rc_test.py`) з образу ВИДАЛЕНІ.
  `/usr/bin/camera` — це зібраний `build/sample`. Перезібрати або змінити програму без вихідників
  неможливо; якщо знадобиться — попроси користувача дістати архів `spi_i2c.03c.tar.gz`.
- Образ Zero 2 НЕ завантажиться на Pi 5: ядро для Pi 5 (`linux-image-rpi-2712`) з нього видалене.
  Тому потрібна чиста ОС на Pi 5, а не клон цієї SD-карти.
- На Zero 2 система була урізана для швидкого старту (вимкнені NetworkManager-wait-online,
  getty@tty1, timesyncd, bluetooth, ModemManager, swap). Це оптимізація, для роботи камери не потрібна.

## 11. MAVLink-варіант керування (mavlink-router) — альтернатива кроку 8

На Zero 2 спершу було керування через MAVLink (`mavlink-router` + `/bin/rc.py`, сервіс
`camcontrol`), потім його вимкнули на користь MSP (`mspcontrol`, крок 8).
**Обирай ОДНЕ з двох**: обидва займають той самий UART до польотника. MAVLink — якщо на
польотнику ArduPilot/PX4 або порт налаштований на MAVLink; MSP — якщо Betaflight/INAV з MSP.
Спитай користувача, яка прошивка польотника, якщо невідомо.

Файли з образу: `files/usr/bin/mavlink-routerd` (зібраний на Zero 2 з
github.com/mavlink-router/mavlink-router, aarch64, залежить лише від libc/libstdc++),
`files/mavlink/main.conf`, `files/systemd/mavlink-router.service`, `files/systemd/camcontrol.service`.
`files/usr/bin/rc.mav.py` — **відтворений** скрипт (оригінальний `rc.py` видалено з образу):
логіка каналів з `rc.msp.py`, транспорт MAVLink. На залізі не перевірявся — тестуй уважно.

Оригінальний конфіг роутера: UART `/dev/serial0` 115200 → UDP-сервери `0.0.0.0:14550`
(наземна станція, QGC) і `0.0.0.0:14551` (скрипт).

```bash
sudo systemctl disable --now mspcontrol 2>/dev/null
```
```bash
sudo install -m 755 files/usr/bin/mavlink-routerd /usr/bin/mavlink-routerd && mavlink-routerd --version
```
Якщо бінарник не стартує — збери з вихідників, як на Zero 2:
`sudo apt install -y git meson ninja-build pkg-config gcc g++ && git clone https://github.com/mavlink-router/mavlink-router.git && cd mavlink-router && git submodule update --init --recursive && meson setup build . && ninja -C build && sudo ninja -C build install`
```bash
sudo mkdir -p /etc/mavlink-router && sudo install -m 644 files/mavlink/main.conf /etc/mavlink-router/main.conf
```
**Pi 5:** UART на GPIO14/15 — це `/dev/ttyAMA0`, а не `/dev/serial0`:
```bash
sudo sed -i 's#/dev/serial0#/dev/ttyAMA0#' /etc/mavlink-router/main.conf
```
```bash
sudo install -m 644 files/systemd/mavlink-router.service /usr/lib/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now mavlink-router && systemctl status mavlink-router --no-pager
```
Перевірка, що MAVLink іде з польотника (має друкувати HEARTBEAT):
```bash
sudo pip3 install --break-system-packages pymavlink
```
```bash
python3 -c "from pymavlink import mavutil; m=mavutil.mavlink_connection('udpout:127.0.0.1:14551'); m.mav.heartbeat_send(18,8,0,0,0); print(m.recv_match(type='HEARTBEAT',blocking=True,timeout=10))"
```
`None` = даних немає: перевір проводку TX/RX, швидкість 115200 і що порт польотника в режимі MAVLink.

Скрипт керування камерою:
```bash
sudo install -m 755 files/usr/bin/rc.mav.py /usr/bin/rc.mav.py
```
```bash
sudo install -m 644 files/systemd/camcontrol.service /usr/lib/systemd/system/ && sudo sed -i 's#ExecStart=/bin/rc.py#ExecStart=/usr/bin/rc.mav.py#' /usr/lib/systemd/system/camcontrol.service
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now camcontrol && systemctl status camcontrol --no-pager
```
Канали пульта в `rc.mav.py` (як у `rc.msp.py`): ch7 — шатер, ch9 — яскравість, ch13 — AGC,
ch6 — контраст. Якщо у користувача інша розкладка — зміни константи `CH_*` на початку скрипта.
Порт 14550 відкритий на всі інтерфейси (0.0.0.0) — це як на Zero 2; повідом користувача,
якщо Pi у спільній мережі.

## 12. Емуляція пульта (перевірка керування без польотника)

У `tools/` є два скрипти: `rc_emulator.py` удає польотник (шле MAVLink HEARTBEAT + RC_CHANNELS),
`fake_camera.py` удає програму камери (друкує команди, що приходять на UDP 1111).
Ланцюжок `rc_emulator → rc.mav.py → fake_camera` перевірено на комп'ютері розробника (не на Pi).
Потрібен `pymavlink` (крок 11).

**А. Тільки логіка, без камери й роутера** — три термінали (або `tmux`):
```bash
sudo systemctl stop camera camcontrol mavlink-router 2>/dev/null; python3 tools/fake_camera.py
```
```bash
python3 files/usr/bin/rc.mav.py
```
```bash
python3 tools/rc_emulator.py --demo
```
Очікувано у `fake_camera`: спершу `img 58 80 2`, далі `img ...` зі зміною яскравості
(48 → 108 → 78), контрасту (60 → 135), AGC (0 → 3 → 5) і двічі `shut`.

**Б. Зі справжньою камерою** (видно реальну зміну картинки): `camera` запущена, `fake_camera` НЕ запускати.
```bash
sudo systemctl start camera; sudo systemctl stop camcontrol mavlink-router 2>/dev/null; python3 files/usr/bin/rc.mav.py &
```
```bash
python3 tools/rc_emulator.py
```
Далі вводь команди вручну: `bright 1900`, `contr 1200`, `agc 1550`, `shut`, `9 1000`, `show`, `q`.
У журналі камери (`journalctl -u camera -f`) мають з'являтись `got IMG command` / `got SHUT command`,
а зображення — змінюватись; при `shut` чути клацання шатера.

**В. Через працюючий mavlink-router** (перевіряє і роутер): сервіси `mavlink-router` та `camcontrol`
запущені, польотник від'єднаний або вимкнений.
```bash
python3 tools/rc_emulator.py --router
```

Після тестів поверни сервіси: `sudo systemctl start mavlink-router camcontrol`.
