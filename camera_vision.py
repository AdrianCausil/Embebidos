"""
camera_vision.py -- Cámara OV7670 ultrarrápida (80x60, centroides RGB)
Publica los centroides en el tópico "camera/centroids"
"""

import utime, gc, _thread
from machine import Pin, I2C

_CAM_OK = False
try:
    from ov7670_wrapper import (OV7670Wrapper,
                                OV7670_WRAPPER_SIZE_DIV8,
                                OV7670_WRAPPER_TEST_PATTERN_NONE)
    _CAM_OK = True
except ImportError:
    print("[CAM] ov7670_wrapper no encontrado")

# Pines (ajusta a tu conexión física)
CAM_D0       = 0
CAM_PCLK     = 8
CAM_MCLK     = 9
CAM_HREF     = 12
CAM_VSYNC    = 13
CAM_RESET    = 14
CAM_SHUTDOWN = 15
CAM_SDA      = 16
CAM_SCL      = 17

CAM_W = 80
CAM_H = 60
CAM_BUF_SIZE = CAM_W * CAM_H * 2

# Umbrales RGB (ajústalos según tus tubos)
_TH = {
    "red":   {"r_min": 130, "g_max": 110, "b_max": 110},
    "green": {"g_min": 90,  "r_max": 130, "b_max": 120},
    "blue":  {"b_min": 90,  "r_max": 130, "g_max": 120},
}

COLOR_NONE = 0
COLOR_RED = 1
COLOR_GREEN = 2
COLOR_BLUE = 3

class CameraTask:
    def __init__(self, scheduler, pubsub, period_ms=20, priority=7):
        self.period = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self.pubsub = pubsub
        self._cam_ok = False
        self._buf = bytearray(CAM_BUF_SIZE)

        # Centroides (lectura directa)
        self.red_cx = -1
        self.green_cx = -1
        self.blue_cx = -1

        if _CAM_OK:
            self._init_camera()
            if self._cam_ok:
                _thread.stack_size(4096)
                _thread.start_new_thread(self._capture_loop, ())
        else:
            print("[CAM] Driver no disponible")

        if scheduler:
            scheduler.add(self)
        print("[CAM] Cámara lista (publica centroides en 'camera/centroids')")

    def _init_camera(self):
        try:
            i2c = I2C(0, freq=400_000, scl=Pin(CAM_SCL), sda=Pin(CAM_SDA))
            self._cam = OV7670Wrapper(
                i2c_bus=i2c,
                mclk_pin_no=CAM_MCLK,
                pclk_pin_no=CAM_PCLK,
                data_pin_base=CAM_D0,
                vsync_pin_no=CAM_VSYNC,
                href_pin_no=CAM_HREF,
                reset_pin_no=CAM_RESET,
                shutdown_pin_no=CAM_SHUTDOWN,
                mclk_frequency=16_000_000,
            )
            self._cam.wrapper_configure_base()
            self._cam.wrapper_configure_rgb()
            self._cam.wrapper_configure_size(OV7670_WRAPPER_SIZE_DIV8)
            self._cam.wrapper_configure_test_pattern(OV7670_WRAPPER_TEST_PATTERN_NONE)
            self._cam_ok = True
            print("[CAM] OV7670 lista 80x60")
        except Exception as e:
            print("[CAM] Error init:", e)

    def _capture_loop(self):
        utime.sleep(1)
        while True:
            try:
                self._cam.capture(self._buf)
                self._calcular_centroides(self._buf)
                # Publicar inmediatamente (cada frame)
                if self.pubsub:
                    self.pubsub.publish("camera/centroids", {
                        "red": self.red_cx,
                        "green": self.green_cx,
                        "blue": self.blue_cx
                    })
            except Exception as e:
                print("[CAM] capture err:", e)
                utime.sleep_ms(50)

    @staticmethod
    def _rgb565_to_rgb(pixel):
        r = ((pixel >> 11) & 0x1F) << 3
        g = ((pixel >> 5) & 0x3F) << 2
        b = (pixel & 0x1F) << 3
        return r, g, b

    def _clasificar_pixel(self, r, g, b):
        if r >= _TH["red"]["r_min"] and g <= _TH["red"]["g_max"] and b <= _TH["red"]["b_max"]:
            return COLOR_RED
        if g >= _TH["green"]["g_min"] and r <= _TH["green"]["r_max"] and b <= _TH["green"]["b_max"]:
            return COLOR_GREEN
        if b >= _TH["blue"]["b_min"] and r <= _TH["blue"]["r_max"] and g <= _TH["blue"]["g_max"]:
            return COLOR_BLUE
        return COLOR_NONE

    def _calcular_centroides(self, buf):
        sr = br = sg = bg = sb = bb = 0
        step = 2
        for y in range(0, CAM_H, step):
            row = y * CAM_W
            for x in range(0, CAM_W, step):
                idx = (row + x) * 2
                if idx + 1 >= len(buf):
                    continue
                pixel = (buf[idx] << 8) | buf[idx+1]
                r, g, b = self._rgb565_to_rgb(pixel)
                c = self._clasificar_pixel(r, g, b)
                if c == COLOR_RED:
                    sr += x
                    br += 1
                elif c == COLOR_GREEN:
                    sg += x
                    bg += 1
                elif c == COLOR_BLUE:
                    sb += x
                    bb += 1
        MIN_PX = 5
        self.red_cx = sr // br if br >= MIN_PX else -1
        self.green_cx = sg // bg if bg >= MIN_PX else -1
        self.blue_cx = sb // bb if bb >= MIN_PX else -1

    def update(self):
        pass