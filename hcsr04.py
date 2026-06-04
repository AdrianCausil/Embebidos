"""
hcsr04.py — Sensor ultrasónico HC-SR04
Robot7

Pines sugeridos (cámara deshabilitada):
  GP2 → TRIG  (salida, pulso 10µs)
  GP3 → ECHO  (entrada, mide duración del eco)

Topics publicados:
  distance/sonar → {cm, valid}

Nota: usa time_pulse_us() de MicroPython — no bloquea el scheduler
más de ~25ms (timeout máximo configurado).
"""

from machine import Pin, time_pulse_us
import utime


TRIG_PIN     = 2
ECHO_PIN     = 3
TIMEOUT_US   = 25000    # 25ms → ~430cm máximo (más que suficiente)
MIN_CM       = 2.0
MAX_CM       = 400.0


class HCSr04Task:
    """
    Mide distancia con HC-SR04 cada period_ms y publica distance/sonar.

    Uso sin PubSub (prueba):
        s = HCSr04Task()
        s.update()

    Uso con PubSub (main.py):
        sonar = HCSr04Task(scheduler=sched, pubsub=node, period_ms=200)
    """

    def __init__(self, scheduler=None, pubsub=None,
                 period_ms=200, priority=6,
                 trig_pin=TRIG_PIN, echo_pin=ECHO_PIN):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self._pubsub  = pubsub

        self._trig = Pin(trig_pin, Pin.OUT)
        self._echo = Pin(echo_pin, Pin.IN)
        self._trig.low()

        self.distance_cm = -1
        self.valid       = False

        if scheduler:
            scheduler.add(self)

    def _medir(self):
        """
        Dispara un pulso TRIG y mide la duración del ECHO.
        Retorna distancia en cm o -1 si hay timeout / fuera de rango.
        """
        # Asegurar TRIG en LOW
        self._trig.low()
        utime.sleep_us(2)

        # Pulso TRIG de 10µs
        self._trig.high()
        utime.sleep_us(10)
        self._trig.low()

        # Medir duración del ECHO en alto
        duracion = time_pulse_us(self._echo, 1, TIMEOUT_US)

        if duracion < 0:
            # Timeout — nada detectado o sensor desconectado
            return -1

        # Velocidad del sonido: 343 m/s = 0.0343 cm/µs
        # distancia = (tiempo_ida_vuelta × velocidad) / 2
        cm = (duracion * 0.0343) / 2.0

        if cm < MIN_CM or cm > MAX_CM:
            return -1

        return round(cm, 1)

    def update(self):
        cm = self._medir()
        self.distance_cm = cm
        self.valid       = (cm > 0)

        if self.valid:
            print(f"[SONAR] {cm} cm")
        else:
            print("[SONAR] sin detección")

        if self._pubsub:
            self._pubsub.publish("distance/sonar", {
                "cm":    cm,
                "valid": self.valid
            })