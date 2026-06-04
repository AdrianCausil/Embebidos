"""
camera.py -- Camara OV7670 + estimacion de distancia
Robot11 | Proyecto Final

Clase: CameraTask

Pines (codigo que funciono con el profe):
  GP0-GP7  -> D0-D7   (datos, PIO in_base, consecutivos)
  GP8      -> PCLK
  GP9      -> MCLK/XCLK (PWM 16 MHz)
  GP12     -> HREF
  GP13     -> VSYNC
  GP14     -> RESET
  GP15     -> PWDN (cable directo a GND, no GPIO)
  GP20     -> SDA  (I2C compartido con OLED 0x3C)
  GP21     -> SCL

Resolucion: 160x120 RGB565 (38400 bytes por frame)

Estimacion de distancia:
  Busca pixeles de color carton en franja central
  Calcula ancho en pixeles del objeto
  Formula: dist_cm = (OBJECT_REAL_CM * CAM_F_PX) / pixel_width
  Calibrar OBJECT_REAL_CM y CAM_F_PX segun el carton real

Topics publicados:
  camera/frame   -> {w, h, fmt, frame}   base64 RGB565
  distance/value -> {cm, object}         distancia estimada
"""

import ubinascii
import utime
import math
import gc
import _thread
from machine import Pin, PWM, SoftI2C

_CAM_OK = False
try:
    from ov7670_wrapper import (OV7670Wrapper,
                                OV7670_WRAPPER_SIZE_DIV4,
                                OV7670_WRAPPER_TEST_PATTERN_NONE)
    _CAM_OK = True
except ImportError:
    print("[CAM] ov7670_wrapper no encontrado")

# Pines camara (del codigo que funciono)
CAM_D0       = 0
CAM_PCLK     = 8
CAM_MCLK     = 9
CAM_HREF     = 12
CAM_VSYNC    = 13
CAM_RESET    = 14
# PWDN va directo a GND -- no necesita pin GPIO
CAM_SDA      = 20
CAM_SCL      = 21

CAM_W        = 160
CAM_H        = 120
CAM_BUF_SIZE = CAM_W * CAM_H * 2   # 38400 bytes RGB565

# Calibracion distancia
OBJECT_REAL_CM = 15.0   # ancho real del carton en cm -- ajustar
CAM_F_PX       = 150.0  # focal estimada en px -- calibrar


class CameraTask:
    """
    Captura frames OV7670 en hilo secundario y los publica.

    Uso sin PubSub (prueba):
        cam = CameraTask()

    Uso con PubSub (main.py):
        cam = CameraTask(scheduler=sched, pubsub=node, i2c=i2c)
    """

    def __init__(self, scheduler=None, pubsub=None, i2c=None,
                 period_ms=300, priority=7):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self._pubsub  = pubsub
        self._frame   = bytearray(CAM_BUF_SIZE)
        self._ready   = False
        self._cam_ok  = False
        self._dist_cm = -1
        self._lock    = _thread.allocate_lock()

        # I2C -- reutiliza el existente o crea uno nuevo
        if i2c is None:
            i2c = SoftI2C(scl=Pin(CAM_SCL), sda=Pin(CAM_SDA), freq=400_000)
        self._i2c = i2c

        if _CAM_OK:
            self._init_camera()
            if self._cam_ok:
                _thread.start_new_thread(self._capture_loop, ())
        else:
            print("[CAM] Driver no disponible")

        if scheduler:
            scheduler.add(self)

    # ══════════════════════════════════════════════
    #  Inicializacion camara
    # ══════════════════════════════════════════════

    def _init_camera(self):
        try:
            self._cam = OV7670Wrapper(
                i2c_bus         = self._i2c,
                mclk_pin_no     = CAM_MCLK,
                pclk_pin_no     = CAM_PCLK,
                data_pin_base   = CAM_D0,
                vsync_pin_no    = CAM_VSYNC,
                href_pin_no     = CAM_HREF,
                reset_pin_no    = CAM_RESET,
                shutdown_pin_no = 15,      # PWDN a GND directo
                mclk_frequency  = 16_000_000,
            )
            self._cam.wrapper_configure_base()
            self._cam.wrapper_configure_rgb()
            self._cam.wrapper_configure_size(OV7670_WRAPPER_SIZE_DIV4)
            self._cam.wrapper_configure_test_pattern(OV7670_WRAPPER_TEST_PATTERN_NONE)
            self._cam_ok = True
            print(f"[CAM] OV7670 lista {CAM_W}x{CAM_H} RGB565")
            if self._pubsub:
                self._pubsub.publish("debug/log", {"msg": "Camara OK"})
        except Exception as e:
            print(f"[CAM] Error init: {e}")
            self._cam_ok = False
            if self._pubsub:
                self._pubsub.publish("debug/log", {"msg": "Cam error"})

    # ══════════════════════════════════════════════
    #  Hilo de captura (corre en nucleo 1)
    # ══════════════════════════════════════════════

    def _capture_loop(self):
        """
        Captura frames continuamente en segundo hilo.
        Escribe en _frame bajo lock para evitar race conditions.
        """
        tmp = bytearray(CAM_BUF_SIZE)
        while True:
            if not self._cam_ok:
                utime.sleep_ms(500)
                continue
            try:
                self._cam.capture(tmp)
                with self._lock:
                    self._frame[:] = tmp
                    self._ready    = True
            except Exception as e:
                print(f"[CAM] capture err: {e}")
            utime.sleep_ms(66)   # ~15 fps max

    # ══════════════════════════════════════════════
    #  Estimacion de distancia por vision
    # ══════════════════════════════════════════════

    def _detect_distance(self, frame):
        """
        Detecta el carton por color y estima distancia.
        Analiza la franja central del frame (menos computo).

        Calibracion:
          1. Poner el carton a distancia conocida (ej 30 cm)
          2. Ver pixel_width en consola
          3. CAM_F_PX = 30 * pixel_width / OBJECT_REAL_CM
        """
        min_x = CAM_W; max_x = 0; count = 0
        y0 = CAM_H // 3;  y1 = 2 * CAM_H // 3
        x0 = CAM_W // 4;  x1 = 3 * CAM_W // 4

        for y in range(y0, y1):
            for x in range(x0, x1):
                idx = (y * CAM_W + x) * 2
                rgb = (frame[idx] << 8) | frame[idx + 1]
                r = ((rgb >> 11) & 0x1F) * 8
                g = ((rgb >>  5) & 0x3F) * 4
                b = (rgb & 0x1F) * 8
                # Color carton: marron claro / beige
                # Ajustar estos umbrales segun el carton real
                if r > 100 and g > 60 and b < 80 and r > g and r > b:
                    count += 1
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x

        if count > 30 and max_x > min_x:
            w_px = max_x - min_x
            dist = (OBJECT_REAL_CM * CAM_F_PX) / max(w_px, 1)
            return round(dist, 1)
        return -1

    # ══════════════════════════════════════════════
    #  update() -- llamado por el Scheduler
    # ══════════════════════════════════════════════

    def update(self):
        if not self._cam_ok:
            return
        with self._lock:
            if not self._ready:
                return
            snap        = bytes(self._frame)
            self._ready = False

        # Distancia
        dist = self._detect_distance(snap)
        if dist > 0:
            self._dist_cm = dist
            if self._pubsub:
                self._pubsub.publish("distance/value", {
                    "cm": dist, "object": "carton"
                })

        # Frame en base64
        b64 = ubinascii.b2a_base64(snap).decode().replace("\n", "")
        if self._pubsub:
            self._pubsub.publish("camera/frame", {
                "w": CAM_W, "h": CAM_H, "fmt": "rgb565", "frame": b64
            })

        gc.collect()
