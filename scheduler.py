"""
scheduler.py — Planificador cooperativo por tiempo
Robot11 | MicroPython - Raspberry Pi Pico 2W

Clases:
    Task       base para todas las tareas del sistema
    Scheduler  ejecuta tareas según su periodo y prioridad

Prioridades del proyecto:
    1  → SocketClient   (TCP, máxima prioridad)
    3  → ModeTask
    4  → DisplayTask    (OLED)
    5  → CarTask / ArmTask
    7  → CameraTask
    9  → BatteryTask / WatchdogTask
"""

import utime
import gc


# ─────────────────────────────────────────────────────────────
class Task:
    """
    Tarea base. Subclasificar y sobreescribir update().

    Parámetros:
        scheduler  : instancia de Scheduler donde se registra
        period_ms  : cada cuántos ms se llama update()
        priority   : menor número = se ejecuta primero
    """

    def __init__(self, scheduler, period_ms, priority=5):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        scheduler.add(self)

    def update(self):
        """Sobreescribir en subclase. No debe bloquear más de ~5 ms."""
        pass


# ─────────────────────────────────────────────────────────────
class Scheduler:
    """
    Planificador cooperativo (single-thread, sin RTOS).

    Regla: ningún update() debe bloquear el hilo salvo que sea
    intencional (ej. movimiento de motores paso a paso).
    """

    def __init__(self):
        self._tasks   = []
        self._running = False

    # ── Gestión de tareas ─────────────────────────────────────

    def add(self, task):
        """Agrega una tarea y reordena por prioridad."""
        self._tasks.append(task)
        self._tasks.sort(key=lambda t: t.priority)

    def remove(self, task):
        """Elimina una tarea del loop."""
        if task in self._tasks:
            self._tasks.remove(task)

    def stop(self):
        """Detiene el loop en la próxima iteración."""
        self._running = False

    # ── Loop principal ────────────────────────────────────────

    def run(self):
        """Inicia el loop cooperativo. Bloquea hasta stop()."""
        self._running = True
        print("[SCHED] Iniciando loop...")

        while self._running:
            now = utime.ticks_ms()

            for task in self._tasks:
                if utime.ticks_diff(now, task.next_run) >= 0:
                    try:
                        task.update()
                    except Exception as e:
                        print(f"[SCHED] Error en {task.__class__.__name__}: {e}")
                    # Reprogramar desde el momento real de ejecución
                    task.next_run = utime.ticks_add(utime.ticks_ms(), task.period)

            gc.collect()
            utime.sleep_ms(1)

        print("[SCHED] Loop detenido.")
