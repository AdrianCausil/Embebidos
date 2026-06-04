"""
battery.py -- Medidor de bateria 2S Li-Ion (8.4V max)
Robot7 | Proyecto Final

Circuito divisor de voltaje:
  Bateria (+) --- R1 (82kohm) ---+--- R2 (47kohm) --- GND
                                 |
                                GP28 (ADC2, pin fisico 34)

Calculo verificado:
  Vout a 8.4V = 3.06V  (dentro del rango ADC 0-3.3V)
  Vout a 6.0V = 2.19V
  FACTOR      = 2.7447

Rangos bateria 2S Li-Ion:
  V_MAX = 8.4V  (100% -- cargada)
  V_NOM = 7.4V  (nominal)
  V_MIN = 6.0V  (0%  -- descargada, no bajar de aqui)

Topics publicados:
  battery/level -> {percent, voltage}
"""

from machine import ADC, Pin
import utime

VOLTAGE_DROP_FACTOR = 2.849   # R1=82k R2=47k -- afinar con multimetro
V_MAX = 8.4
V_MIN = 6.0
BAT_PIN = 28   # GP28 = ADC2


class BatteryTask:
    """
    Lee voltaje de bateria 2S cada period_ms y publica battery/level.

    Uso sin PubSub (prueba):
        bat = BatteryTask()
        bat.update()

    Uso con PubSub (main.py):
        bat = BatteryTask(scheduler=sched, pubsub=node, period_ms=30000)
    """

    def __init__(self, scheduler=None, pubsub=None,
                 period_ms=30_000, priority=9):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        self._pubsub  = pubsub
        self._adc     = ADC(Pin(BAT_PIN))
        self.percent  = 0
        self.voltage  = 0.0

        if scheduler:
            scheduler.add(self)

    def read(self):
        """Lee el voltaje y devuelve (percent, voltage)."""
        raw          = self._adc.read_u16()
        v_pin        = raw * 3.3 / 65535
        v_bat        = v_pin * VOLTAGE_DROP_FACTOR
        pct          = (v_bat - V_MIN) / (V_MAX - V_MIN) * 100
        pct          = max(0, min(100, int(pct)))
        self.percent = pct
        self.voltage = round(v_bat, 2)
        return pct, self.voltage

    def update(self):
        pct, v = self.read()
        print(f"[BAT] {v}V  {pct}%")
        if self._pubsub:
            self._pubsub.publish("battery/level", {
                "percent": pct,
                "voltage": v
            })