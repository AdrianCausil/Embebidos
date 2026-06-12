"""
camera_task.py — Cámara OV7670 con detección HSV + centroides (rápido)
Robot11 | Pines I2C: SDA=16, SCL=17
"""

import ubinascii, hashlib, struct
import usocket as socket
import utime, gc, _thread
from machine import Pin

_CAM_OK = False
try:
    from ov7670_wrapper import (
        OV7670Wrapper,
        OV7670_REG_CLKRC,
        OV7670_WRAPPER_SIZE_DIV4,
        OV7670_WRAPPER_TEST_PATTERN_NONE,
    )
    _CAM_OK = True
except ImportError:
    print("[CAM] ov7670_wrapper no encontrado — CameraTask deshabilitada")

# ── Pines (originales, sin cambios) ──
CAM_D0       = 0
CAM_PCLK     = 8
CAM_MCLK     = 9
CAM_HREF     = 12
CAM_VSYNC    = 13
CAM_RESET    = 14
CAM_SHUTDOWN = 15
CAM_SDA      = 16      # I2C0 SDA
CAM_SCL      = 17      # I2C0 SCL

# ── Resolución ─────────────────────────────────────────────────
CAM_W        = 160
CAM_H        = 120
CAM_BUF_SIZE = CAM_W * CAM_H * 2

# ── Servidor de video ──────────────────────────────────────────
VIDEO_PORT       = 8080
SEND_INTERVAL_MS = 100
GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# ── Análisis de color (cuadrícula 4×3 para el frontend, opcional) ──
GRID_COLS       = 4
GRID_ROWS       = 3
COLOR_THRESHOLD = 0.20      # 20% de la celda para considerarse dominante

# ── Umbrales HSV (ajustables según tus condiciones) ────────────
# Formato: (H_min, H_max, S_min, V_min)
# Rojo tiene dos rangos por la envoltura del tono (0-15 y 345-360)
HSV_RANGES = {
    "red":   [(0, 15, 100, 50), (345, 360, 100, 50)],
    "green": [(75, 105, 80, 50)],
    "blue":  [(130, 170, 80, 50)],
}

# ── Constantes de color ────────────────────────────────────────
COLOR_NONE   = 0
COLOR_RED    = 1
COLOR_GREEN  = 2
COLOR_BLUE   = 3
COLOR_NAMES  = {0: "none", 1: "red", 2: "green", 3: "blue"}

# ── Reintentos de captura ──────────────────────────────────────
MAX_CAPTURE_FAILS = 5
CAPTURE_RETRY_MS  = 500

class CameraTask:
    def __init__(self, scheduler, pubsub, period_ms=500, priority=7):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self.pubsub   = pubsub

        self._grid_pending = None
        self._cam_ok       = False

        # Centroides para acceso rápido desde AutonomyTask
        self.red_cx   = -1
        self.green_cx = -1
        self.blue_cx  = -1

        # Buffer de captura
        self._buf = bytearray(CAM_BUF_SIZE)

        if _CAM_OK:
            self._init_camera()
            if self._cam_ok:
                _thread.stack_size(8192)
                _thread.start_new_thread(self._cam_loop, ())
        else:
            print("[CAM] Driver no disponible — CameraTask sin video")

        scheduler.add(self)
        pubsub.publish("camera/debug", {"msg": "CameraTask HSV con centroides"})
        print("[CAM] CameraTask lista ({}x{}, centroides activos)".format(CAM_W, CAM_H))

    # ── Inicializar hardware (I2C0, pines 16,17) ──
    def _init_camera(self):
        try:
            from machine import I2C
            i2c = I2C(0, freq=400_000,
                      scl=Pin(CAM_SCL), sda=Pin(CAM_SDA))

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
            self._cam.write_register(OV7670_REG_CLKRC, 0x01)
            self._cam.wrapper_configure_rgb()
            self._cam.wrapper_configure_size(OV7670_WRAPPER_SIZE_DIV4)
            self._cam.wrapper_configure_test_pattern(OV7670_WRAPPER_TEST_PATTERN_NONE)
            gc.collect()
            self._cam_ok = True
            print("[CAM] OV7670 inicializada {}x{}".format(CAM_W, CAM_H))
        except Exception as e:
            print("[CAM] Error init OV7670:", e)
            self._cam_ok = False

    # ── Hilo de captura y análisis (núcleo 1) ──
    def _cam_loop(self):
        utime.sleep(2)
        print("[CAM] Hilo de captura + video iniciado")

        # Servidor WebSocket para video
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(socket.getaddrinfo("0.0.0.0", VIDEO_PORT)[0][-1])
        srv.listen(1)

        buf = self._buf

        while True:
            try:
                cl, addr = srv.accept()
                print("[CAM WS] cliente conectado:", addr)

                # Handshake WebSocket
                try:
                    req = b""
                    while b"\r\n\r\n" not in req:
                        chunk = cl.recv(256)
                        if not chunk:
                            break
                        req += chunk
                    ws_key = b""
                    for line in req.split(b"\r\n"):
                        if b"Sec-WebSocket-Key" in line:
                            ws_key = line.split(b": ")[1].strip()
                            break
                    if not ws_key:
                        cl.close()
                        continue
                    accept = ubinascii.b2a_base64(
                        hashlib.sha1(ws_key + GUID).digest()
                    ).strip()
                    cl.send((
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        "Sec-WebSocket-Accept: " + accept.decode() + "\r\n\r\n"
                    ).encode())
                    print("[CAM WS] handshake OK")
                except Exception as e:
                    print("[CAM WS] handshake error:", e)
                    cl.close()
                    continue

                fail_count = 0
                # Bucle de captura continua
                while True:
                    try:
                        self._cam.capture(buf)
                        fail_count = 0
                    except Exception as e:
                        fail_count += 1
                        if fail_count >= MAX_CAPTURE_FAILS:
                            break
                        utime.sleep_ms(CAPTURE_RETRY_MS)
                        continue

                    # 1. Calcular centroides (muy rápido) para autonomía
                    self._calcular_centroides(buf)

                    # 2. Opcional: enviar grid al broker cada cierto tiempo
                    #    (si quieres ahorrar CPU, puedes comentar esto)
                    if self.pubsub and (utime.ticks_ms() % 500) < 20:  # ~2 Hz
                        try:
                            grid = self._analizar_grid(buf)
                            self.pubsub.publish("camera/grid", {
                                "cols": GRID_COLS,
                                "rows": GRID_ROWS,
                                "cells": grid,
                            })
                        except Exception as e:
                            print("[CAM] grid error:", e)

                    # 3. Enviar frame de video al cliente WebSocket
                    try:
                        self._ws_send_binary(cl, buf)
                    except Exception as e:
                        print("[CAM WS] cliente desconectado:", e)
                        break

                    utime.sleep_ms(SEND_INTERVAL_MS)
                    gc.collect()

            except Exception as e:
                print("[CAM WS] error servidor:", e)
            finally:
                try:
                    cl.close()
                except:
                    pass

    # ── WebSocket: envío de frame binario ──
    def _ws_send_binary(self, sock, payload):
        L = len(payload)
        hdr = bytearray([0x82])  # opcode binary
        if L <= 125:
            hdr.append(L)
        elif L <= 0xFFFF:
            hdr.append(126)
            hdr.extend(struct.pack(">H", L))
        else:
            hdr.append(127)
            hdr.extend(struct.pack(">Q", L))
        sock.send(hdr)
        sent = 0
        while sent < L:
            sent += sock.send(payload[sent:])

    # ── Conversión RGB565 a RGB ──
    @staticmethod
    def _rgb565_to_rgb(pixel):
        r = ((pixel >> 11) & 0x1F) << 3
        g = ((pixel >> 5) & 0x3F) << 2
        b = (pixel & 0x1F) << 3
        return r, g, b

    # ── Conversión RGB a HSV (rápida) ──
    @staticmethod
    def _rgb_to_hsv(r, g, b):
        rn = r / 255.0
        gn = g / 255.0
        bn = b / 255.0
        maxc = max(rn, gn, bn)
        minc = min(rn, gn, bn)
        diff = maxc - minc
        if diff == 0:
            h = 0
        elif maxc == rn:
            h = 60 * (((gn - bn) / diff) % 6)
        elif maxc == gn:
            h = 60 * (((bn - rn) / diff) + 2)
        else:
            h = 60 * (((rn - gn) / diff) + 4)
        if h < 0:
            h += 360
        s = 0 if maxc == 0 else (diff / maxc) * 255
        v = maxc * 255
        return h, s, v

    # ── Clasificación de píxel usando HSV ──
    def _clasificar_pixel(self, r, g, b):
        h, s, v = self._rgb_to_hsv(r, g, b)
        # Rojo
        for h_min, h_max, s_min, v_min in HSV_RANGES["red"]:
            if h_min <= h <= h_max and s >= s_min and v >= v_min:
                return COLOR_RED
        # Verde
        for h_min, h_max, s_min, v_min in HSV_RANGES["green"]:
            if h_min <= h <= h_max and s >= s_min and v >= v_min:
                return COLOR_GREEN
        # Azul
        for h_min, h_max, s_min, v_min in HSV_RANGES["blue"]:
            if h_min <= h <= h_max and s >= s_min and v >= v_min:
                return COLOR_BLUE
        return COLOR_NONE

    # ── Cálculo de centroides (coordenada X del color) ──
    def _calcular_centroides(self, buf):
        y0 = CAM_H // 5
        y1 = 4 * CAM_H // 5
        sr = br = sg = bg = sb = bb = 0
        step = 3
        for y in range(y0, y1, step):
            for x in range(0, CAM_W, step):
                idx = (y * CAM_W + x) * 2
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
        MIN_PX = 30
        self.red_cx   = sr // br if br >= MIN_PX else -1
        self.green_cx = sg // bg if bg >= MIN_PX else -1
        self.blue_cx  = sb // bb if bb >= MIN_PX else -1

    # ── Análisis de cuadrícula (para frontend, no esencial) ──
    def _analizar_grid(self, buf):
        cell_w = CAM_W // GRID_COLS
        cell_h = CAM_H // GRID_ROWS
        cells = []
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                x0 = col * cell_w
                y0 = row * cell_h
                cnt = {COLOR_RED: 0, COLOR_GREEN: 0, COLOR_BLUE: 0}
                total = 0
                for y in range(y0, y0 + cell_h, 3):
                    for x in range(x0, x0 + cell_w, 3):
                        idx = (y * CAM_W + x) * 2
                        if idx+1 >= len(buf):
                            continue
                        pixel = (buf[idx] << 8) | buf[idx+1]
                        r, g, b = self._rgb565_to_rgb(pixel)
                        c = self._clasificar_pixel(r, g, b)
                        if c != COLOR_NONE:
                            cnt[c] += 1
                        total += 1
                if total == 0:
                    cells.append("none")
                else:
                    best = max(cnt.items(), key=lambda x: x[1])
                    if best[1] > total * COLOR_THRESHOLD:
                        cells.append(COLOR_NAMES[best[0]])
                    else:
                        cells.append("none")
        return cells

    # ── update() del scheduler (se ejecuta periódicamente) ──
    def update(self):
        gc.collect()
        # No hacemos nada aquí, porque la cámara ya publica grid ocasionalmente
        # Los centroides se actualizan en el hilo y están disponibles para lectura.
        pass
