from machine import Pin, PWM
from scheduler import Task

IN1 = 21
IN2 = 22
IN3 = 26
IN4 = 27
ENA_PIN = 10
ENB_PIN = 11

def _pct_to_duty(pct):
    return int(max(0, min(100, pct)) / 100 * 65535)

class CarTask(Task):
    def __init__(self, scheduler, pubsub, period_ms=50, priority=5):
        super().__init__(scheduler, period_ms=period_ms, priority=priority)
        self.pubsub = pubsub
        self._in1 = Pin(IN1, Pin.OUT)
        self._in2 = Pin(IN2, Pin.OUT)
        self._in3 = Pin(IN3, Pin.OUT)
        self._in4 = Pin(IN4, Pin.OUT)
        self._ena = PWM(Pin(ENA_PIN), freq=1000) if ENA_PIN else None
        self._enb = PWM(Pin(ENB_PIN), freq=1000) if ENB_PIN else None
        self._pending = None
        self._stop()

        # Factores de corrección (ajústalos según pruebas)
        self.factor_der = 1.0   # Motor derecho (ENA, GP10)
        self.factor_izq = 0.9  # Motor izquierdo (ENB, GP11)

        pubsub.subscribe("car/cmd", self._on_cmd)
        print("[CAR] CarTask lista con factores en todos los movimientos")

    def _on_cmd(self, data):
        self._pending = data

    def update(self):
        if self._pending is None:
            return
        cmd = self._pending
        self._pending = None
        direction = cmd.get("dir", "stop")
        speed = cmd.get("speed", 60)
        duty = _pct_to_duty(speed)
        if direction == "fwd":   self._forward(duty)
        elif direction == "bwd": self._backward(duty)
        elif direction == "left": self._turn_left(duty)
        elif direction == "right": self._turn_right(duty)
        else: self._stop()

    def _set_duty(self, duty_der, duty_izq):
        if self._ena:
            self._ena.duty_u16(duty_der)
        if self._enb:
            self._enb.duty_u16(duty_izq)

    def _forward(self, duty):
        self._set_duty(int(duty * self.factor_der), int(duty * self.factor_izq))
        self._in1.value(1); self._in2.value(0)
        self._in3.value(1); self._in4.value(0)

    def _backward(self, duty):
        self._set_duty(int(duty * self.factor_der), int(duty * self.factor_izq))
        self._in1.value(0); self._in2.value(1)
        self._in3.value(0); self._in4.value(1)

    def _turn_left(self, duty):
        self._set_duty(int(duty * self.factor_der), int(duty * self.factor_izq))
        self._in1.value(0); self._in2.value(1)   # izquierdo atrás
        self._in3.value(1); self._in4.value(0)   # derecho adelante

    def _turn_right(self, duty):
        self._set_duty(int(duty * self.factor_der), int(duty * self.factor_izq))
        self._in1.value(1); self._in2.value(0)   # izquierdo adelante
        self._in3.value(0); self._in4.value(1)   # derecho atrás

    def _stop(self):
        self._set_duty(0, 0)
        self._in1.value(0); self._in2.value(0)
        self._in3.value(0); self._in4.value(0)