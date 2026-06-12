"""
autonomy_color.py — Autonomía basada solo en cámara: gira, detecta color, alinea, avanza y recoge.
"""

import utime
from scheduler import Task

# Parámetros
SCAN_SPEED = 40          # velocidad de giro (0-100) para buscar color
ALIGN_SPEED = 30         # velocidad para centrar
FORWARD_SPEED = 60       # velocidad para avanzar
FORWARD_TIME_MS = 2000   # tiempo de avance (ms) → ajustar según distancia
CENTER_TOLERANCE = 30    # píxeles de tolerancia para considerar centrado
MIN_CX = 50              # mínimo centroide válido (para evitar ruido)

class ColorAutonomyTask(Task):
    def __init__(self, scheduler, pubsub, car_task, arm_task, camera_task,
                 period_ms=50, priority=6):
        super().__init__(scheduler, period_ms=period_ms, priority=priority)
        self.pubsub = pubsub
        self.car = car_task
        self.arm = arm_task
        self.camera = camera_task
        self.state = "IDLE"        # IDLE, SCANNING, ALIGNING, MOVING, GRABBING, DONE
        self.target_color = None   # "red", "green", "blue"
        self.timer_start = 0
        self.duration_ms = 0
        self.executed = False

        print("[AUTO] ColorAutonomyTask iniciada. Buscando colores...")

    def update(self):
        if self.executed:
            return

        # Obtener centroides
        red = self.camera.red_cx
        green = self.camera.green_cx
        blue = self.camera.blue_cx

        # Máquina de estados
        if self.state == "IDLE":
            # Elegir el primer color visible
            if red > MIN_CX:
                self.target_color = "red"
                self.state = "SCANNING"
                print("[AUTO] Detectado ROJO, iniciando barrido fino")
            elif green > MIN_CX:
                self.target_color = "green"
                self.state = "SCANNING"
                print("[AUTO] Detectado VERDE, iniciando barrido fino")
            elif blue > MIN_CX:
                self.target_color = "blue"
                self.state = "SCANNING"
                print("[AUTO] Detectado AZUL, iniciando barrido fino")
            # Si no hay color, girar (modo SCANNING implícito)
            else:
                self.car.girar_izquierda(SCAN_SPEED)
                return

        elif self.state == "SCANNING":
            cx = self._get_cx()
            if cx < 0:
                # No ve el color, seguir girando
                self.car.girar_izquierda(SCAN_SPEED)
                return
            # Vemos el color, pasamos a alinear
            print("[AUTO] Color visto, alineando...")
            self.state = "ALIGNING"

        elif self.state == "ALIGNING":
            cx = self._get_cx()
            if cx < 0:
                # Perdió el color, volver a escanear
                self.state = "SCANNING"
                return
            error = cx - 80  # centro de la imagen es ~80 píxeles (160/2)
            if abs(error) <= CENTER_TOLERANCE:
                self.car.parar()
                print("[AUTO] Centrado. Bajando brazo...")
                self.start_arm_down()
                self.state = "MOVING"
                self.timer_start = utime.ticks_ms()
                self.duration_ms = FORWARD_TIME_MS
            else:
                # Girar suavemente para centrar
                if error > 0:
                    self.car.girar_derecha(ALIGN_SPEED)
                else:
                    self.car.girar_izquierda(ALIGN_SPEED)

        elif self.state == "MOVING":
            # Avanzar durante el tiempo fijo
            if utime.ticks_diff(utime.ticks_ms(), self.timer_start) >= self.duration_ms:
                self.car.parar()
                print("[AUTO] Avance completado. Subiendo brazo...")
                self.start_arm_up()
                self.state = "GRABBING"
            else:
                self.car.adelante(FORWARD_SPEED)

        elif self.state == "GRABBING":
            # Esperar a que el brazo termine (opcional, usar timer)
            if utime.ticks_diff(utime.ticks_ms(), self.timer_start) >= 3000:
                print("[AUTO] Secuencia completada. FIN.")
                self.state = "DONE"
                self.executed = True

    def _get_cx(self):
        if self.target_color == "red":
            return self.camera.red_cx
        elif self.target_color == "green":
            return self.camera.green_cx
        elif self.target_color == "blue":
            return self.camera.blue_cx
        return -1

    def start_arm_down(self):
        self.pubsub.publish("arm/cmd", {"action": "abajo"})
        self.timer_start = utime.ticks_ms()

    def start_arm_up(self):
        self.pubsub.publish("arm/cmd", {"action": "arriba"})
        self.timer_start = utime.ticks_ms()