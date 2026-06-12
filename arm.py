"""
arm.py — Control del brazo (3 servos) con movimientos muy suaves (ease-in-out)
Robot11 | MicroPython - Raspberry Pi Pico 2W

Hardware:
    GP18 → Servo BASE
    GP19 → Servo HOMBRO
    GP20 → Servo CODO

Movimientos suaves gracias a:
    - SMOOTH_STEPS = 120 (más pasos)
    - Curva de easing (acelera y desacelera)
"""

from machine import Pin, PWM
from scheduler import Task
import utime

PIN_BASE   = 18
PIN_HOMBRO = 19
PIN_CODO   = 20

FREQ      = 50
PULSO_MIN = 500    # µs
PULSO_MAX = 2500   # µs

POSTURA_HOME   = {"base": 90, "hombro": 90,  "codo": 90}
POSTURA_ABAJO  = {"base": 90, "hombro": 170, "codo": 90}
POSTURA_ARRIBA = {"base": 90, "hombro": 90,  "codo": 170}

SMOOTH_STEPS = 120   # número de pasos (mayor = más suave y lento)

def _duty(angle):
    angle = max(0, min(180, angle))
    us = PULSO_MIN + (PULSO_MAX - PULSO_MIN) * angle / 180
    return int(us / 20000 * 65535)

class ArmTask(Task):
    def __init__(self, scheduler, pubsub, period_ms=20, priority=5):
        super().__init__(scheduler, period_ms=period_ms, priority=priority)
        self.pubsub = pubsub
        self._servos = {
            "base":   PWM(Pin(PIN_BASE),   freq=FREQ),
            "hombro": PWM(Pin(PIN_HOMBRO), freq=FREQ),
            "codo":   PWM(Pin(PIN_CODO),   freq=FREQ),
        }
        self._angles = dict(POSTURA_HOME)
        self._queue = []   # lista de [target_dict, steps, step_actual]
        self._apply(POSTURA_HOME)

        pubsub.subscribe("arm/cmd", self._on_cmd)
        print("[ARM] ArmTask lista - movimientos suaves con easing, {} pasos".format(SMOOTH_STEPS))

    def _apply(self, postura):
        for name, angle in postura.items():
            self._set_servo(name, angle)

    def _set_servo(self, name, angle):
        angle = max(0, min(180, int(angle)))
        self._angles[name] = angle
        self._servos[name].duty_u16(_duty(angle))

    def _queue_smooth(self, target, steps=None):
        if steps is None:
            steps = SMOOTH_STEPS
        self._queue.append([dict(target), steps, 0])

    def _sequence_to_posture(self, final_posture):
        """
        Añade a la cola los movimientos necesarios para llegar a 'final_posture'
        respetando la regla: el codo solo se mueve cuando el hombro está a 90°.
        """
        current = self._angles
        final = final_posture
        # Mover codo (si es necesario) asegurando hombro a 90°
        if "codo" in final and final["codo"] != current.get("codo", 90):
            if current.get("hombro", 90) != 90:
                self._queue_smooth({"hombro": 90})
            self._queue_smooth({"codo": final["codo"]})
        # Luego mover hombro (si es necesario y no está en 90° final)
        if "hombro" in final and final["hombro"] != current.get("hombro", 90):
            self._queue_smooth({"hombro": final["hombro"]})
        # Finalmente mover base
        if "base" in final and final["base"] != current.get("base", 90):
            self._queue_smooth({"base": final["base"]})

    def _on_cmd(self, data):
        action = data.get("action")
        if action == "rutina":
            self._start_rutina()
        elif action == "home":
            self._sequence_to_posture(POSTURA_HOME)
        elif action == "abajo":
            self._sequence_to_posture(POSTURA_ABAJO)
        elif action == "arriba":
            self._sequence_to_posture(POSTURA_ARRIBA)
        elif "servo" in data and "angle" in data:
            self._set_servo(data["servo"], data["angle"])
            self._publish_state()

    def _start_rutina(self):
        self._queue.clear()
        for _ in range(3):
            self._sequence_to_posture(POSTURA_ARRIBA)
            self._sequence_to_posture(POSTURA_ABAJO)
        self._sequence_to_posture(POSTURA_ARRIBA)
        self._sequence_to_posture(POSTURA_HOME)
        print("[ARM] Rutina encolada ({} movimientos suaves)".format(len(self._queue)))

    def update(self):
        if not self._queue:
            return
        target, steps_total, step = self._queue[0]
        # Progreso lineal (0..1)
        t = (step + 1) / steps_total
        # Curva ease-in-out: suave al inicio y al final
        t_ease = t * t * (3 - 2 * t)   # 3t^2 - 2t^3
        changed = False
        for name, dest in target.items():
            origin = self._angles[name]
            new_angle = int(origin + (dest - origin) * t_ease)
            if new_angle != self._angles[name]:
                self._set_servo(name, new_angle)
                changed = True
        step += 1
        if step >= steps_total:
            self._apply(target)
            self._queue.pop(0)
            self._publish_state()
        else:
            self._queue[0] = [target, steps_total, step]

    def _publish_state(self):
        self.pubsub.publish("arm/state", dict(self._angles))