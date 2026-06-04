"""
display.py — Pantalla OLED SSD1306 128x64
Robot7| Proyecto Final

Clase: DisplayTask
Hereda de Task (scheduler.py)

Pines:
  GP14 → SDA  (I2C compartido con OV7670)
  GP15 → SCL

Topics suscritos:
  system/mode   → {mode: "carrito"|"brazo"}
  car/state     → {state, dm}
  arm/state     → {state, step, total}
  battery/level → {percent, voltage}
  debug/log     → {msg}

Topics publicados:
  Ninguno — solo muestra información

Notas:
  - El bus I2C es compartido con la cámara OV7670 (addr 0x21)
  - El OLED usa addr 0x3C
  - SoftI2C para compatibilidad con cualquier pin
"""

from machine import Pin, SoftI2C
import ssd1306
import utime


# ─────────────────────────────────────────────────────────────
#  Pines
# ─────────────────────────────────────────────────────────────
_SDA = 20
_SCL = 21


class DisplayTask:
    """
    Maneja la pantalla OLED SSD1306 128×64.

    Uso sin PubSub (prueba):
        d = DisplayTask()
        d.mostrar_boot()

    Uso con PubSub (main.py):
        d = DisplayTask(scheduler=sched, pubsub=node)
    """

    def __init__(self, scheduler=None, pubsub=None,
                 i2c=None, period_ms=500, priority=4):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()

        # Estado interno
        self._mode    = "carrito"
        self._log     = ""
        self._wifi    = False
        self._broker  = False
        self._bat_pct = -1
        self._bat_v   = 0.0
        self._car_st  = "idle"
        self._arm_st  = "idle"

        # I2C — reutiliza el que se pase, o crea uno nuevo
        if i2c is None:
            i2c = SoftI2C(
                scl=Pin(_SCL), sda=Pin(_SDA), freq=400_000
            )
        self._i2c = i2c
        self.oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)

        # Pantalla de boot inmediata
        self.mostrar_boot()

        # Suscripciones
        if pubsub:
            self.set_pubsub(pubsub)

        # Registro en scheduler
        if scheduler:
            scheduler.add(self)

    # ══════════════════════════════════════════════════════════
    #  Conexión PubSub (puede hacerse después del __init__)
    # ══════════════════════════════════════════════════════════

    def set_pubsub(self, pubsub):
        pubsub.subscribe("system/mode",   self._on_mode)
        pubsub.subscribe("car/state",     self._on_car)
        pubsub.subscribe("arm/state",     self._on_arm)
        pubsub.subscribe("battery/level", self._on_battery)
        pubsub.subscribe("debug/log",     self._on_log)

    # ══════════════════════════════════════════════════════════
    #  Setters de estado de conexión
    # ══════════════════════════════════════════════════════════

    def set_wifi(self, ok):
        self._wifi = ok

    def set_broker(self, ok):
        self._broker = ok

    # ══════════════════════════════════════════════════════════
    #  Callbacks PubSub
    # ══════════════════════════════════════════════════════════

    def _on_mode(self, data):
        self._mode = data.get("mode", "carrito")

    def _on_car(self, data):
        self._car_st = data.get("state", "idle")

    def _on_arm(self, data):
        self._arm_st = data.get("state", "idle")

    def _on_battery(self, data):
        self._bat_pct = data.get("percent", -1)
        self._bat_v   = data.get("voltage", 0.0)

    def _on_log(self, data):
        self._log = str(data.get("msg", ""))[:16]

    # ══════════════════════════════════════════════════════════
    #  Pantallas especiales (llamadas directamente)
    # ══════════════════════════════════════════════════════════

    def mostrar_boot(self):
        self.oled.fill(0)
        self.oled.text("ROBOT11  v2.0", 0, 0)
        self.oled.hline(0, 10, 128, 1)
        self.oled.text("Iniciando...", 0, 24)
        self.oled.text("Espere...", 0, 40)
        self.oled.show()

    def mostrar_conectando_wifi(self, t):
        sp = ["|", "/", "-", "\\"][t % 4]
        self.oled.fill(0)
        self.oled.text("Conectando WiFi", 0, 0)
        self.oled.hline(0, 10, 128, 1)
        self.oled.text("Red: robot11", 0, 18)
        self.oled.text(f"{sp} espere...", 0, 32)
        self.oled.show()

    def mostrar_wifi_ok(self, ip):
        self.oled.fill(0)
        self.oled.text("WiFi OK!", 28, 0)
        self.oled.hline(0, 10, 128, 1)
        self.oled.text(ip, 0, 18)
        self.oled.text("Conectando broker", 0, 32)
        self.oled.show()

    def mostrar_broker_ok(self):
        self.oled.fill(0)
        self.oled.text("Broker OK!", 20, 0)
        self.oled.hline(0, 10, 128, 1)
        self.oled.text("Robot11 listo", 0, 24)
        self.oled.show()
        utime.sleep(1)

    # ══════════════════════════════════════════════════════════
    #  Iconos de estado (esquina superior derecha)
    # ══════════════════════════════════════════════════════════

    def _draw_icons(self):
        # WiFi (x=90)
        if self._wifi:
            self.oled.fill_rect(94, 0, 3, 2, 1)
            self.oled.hline(91, 3, 7, 1)
            self.oled.hline(89, 5, 11, 1)
        else:
            self.oled.pixel(95, 1, 1)
            self.oled.pixel(96, 1, 1)
            self.oled.hline(91, 4, 7, 1)

        # Broker / WS (x=104)
        if self._broker:
            self.oled.fill_rect(104, 1, 10, 7, 1)
        else:
            self.oled.rect(104, 1, 10, 7, 1)

        # Batería (x=116)
        if self._bat_pct >= 0:
            self.oled.rect(116, 1, 10, 7, 1)
            self.oled.fill_rect(126, 3, 2, 3, 1)   # polo +
            ancho = max(0, int(8 * self._bat_pct / 100))
            if ancho > 0:
                self.oled.fill_rect(117, 2, ancho, 5, 1)

    # ══════════════════════════════════════════════════════════
    #  update() — llamado por el Scheduler cada period_ms
    # ══════════════════════════════════════════════════════════

    def update(self):
        self.oled.fill(0)

        # ── Línea 1: título + modo ────────────────────────────
        if self._mode == "carrito":
            self.oled.text("== CARRITO ==", 0, 0)
        else:
            self.oled.text("=== BRAZO ===", 0, 0)
        self.oled.hline(0, 10, 128, 1)

        # ── Línea 2-3: estado activo ─────────────────────────
        if self._mode == "carrito":
            st = self._car_st
            self.oled.text(f"Estado: {st[:8]}", 0, 14)
            self.oled.text("car/cmd → robot", 0, 25)
        else:
            st = self._arm_st
            self.oled.text(f"Brazo: {st[:9]}", 0, 14)
            self.oled.text("arm/cmd → robot", 0, 25)

        # ── Línea 4: batería ─────────────────────────────────
        if self._bat_pct >= 0:
            self.oled.text(
                f"Bat:{self._bat_pct:3d}% {self._bat_v:.1f}V", 0, 37
            )
        else:
            self.oled.text("Bat: --", 0, 37)

        # ── Línea 5: log ─────────────────────────────────────
        self.oled.hline(0, 49, 128, 1)
        if self._log:
            self.oled.text(self._log[:16], 0, 53)

        # ── Iconos de conexión ────────────────────────────────
        self._draw_icons()

        self.oled.show()