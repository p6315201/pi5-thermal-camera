# Донавчання моделі: люди і техніка з дрона

Два класи: `0 = person` (люди), `1 = vehicle` (техніка).
Окремі моделі для тепловізора (`sar_thermal`) і RGB-камери (`sar_rgb`).

## Найпростіше: Google Colab (безкоштовна GPU)

1. Відкрийте https://colab.research.google.com → «Завантажити» → `train_colab.ipynb`.
2. Середовище → Змінити тип середовища → **GPU**.
3. Виконуйте комірки по черзі. Коли попросить, завантажте `training_kit.zip`.
4. Наприкінці скачається `models_for_pi.zip`. Розпакуйте його в `thermal_viewer` на Pi.

## На своєму ПК з відеокартою NVIDIA

```bash
pip install ultralytics ncnn pnnx
python prepare_data.py --target thermal
python train.py --target thermal
```

## Дані

| Джерело | Що це | Для якої моделі |
|---|---|---|
| HIT-UAV | тепловізор 640×512 з дрона, 60–130 м, день/ніч, ~2900 кадрів | thermal |
| VisDrone2019 | RGB з дрона, дрібні об'єкти, ~8600 кадрів | rgb, а також thermal у сірому |
| `own_data/` | **ваші кадри**, найцінніші | обидві |

Скачуються автоматично. Перевірте ліцензії датасетів перед використанням поза дослідженнями.

### Власні кадри

```
own_data/thermal/images/  кадр1.jpg ...
own_data/thermal/labels/  кадр1.txt ...   # YOLO: <клас> <xc> <yc> <w> <h>, координати 0..1
own_data/rgb/images/ ...
own_data/rgb/labels/ ...
```
Розмічати зручно в CVAT або Roboflow, експорт «YOLO». Класи: `person`, `vehicle`.
Кадр без файлу розмітки вважається порожнім («тут нічого немає»). Такі кадри зменшують кількість хибних тривог.
Власні кадри автоматично дублюються в навчальній вибірці (`--own-repeat 3`).

## Результат (`trained/`)

- `sar_thermal.pt` — модель
- `sar_thermal_416_ncnn_model/`, `sar_thermal_320_ncnn_model/` — готові для Raspberry Pi
- `sar_thermal_metrics.txt` — точність по класах (recall = скільки знайдено, precision = скільки тривог справжні)

На Pi, у `config.env`:
```
ARGS="--ncnn --imgsz 416 --thermal-model sar_thermal.pt"
```
