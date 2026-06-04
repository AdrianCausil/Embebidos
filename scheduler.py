"""
scheduler.py — Planificador cooperativo por tiempo
Robot7 | Proyecto Final

Clases:
  Task       base para todas las tareas del sistema
  Scheduler  ejecuta tareas según su periodo y prioridad

Uso:
  class MiTarea(Task):
      def __init__(self, scheduler):
          super().__init__(scheduler, period_ms=500, priority=3)
      def update(self):
          print("corriendo")

  sched = Scheduler()
  tarea = MiTarea(sched)
  sched.run()

Prioridades usadas en el proyecto:
  1 → SocketClient   (TCP, máxima prioridad)
  2 → (libre)
  3 → ModeTask
  4 → DisplayTask
  5 → CarTask / ArmTask
  7 → CameraTask
  9 → BatteryTask / WatchdogTask
"""

import utime
import gc


class Task:
    """
    Tarea base. Subclasificar y sobreescribir update().

    period_ms : cada cuánto ms se llama update()
    priority  : menor número = se ejecuta primero en cada ciclo
    """
    def __init__(self, scheduler, period_ms, priority=5):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()
        scheduler.add(self)

    def update(self):
        pass


class Scheduler:
    """
    Planificador cooperativo (single-thread).

    REGLA IMPORTANTE:
    Las tareas no deben bloquear más de unos pocos ms,
    salvo CarTask y ArmTask que bloquean durante el movimiento
    — eso es intencional para no enviar comandos a medias.
    """
    def __init__(self):
        self.tasks    = []
        self._running = True

    def add(self, task):
        self.tasks.append(task)
        self.tasks.sort(key=lambda t: t.priority)

    def stop(self):
        self._running = False

    def run(self):
        print("[SCHED] Iniciando loop...")
        while self._running:
            now = utime.ticks_ms()
            for task in self.tasks:
                if utime.ticks_diff(now, task.next_run) >= 0:
                    try:
                        task.update()
                    except Exception as e:
                        print(f"[SCHED] Error en {task.__class__.__name__}: {e}")
                    task.next_run = utime.ticks_add(
                        utime.ticks_ms(), task.period
                    )
            gc.collect()
            utime.sleep_ms(1)