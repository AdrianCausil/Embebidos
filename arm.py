"""
arm.py — Brazo meArm con Cinemática Inversa
Robot7 | Proyecto Final

Clase: ArmTask

Pines:
  GP22 → Servo base    (giro horizontal, 0°=izq, 90°=frente, 180°=der)
  GP26 → Servo hombro  (plano vertical,  0°=abajo, 90°=horizontal)
  GP27 → Servo codo    (plano vertical,  0°=extendido, 90°=doblado)

Geometría meArm estándar:
  L1 = 80 mm  (brazo superior, hombro→codo)
  L2 = 80 mm  (antebrazo,     codo→gripper)

  Origen del sistema de coordenadas: eje del servo hombro
  X → hacia adelante (frente del robot)
  Y → hacia la izquierda
  Z → hacia arriba

Cinemática inversa — plano vertical (X-Z):
  r   = sqrt(x² + z²)              distancia horizontal al objetivo
  cos_codo = (r² - L1² - L2²) / (2·L1·L2)
  θ_codo   = acos(cos_codo)        en radianes
  θ_hombro = atan2(z, x) - atan2(L2·sin(θ_codo), L1 + L2·cos(θ_codo))

  Luego base = atan2(y, x) convertido a grados

Convención de ángulos servo:
  hombro_servo = 90 - θ_hombro_grados  (90° = horizontal)
  codo_servo   = θ_codo_grados          (0° = extendido, 90° = tope)

Topics suscritos:
  arm/cmd → {action: "move", x, y, z}   mover a posición en mm
            {action: "home"}             posición de reposo
            {action: "angles", base, shoulder, elbow}  ángulos directos

Topics publicados:
  arm/state → {state, x, y, z, angles: {base, shoulder, elbow}}
"""

from machine import Pin, PWM
import utime
import math


# ─────────────────────────────────────────────────────────────
#  Pines
# ─────────────────────────────────────────────────────────────
_SV_BASE   = 22
_SV_HOMBRO = 26
_SV_CODO   = 27

# ─────────────────────────────────────────────────────────────
#  Geometría
# ─────────────────────────────────────────────────────────────
L1 = 80.0   # mm — brazo superior
L2 = 80.0   # mm — antebrazo

# Posición HOME (ángulos servo en grados)
HOME_BASE   = 90
HOME_HOMBRO = 90    # horizontal
HOME_CODO   = 45    # ligeramente doblado

# Límites físicos de cada servo (grados)
BASE_MIN   = 0;   BASE_MAX   = 180
HOMBRO_MIN = 30;  HOMBRO_MAX = 150
CODO_MIN   = 0;   CODO_MAX   = 90


class ArmTask:
    """
    Controla el brazo meArm con cinemática inversa.

    Uso sin PubSub (prueba):
        arm = ArmTask()
        arm.home()
        arm.mover_a(80, 0, 40)   # x=80mm, y=0, z=40mm

    Uso con PubSub (main.py):
        arm = ArmTask(scheduler=sched, pubsub=node)
    """

    def __init__(self, scheduler=None, pubsub=None,
                 period_ms=50, priority=5):
        self.period   = period_ms
        self.priority = priority
        self.next_run = utime.ticks_ms()

        self._state   = "idle"
        self._queue   = []
        self._pubsub  = pubsub
        self._mode_ok = False   # True cuando mode == "brazo"

        # Posición actual en mm y ángulos
        self._x = 0.0
        self._y = 0.0
        self._z = 0.0
        self._angulos = {
            "base":     float(HOME_BASE),
            "shoulder": float(HOME_HOMBRO),
            "elbow":    float(HOME_CODO),
        }

        # Inicializar servos
        self._sv_base   = PWM(Pin(_SV_BASE));   self._sv_base.freq(50)
        self._sv_hombro = PWM(Pin(_SV_HOMBRO)); self._sv_hombro.freq(50)
        self._sv_codo   = PWM(Pin(_SV_CODO));   self._sv_codo.freq(50)

        # Ir a HOME al iniciar
        self._escribir(HOME_BASE, HOME_HOMBRO, HOME_CODO)
        utime.sleep(1)

        # Suscripciones PubSub
        if pubsub:
            pubsub.subscribe("arm/cmd",     self._on_cmd)
            pubsub.subscribe("system/mode", self._on_mode)

        # Registro en scheduler
        if scheduler:
            scheduler.add(self)

    # ══════════════════════════════════════════════════════════
    #  Callbacks PubSub
    # ══════════════════════════════════════════════════════════

    def _on_mode(self, data):
        self._mode_ok = (data.get("mode") == "brazo")

    def _on_cmd(self, data):
        self._queue.append(data)

    # ══════════════════════════════════════════════════════════
    #  API pública
    # ══════════════════════════════════════════════════════════

    def home(self):
        """Mueve el brazo a la posición de reposo."""
        print("[ARM] → HOME")
        self._interpolar(HOME_BASE, HOME_HOMBRO, HOME_CODO, t=0.8)
        self._publicar("idle")

    def mover_a(self, x, y, z, t=0.8):
        """
        Mueve el gripper a la posición (x, y, z) en mm.

        x → hacia adelante desde el hombro
        y → lateral (positivo = izquierda)
        z → altura (positivo = arriba)

        Retorna True si el punto es alcanzable, False si no.
        """
        resultado = self._ik(x, y, z)
        if resultado is None:
            print(f"[ARM] Punto ({x},{y},{z}) fuera de alcance")
            self._publicar("error")
            return False

        base, hombro, codo = resultado
        print(f"[ARM] → ({x},{y},{z})mm  base={base:.1f} hombro={hombro:.1f} codo={codo:.1f}")
        self._x = x; self._y = y; self._z = z
        self._interpolar(base, hombro, codo, t)
        self._publicar("idle")
        return True

    def set_angles(self, base, hombro, codo, t=0.5):
        """
        Mueve directamente a ángulos servo dados.
        Útil para calibración o control manual desde el frontend.
        """
        base   = self._clamp(base,   BASE_MIN,   BASE_MAX)
        hombro = self._clamp(hombro, HOMBRO_MIN, HOMBRO_MAX)
        codo   = self._clamp(codo,   CODO_MIN,   CODO_MAX)
        print(f"[ARM] ángulos directos: base={base} hombro={hombro} codo={codo}")
        self._interpolar(base, hombro, codo, t)
        self._publicar("idle")

    # ══════════════════════════════════════════════════════════
    #  Cinemática Inversa
    # ══════════════════════════════════════════════════════════

    def _ik(self, x, y, z):
        """
        Calcula los ángulos servo para alcanzar (x, y, z) en mm.
        Retorna (base_deg, hombro_deg, codo_deg) o None si no es alcanzable.

        Pasos:
          1. Base: atan2(y, x) — giro horizontal
          2. Proyección en plano vertical: r = sqrt(x²+y²), altura = z
          3. IK de 2 eslabones en plano (r, z):
             cos_codo = (r² + z² - L1² - L2²) / (2·L1·L2)
             θ_codo   = acos(cos_codo)
             θ_hombro = atan2(z, r) - atan2(L2·sin(θc), L1+L2·cos(θc))
          4. Convertir a ángulos servo según convención física
        """
        # ── Base ───────────────────────────────────────────────
        base_rad  = math.atan2(y, x)
        base_deg  = 90 - math.degrees(base_rad)   # 90°=frente
        base_deg  = self._clamp(base_deg, BASE_MIN, BASE_MAX)

        # ── Distancia horizontal al objetivo ───────────────────
        r = math.sqrt(x * x + y * y)

        # ── Verificar alcance ──────────────────────────────────
        dist = math.sqrt(r * r + z * z)
        if dist > (L1 + L2) - 2 or dist < 10:
            return None   # fuera de alcance

        # ── Ángulo codo (solución codo arriba) ─────────────────
        cos_codo = (r * r + z * z - L1 * L1 - L2 * L2) / (2 * L1 * L2)
        cos_codo = self._clamp(cos_codo, -1.0, 1.0)   # evitar dominio acos
        theta_codo = math.acos(cos_codo)               # radianes

        # ── Ángulo hombro ──────────────────────────────────────
        theta_hombro = (
            math.atan2(z, r)
            - math.atan2(L2 * math.sin(theta_codo),
                         L1 + L2 * math.cos(theta_codo))
        )

        # ── Convertir a grados servo ───────────────────────────
        # Hombro: 90° servo = 0 rad (horizontal)
        #         servo aumenta cuando el brazo sube
        hombro_deg = 90 - math.degrees(theta_hombro)

        # Codo: 0° servo = extendido (theta_codo=0)
        #       90° servo = doblado al tope (theta_codo=pi/2)
        codo_deg = math.degrees(theta_codo)

        # Debug
        print(f"[IK] dist={dist:.1f} hombro={hombro_deg:.1f} codo={codo_deg:.1f}")

        # Verificar limites fisicos
        if not (HOMBRO_MIN <= hombro_deg <= HOMBRO_MAX):
            return None
        if not (CODO_MIN <= codo_deg <= CODO_MAX):
            return None

        # Clamp final
        hombro_deg = self._clamp(hombro_deg, HOMBRO_MIN, HOMBRO_MAX)
        codo_deg   = self._clamp(codo_deg,   CODO_MIN,   CODO_MAX)

        return base_deg, hombro_deg, codo_deg

    # ══════════════════════════════════════════════════════════
    #  Control de servos
    # ══════════════════════════════════════════════════════════

    def _duty(self, ang):
        """Convierte ángulo (0°–180°) a duty_u16 para SG90."""
        ang = max(0.0, min(180.0, float(ang)))
        return int(2500 + (ang / 180.0) * 4750)

    def _escribir(self, base, hombro, codo):
        """Escribe ángulos directamente en los servos."""
        self._sv_base.duty_u16(self._duty(base))
        self._sv_hombro.duty_u16(self._duty(hombro))
        self._sv_codo.duty_u16(self._duty(codo))
        self._angulos = {
            "base":     round(float(base),   1),
            "shoulder": round(float(hombro), 1),
            "elbow":    round(float(codo),   1),
        }

    def _interpolar(self, base_t, hombro_t, codo_t, t=1.0):
        """
        Interpolación lineal suave entre la posición actual y el objetivo.
        t = tiempo total en segundos.
        N_PASOS determina la fluidez del movimiento.
        """
        N_PASOS = 20
        delay   = int(t * 1000 / N_PASOS)

        b0 = self._angulos["base"]
        h0 = self._angulos["shoulder"]
        c0 = self._angulos["elbow"]

        for i in range(1, N_PASOS + 1):
            k = i / N_PASOS
            self._escribir(
                b0 + (base_t   - b0) * k,
                h0 + (hombro_t - h0) * k,
                c0 + (codo_t   - c0) * k,
            )
            utime.sleep_ms(delay)

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    # ══════════════════════════════════════════════════════════
    #  PubSub
    # ══════════════════════════════════════════════════════════

    def _publicar(self, state):
        self._state = state
        if self._pubsub:
            self._pubsub.publish("arm/state", {
                "state":  state,
                "x":      self._x,
                "y":      self._y,
                "z":      self._z,
                "angles": self._angulos,
            })

    # ══════════════════════════════════════════════════════════
    #  update() — llamado por el Scheduler
    # ══════════════════════════════════════════════════════════

    def update(self):
        if not self._queue or self._state != "idle":
            return

        cmd    = self._queue.pop(0)
        action = cmd.get("action", "")
        self._state = "moving"

        if action == "home":
            self.home()

        elif action == "move":
            x = float(cmd.get("x", 80))
            y = float(cmd.get("y", 0))
            z = float(cmd.get("z", 40))
            self.mover_a(x, y, z)

        elif action == "angles":
            self.set_angles(
                cmd.get("base",     HOME_BASE),
                cmd.get("shoulder", HOME_HOMBRO),
                cmd.get("elbow",    HOME_CODO),
            )

        else:
            print(f"[ARM] Acción desconocida: {action}")
            self._state = "idle"