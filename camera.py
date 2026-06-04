"""
camera.py -- Camara OV7670 + estimacion de distancia
Robot7 | Proyecto Final

Pines:
  GP0-GP7  -> D0-D7   (datos, consecutivos)
  GP8      -> PCLK
  GP9      -> MCLK/XCLK (PWM 16 MHz)
  GP12     -> HREF
  GP13     -> VSYNC
  GP20     -> SDA  (I2C / SCCB)
  GP21     -> SCL

Topics publicados:
  camera/frame   -> {w, h, fmt, frame}   base64 RGB565
  distance/value -> {cm, object}         distancia estimada
"""

import ubinascii
import utime
import gc
import _thread
from machine import SoftI2C, Pin

_CAM_OK = False
try:
    from ov7670_wrapper import (OV7670Wrapper,
                                OV7670_WRAPPER_SIZE_DIV4,
                                OV7670_WRAPPER_TEST_PATTERN_NONE)
    _CAM_OK = True
except ImportError:
    print("[CAM] ov7670_wrapper no encontrado")

CAM_D0    = 0
CAM_PCLK  = 8
CAM_MCLK  = 9
CAM_HREF  = 12
CAM_VSYNC = 13
CAM_SDA   = 20
CAM_SCL   = 21

CAM_W        = 160
CAM_H        = 120
CAM_BUF_SIZE = CAM_W * CAM_H * 2

OBJECT_REAL_CM = 15.0
CAM_F_PX       = 150.0


class CameraTask:

    def __init__(self, scheduler=None, pubsub=None, i2c=None,
                 period_ms=300, priority=7):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self._pubsub  = pubsub
        self._frame   = bytearray(CAM_BUF_SIZE)
        self._ready   = False
        self._cam_ok  = False
        self._lock    = _thread.allocate_lock()

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

    def _init_camera(self):
        base_args = dict(
            i2c_bus        = self._i2c,
            mclk_pin_no    = CAM_MCLK,
            pclk_pin_no    = CAM_PCLK,
            data_pin_base  = CAM_D0,
            vsync_pin_no   = CAM_VSYNC,
            href_pin_no    = CAM_HREF,
            mclk_frequency = 16_000_000,
        )

        a1 = dict(base_args); a1["reset_pin_no"] = 14; a1["shutdown_pin_no"] = 15
        a2 = dict(base_args); a2["reset_pin_no"] = 14
        a3 = dict(base_args); a3["shutdown_pin_no"] = 15
        a4 = dict(base_args)
        attempts = [a1, a2, a3, a4]

        last_err = None
        for kwargs in attempts:
            try:
                self._cam = OV7670Wrapper(**kwargs)
                self._cam.wrapper_configure_base()
                self._cam.wrapper_configure_rgb()
                self._cam.wrapper_configure_size(OV7670_WRAPPER_SIZE_DIV4)
                self._cam.wrapper_configure_test_pattern(OV7670_WRAPPER_TEST_PATTERN_NONE)
                self._cam_ok = True
                print("[CAM] OV7670 lista {}x{} RGB565".format(CAM_W, CAM_H))
                if self._pubsub:
                    self._pubsub.publish("debug/log", {"msg": "Camara OK"})
                return
            except TypeError as e:
                last_err = e
                continue
            except Exception as e:
                print("[CAM] Error init: {}".format(e))
                return

        print("[CAM] Error init: {}".format(last_err))
        self._cam_ok = False

    def _capture_loop(self):
        tmp = bytearray(CAM_BUF_SIZE)
        while True:
            if not self._cam_ok:
                utime.sleep_ms(500)
                continue
            try:
                self._cam.capture(tmp)
                self._lock.acquire()
                self._frame[:] = tmp
                self._ready    = True
                self._lock.release()
            except Exception as e:
                print("[CAM] capture err: {}".format(e))
                self._lock.release()
            utime.sleep_ms(66)

    def _detect_distance(self, frame):
        min_x = CAM_W
        max_x = 0
        count = 0
        y0 = CAM_H // 3
        y1 = 2 * CAM_H // 3
        x0 = CAM_W // 4
        x1 = 3 * CAM_W // 4
        for y in range(y0, y1):
            for x in range(x0, x1):
                idx = (y * CAM_W + x) * 2
                rgb = (frame[idx] << 8) | frame[idx + 1]
                r = ((rgb >> 11) & 0x1F) * 8
                g = ((rgb >>  5) & 0x3F) * 4
                b = ( rgb        & 0x1F) * 8
                if r > 100 and g > 60 and b < 80 and r > g and r > b:
                    count += 1
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
        if count > 30 and max_x > min_x:
            w_px = max_x - min_x
            return round((OBJECT_REAL_CM * CAM_F_PX) / max(w_px, 1), 1)
        return -1

    def update(self):
        if not self._cam_ok:
            return

        self._lock.acquire()
        if not self._ready:
            self._lock.release()
            return
        snap        = bytes(self._frame)
        self._ready = False
        self._lock.release()

        dist = self._detect_distance(snap)
        if dist > 0 and self._pubsub:
            self._pubsub.publish("distance/value", {"cm": dist, "object": "carton"})

        b64 = ubinascii.b2a_base64(snap).decode().replace("\n", "")
        if self._pubsub:
            self._pubsub.publish("camera/frame", {
                "w": CAM_W, "h": CAM_H, "fmt": "rgb565", "frame": b64
            })

        gc.collect()