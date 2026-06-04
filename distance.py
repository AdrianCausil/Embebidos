"""
distance.py — Tarea de sensor ultrasónico HC-SR04
Robot7 | MicroPython - Raspberry Pi Pico 2W

Hardware:
    TRIG → GP4  (salida digital)
    ECHO → GP5  (entrada con divisor de voltaje R1=10kΩ / R2=20kΩ)
                 ¡Obligatorio! El HC-SR04 entrega 5V en ECHO.
                 Sin divisor puedes quemar la Pico.

Divisor recomendado para ECHO:
    GP5 ──┬── R2 (20kΩ) ──── ECHO del sensor
          └── R1 (10kΩ) ──── GND
    (divide 5V → ~3.3V)

Rango útil HC-SR04: 2 cm — 400 cm
Timeout: si no hay eco en 30 ms publica cm=-1 (sin objeto)

Tópico publicado:
    "distance/data"  →  {"cm": float}   (cm=-1 si fuera de rango)
"""

import machine
import utime
from scheduler import Task


# ─────────────────────────────────────────────────────────────
TRIG_PIN    = 4
ECHO_PIN    = 5
TIMEOUT_US  = 30_000   # 30 ms → ~5 m máximo, fuera de rango del sensor


# ─────────────────────────────────────────────────────────────
class DistanceTask(Task):
    """
    Dispara el HC-SR04 y mide la distancia cada `period_ms` ms.
    Publica el resultado en "distance/data".

    Prioridad 6.
    """

    def __init__(self, scheduler, pubsub,
                 trig=TRIG_PIN, echo=ECHO_PIN, period_ms=200):
        super().__init__(scheduler, period_ms=period_ms, priority=6)
        self.pubsub = pubsub
        self.trig   = machine.Pin(trig, machine.Pin.OUT)
        self.echo   = machine.Pin(echo, machine.Pin.IN)
        self.cm     = -1.0
        self.trig.value(0)   # asegurar TRIG en bajo al inicio
        print("[DIST] DistanceTask lista (TRIG=GP{}, ECHO=GP{}, {}ms)".format(
              trig, echo, period_ms))

    # ── Medición ──────────────────────────────────────────────

    def _measure(self):
        """
        Retorna distancia en cm, o -1 si está fuera de rango.
        Pulso TRIG de 10 µs → mide ancho del pulso ECHO.
        Distancia = tiempo_µs / 58
        """
        # Pulso de disparo
        self.trig.value(0)
        utime.sleep_us(2)
        self.trig.value(1)
        utime.sleep_us(10)
        self.trig.value(0)

        # Medir ancho del pulso ECHO (retorna -1 o -2 si timeout)
        duration = machine.time_pulse_us(self.echo, 1, TIMEOUT_US)

        if duration < 0:
            return -1.0   # sin objeto o fuera de rango

        cm = duration / 58.0
        return round(cm, 1)

    # ── update() ──────────────────────────────────────────────

    def update(self):
        self.cm = self._measure()
        self.pubsub.publish("distance/data", {"cm": self.cm})

        if self.cm < 0:
            print("[DIST] Fuera de rango")
        else:
            print("[DIST] {:.1f} cm".format(self.cm))
