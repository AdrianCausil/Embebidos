"""
distance.py — Tarea de sensor ultrasónico HC-SR04
Robot11 | Pines: TRIG=14, ECHO=15 (liberados de la cámara)
"""

import machine
import utime
from scheduler import Task

TRIG_PIN = 14   # GP14
ECHO_PIN = 15   # GP15
TIMEOUT_US = 30000

class DistanceTask(Task):
    def __init__(self, scheduler, pubsub, trig=TRIG_PIN, echo=ECHO_PIN, period_ms=200):
        super().__init__(scheduler, period_ms=period_ms, priority=6)
        self.pubsub = pubsub
        self.trig = machine.Pin(trig, machine.Pin.OUT)
        self.echo = machine.Pin(echo, machine.Pin.IN)
        self.cm = -1.0
        self.trig.value(0)
        print("[DIST] DistanceTask lista (TRIG=GP{}, ECHO=GP{}, {}ms)".format(trig, echo, period_ms))

    def _measure(self):
        self.trig.value(0)
        utime.sleep_us(2)
        self.trig.value(1)
        utime.sleep_us(10)
        self.trig.value(0)
        duration = machine.time_pulse_us(self.echo, 1, TIMEOUT_US)
        if duration < 0:
            return -1.0
        return round(duration / 58.0, 1)

    def update(self):
        self.cm = self._measure()
        self.pubsub.publish("distance/data", {"cm": self.cm})
        if self.cm < 0:
            print("[DIST] Fuera de rango")
        else:
            print("[DIST] {:.1f} cm".format(self.cm))