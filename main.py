"""
main.py -- Modo "Derecho": detecta colores, recoge, gira 90°, pausa, retrocede 10cm, suelta, retrocede, sube brazo a home.
"""

import network
import utime
from scheduler import Scheduler, Task
from pubsub import SocketClient, Node
from car import CarTask
from arm import ArmTask
from camera import CameraTask

# ========== CONFIGURACIÓN ==========
WIFI_SSID = "A35deFabian"
WIFI_PASS = "FAGTAAAA"
BROKER_IP = "10.182.144.3"
BROKER_PORT = 5051

# Parámetros de la rutina de recogida
BACKUP_MS = 0
BACKUP_SPEED = 40
FORWARD_TIME_MS = 1400
FORWARD_SPEED = 50

# Parámetros de la entrega (después de levantar) - retroceso inicial
TURN_90_MS = 1700
TURN_SPEED = 50
DELIVER_PAUSE_MS = 1000          # pausa después del giro
DELIVER_BACKWARD_CM = 15         # cm a retroceder después del giro
DELIVER_BACKWARD_SPEED = 40
CM_PER_SEC = 15.0

# Parámetros de retroceso después de soltar (AHORA ACTIVADO)
DELIVER_BACKUP_MS = 100         # tiempo que retrocede después de soltar (ms)
DELIVER_BACKUP_SPEED = 0
# Se elimina la pausa después de soltar (opcional)
DELIVER_PAUSE_AFTER_DROP_MS = 0   # sin pausa extra

# Tiempos del brazo (segundos)
ARM_DOWN_WAIT_SEC = 1.5
ARM_UP_WAIT_SEC = 1.5

# Umbrales de centroides
TH_RED = -10
TH_GREEN = 20
TH_BLUE = -8
MIN_CONSECUTIVE = 2

# ========== TAREA DE AUTONOMÍA ==========
class AutonomyTask(Task):
    def __init__(self, scheduler, pubsub, car_task, arm_task, camera_task,
                 period_ms=100, priority=6):
        super().__init__(scheduler, period_ms=period_ms, priority=priority)
        self.pubsub = pubsub
        self.car = car_task
        self.arm = arm_task
        self.camera = camera_task

        self.state = "IDLE"
        self.timer_start = 0
        self.detection_counter = 0
        self.sequence_started = False
        self.deliver_backward_time_ms = int((DELIVER_BACKWARD_CM / CM_PER_SEC) * 1000) if CM_PER_SEC > 0 else 0

        self._print_timer = utime.ticks_ms()
        print("[AUTO] Modo DERECHO con retroceso después de soltar ({} ms). Esperando colores...".format(DELIVER_BACKUP_MS))

    def update(self):
        now = utime.ticks_ms()

        if utime.ticks_diff(now, self._print_timer) >= 1000:
            self._print_timer = now
            print(f"[CAM] R:{self.camera.red_cx:3d} G:{self.camera.green_cx:3d} B:{self.camera.blue_cx:3d}")

        if self.state == "DONE":
            return

        # Detección de colores en IDLE
        if self.state == "IDLE":
            r = self.camera.red_cx
            g = self.camera.green_cx
            b = self.camera.blue_cx
            if r > TH_RED and g > TH_GREEN and b > TH_BLUE:
                self.detection_counter += 1
                if self.detection_counter >= MIN_CONSECUTIVE and not self.sequence_started:
                    print(f"[AUTO] ¡Colores detectados! (R={r} G={g} B={b})")
                    self.sequence_started = True
                    self._start_sequence()
            else:
                self.detection_counter = 0

        # Estados de recogida
        if self.state == "BACKUP":
            if utime.ticks_diff(now, self.timer_start) >= BACKUP_MS:
                self.pubsub.publish("car/cmd", {"dir": "stop"})
                self.state = "ARM_DOWN"
                self.timer_start = now
                self.pubsub.publish("arm/cmd", {"action": "abajo"})
                print("[AUTO] Bajando brazo...")

        elif self.state == "ARM_DOWN":
            if utime.ticks_diff(now, self.timer_start) >= ARM_DOWN_WAIT_SEC * 1000:
                self.state = "FORWARD"
                self.timer_start = now
                if FORWARD_TIME_MS > 0:
                    print(f"[AUTO] Avanzando {FORWARD_TIME_MS} ms")
                    self.pubsub.publish("car/cmd", {"dir": "fwd", "speed": FORWARD_SPEED})
                else:
                    self.state = "ARM_UP"
                    self.timer_start = now
                    self.pubsub.publish("arm/cmd", {"action": "home"})

        elif self.state == "FORWARD":
            if utime.ticks_diff(now, self.timer_start) >= FORWARD_TIME_MS:
                self.pubsub.publish("car/cmd", {"dir": "stop"})
                print("[AUTO] Avance completado. Subiendo brazo...")
                self.state = "ARM_UP"
                self.timer_start = now
                self.pubsub.publish("arm/cmd", {"action": "home"})

        elif self.state == "ARM_UP":
            if utime.ticks_diff(now, self.timer_start) >= ARM_UP_WAIT_SEC * 1000:
                print("[AUTO] Brazo arriba. Iniciando entrega (giro)...")
                self.state = "DELIVER_TURN"
                self.timer_start = now
                self.pubsub.publish("car/cmd", {"dir": "right", "speed": TURN_SPEED})
                print(f"[AUTO] Girando derecha {TURN_90_MS} ms")

        # Estados de entrega: retrocede después de girar, suelta, luego retrocede más
        elif self.state == "DELIVER_TURN":
            if utime.ticks_diff(now, self.timer_start) >= TURN_90_MS:
                self.pubsub.publish("car/cmd", {"dir": "stop"})
                print("[AUTO] Giro completado. Pausando antes de retroceder...")
                self.state = "DELIVER_PAUSE"
                self.timer_start = now

        elif self.state == "DELIVER_PAUSE":
            if utime.ticks_diff(now, self.timer_start) >= DELIVER_PAUSE_MS:
                self.state = "DELIVER_BACKWARD"
                self.timer_start = now
                if self.deliver_backward_time_ms > 0:
                    print(f"[AUTO] Retrocediendo {DELIVER_BACKWARD_CM} cm ({self.deliver_backward_time_ms} ms)")
                    self.pubsub.publish("car/cmd", {"dir": "bwd", "speed": DELIVER_BACKWARD_SPEED})
                else:
                    self.state = "DELIVER_DOWN"
                    self.timer_start = now
                    self.pubsub.publish("arm/cmd", {"action": "abajo"})

        elif self.state == "DELIVER_BACKWARD":
            if utime.ticks_diff(now, self.timer_start) >= self.deliver_backward_time_ms:
                self.pubsub.publish("car/cmd", {"dir": "stop"})
                print("[AUTO] Retroceso completado. Bajando brazo para soltar...")
                self.state = "DELIVER_DOWN"
                self.timer_start = now
                self.pubsub.publish("arm/cmd", {"action": "abajo"})

        elif self.state == "DELIVER_DOWN":
            if utime.ticks_diff(now, self.timer_start) >= ARM_DOWN_WAIT_SEC * 1000:
                print("[AUTO] Estiba soltada. Retrocediendo para separarse...")
                self.state = "DELIVER_BACKUP"
                self.timer_start = now
                self.pubsub.publish("car/cmd", {"dir": "bwd", "speed": DELIVER_BACKUP_SPEED})
                print(f"[AUTO] Retrocediendo {DELIVER_BACKUP_MS} ms")

        elif self.state == "DELIVER_BACKUP":
            if utime.ticks_diff(now, self.timer_start) >= DELIVER_BACKUP_MS:
                self.pubsub.publish("car/cmd", {"dir": "stop"})
                print("[AUTO] Retroceso completado. Subiendo brazo a home...")
                self.state = "FINAL_ARM_UP"
                self.timer_start = now
                self.pubsub.publish("arm/cmd", {"action": "home"})

        elif self.state == "FINAL_ARM_UP":
            if utime.ticks_diff(now, self.timer_start) >= ARM_UP_WAIT_SEC * 1000:
                print("[AUTO] Secuencia completada (brazo en home). Fin.")
                self.state = "DONE"

    def _start_sequence(self):
        if BACKUP_MS > 0:
            self.state = "BACKUP"
            self.timer_start = utime.ticks_ms()
            self.pubsub.publish("car/cmd", {"dir": "bwd", "speed": BACKUP_SPEED})
            print(f"[AUTO] Retrocediendo {BACKUP_MS} ms")
        else:
            self.state = "ARM_DOWN"
            self.timer_start = utime.ticks_ms()
            self.pubsub.publish("arm/cmd", {"action": "abajo"})
            print("[AUTO] Bajando brazo...")

# ========== CONEXIÓN WiFi ==========
def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    for _ in range(150):
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            print(f"[WiFi] Conectado, IP: {ip}")
            return True
        utime.sleep_ms(100)
    return False

# ========== MAIN ==========
def main():
    if not connect_wifi(WIFI_SSID, WIFI_PASS):
        return
    sched = Scheduler()
    sock = SocketClient(BROKER_IP, BROKER_PORT, sched)
    if not sock.connect():
        print("[MAIN] Broker no conectado")
        return
    pubsub = Node(sock)
    car = CarTask(sched, pubsub)
    arm = ArmTask(sched, pubsub)
    camera = CameraTask(sched, pubsub)
    autonomy = AutonomyTask(sched, pubsub, car, arm, camera)
    print("[MAIN] Robot listo. Colócalo frente a las cajas. Esperará detección de colores.")
    sched.run()

if __name__ == "__main__":
    main()