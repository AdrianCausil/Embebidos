"""
car.py — Control de motores del carrito
Robot7 |

Clase: CarTask
Hereda de Task (scheduler.py)

Pines:
  GP16 → IN1  (motor derecho, dirección A)
  GP17 → IN2  (motor derecho, dirección B)
  GP18 → IN3  (motor izquierdo, dirección A)
  GP19 → IN4  (motor izquierdo, dirección B)
  GP20 → ENA  (PWM velocidad derecho)
  GP21 → ENB  (PWM velocidad izquierdo)

Topics suscritos:
  car/cmd  → {action: "recta"|"izquierda"|"derecha"|"stop", dm: N}

Topics publicados:
  car/state → {state: "recta"|"izquierda"|"derecha"|"idle", dm: N}

Calibración:
  TIEMPO_DM            segundos por decímetro en línea recta
  TIEMPO_GIRO_90       segundos para girar 90° sobre el eje
  VEL_DEFAULT          duty_u16 (0–65535), ~40% = 26214
  CORRECCION_DER/IZQ   ajuste fino si el carro no va recto
"""

from machine import Pin, PWM
import utime


# ─────────────────────────────────────────────────────────────
#  Constantes de pines (espejo del pin map global)
# ─────────────────────────────────────────────────────────────
_IN1 = 16
_IN2 = 17
_IN3 = 18
_IN4 = 19
_ENA = 20
_ENB = 21


class CarTask:
    """
    Controla los dos motores del carrito mediante un L298N.

    En el proyecto final se instancia con scheduler y pubsub.
    Para pruebas individuales se puede instanciar sin argumentos:

        car = CarTask()
        car.adelante(5)
    """

    # ── Parámetros de calibración ────────────────────────────
    TIEMPO_DM      = 1.1      # s / dm en línea recta  ← CALIBRAR
    TIEMPO_GIRO_90 = 1.0      # s para giro 90°        ← CALIBRAR
    VEL_DEFAULT    = 26214    # duty_u16 (~40%)
    ANCHO_RUEDAS   = 0.14     # metros, distancia entre ruedas
    CORRECCION_DER = 1.00     # si desvía a la derecha bajar a 0.97
    CORRECCION_IZQ = 0.98     # si desvía a la izquierda bajar a 0.97

    def __init__(self, scheduler=None, pubsub=None, period_ms=50, priority=5):
        # Scheduler / PubSub son opcionales para poder probar sin ellos
        self._scheduler = scheduler
        self._pubsub    = pubsub
        self.period     = period_ms
        self.priority   = priority
        self.next_run   = utime.ticks_ms()

        self._state     = "idle"
        self._queue     = []

        # ── Pines de dirección ───────────────────────────────
        self._in1 = Pin(_IN1, Pin.OUT)
        self._in2 = Pin(_IN2, Pin.OUT)
        self._in3 = Pin(_IN3, Pin.OUT)
        self._in4 = Pin(_IN4, Pin.OUT)

        # ── PWM de velocidad ─────────────────────────────────
        self._ena = PWM(Pin(_ENA))
        self._enb = PWM(Pin(_ENB))
        self._ena.freq(1000)
        self._enb.freq(1000)

        self.parar()

        # ── Suscripciones PubSub ─────────────────────────────
        if pubsub:
            pubsub.subscribe("car/cmd",     self._on_cmd)
            pubsub.subscribe("system/mode", self._on_mode)

        # ── Registro en scheduler ────────────────────────────
        if scheduler:
            scheduler.add(self)

        self._mode_activo = True   # True cuando mode == "carrito"

    # ══════════════════════════════════════════════════════════
    #  Callbacks PubSub
    # ══════════════════════════════════════════════════════════

    def _on_mode(self, data):
        self._mode_activo = (data.get("mode") == "carrito")

    def _on_cmd(self, data):
        """Encola un comando recibido por PubSub."""
        self._queue.append(data)

    # ══════════════════════════════════════════════════════════
    #  API pública (usable también sin PubSub)
    # ══════════════════════════════════════════════════════════

    def adelante(self, dm, velocidad=None):
        """Avanza dm decímetros en línea recta."""
        v = velocidad or self.VEL_DEFAULT
        t = dm * self.TIEMPO_DM
        print(f"[CAR] adelante {dm} dm  ({t:.2f} s)")
        self._publicar("recta", dm)
        self._der_adelante(int(v * self.CORRECCION_DER))
        self._izq_adelante(int(v * self.CORRECCION_IZQ))
        utime.sleep(t)
        self.parar()

    def atras(self, dm, velocidad=None):
        """Retrocede dm decímetros."""
        v = velocidad or self.VEL_DEFAULT
        t = dm * self.TIEMPO_DM
        print(f"[CAR] atras {dm} dm  ({t:.2f} s)")
        self._publicar("atras", dm)
        self._der_atras(int(v * self.CORRECCION_DER))
        self._izq_atras(int(v * self.CORRECCION_IZQ))
        utime.sleep(t)
        self.parar()

    def girar_derecha(self, grados=90, velocidad=None):
        """Giro sobre el eje hacia la derecha."""
        v = velocidad or self.VEL_DEFAULT
        t = self.TIEMPO_GIRO_90 * (grados / 90)
        print(f"[CAR] giro derecha {grados}°  ({t:.2f} s)")
        self._publicar("derecha", grados)
        self._der_atras(int(v * self.CORRECCION_DER))
        self._izq_adelante(int(v * self.CORRECCION_IZQ))
        utime.sleep(t)
        self.parar()

    def girar_izquierda(self, grados=90, velocidad=None):
        """Giro sobre el eje hacia la izquierda."""
        v = velocidad or self.VEL_DEFAULT
        t = self.TIEMPO_GIRO_90 * (grados / 90)
        print(f"[CAR] giro izquierda {grados}°  ({t:.2f} s)")
        self._publicar("izquierda", grados)
        self._der_adelante(int(v * self.CORRECCION_DER))
        self._izq_atras(int(v * self.CORRECCION_IZQ))
        utime.sleep(t)
        self.parar()

    def circulo_izquierda(self, radio_dm, velocidad=None):
        """Arco de círculo hacia la izquierda con radio dado en dm."""
        v   = velocidad or self.VEL_DEFAULT
        r   = radio_dm * 2.5
        r_e = r + (self.ANCHO_RUEDAS * 10) / 2
        r_i = r - (self.ANCHO_RUEDAS * 10) / 2
        t   = ((3.1416 / 2) * r_e / 4) * self.TIEMPO_DM
        print(f"[CAR] círculo izq. radio={radio_dm} dm  ({t:.2f} s)")
        self._publicar("izquierda", radio_dm)
        self._izq_adelante(max(int(v * self.CORRECCION_IZQ * r_i / r_e), 0))
        self._der_adelante(int(v * self.CORRECCION_DER * 1.05))
        utime.sleep(t)
        self.parar()

    def circulo_derecha(self, radio_dm, velocidad=None):
        """Arco de círculo hacia la derecha con radio dado en dm."""
        v   = velocidad or self.VEL_DEFAULT
        r   = radio_dm * 2.3
        r_e = r + (self.ANCHO_RUEDAS * 10) / 2
        r_i = r - (self.ANCHO_RUEDAS * 10) / 2
        t   = ((3.1416 / 2) * r_e / 4) * self.TIEMPO_DM
        print(f"[CAR] círculo der. radio={radio_dm} dm  ({t:.2f} s)")
        self._publicar("derecha", radio_dm)
        self._izq_adelante(int(v * self.CORRECCION_IZQ * 1.05))
        self._der_adelante(max(int(v * self.CORRECCION_DER * r_i / r_e), 0))
        utime.sleep(t)
        self.parar()

    def parar(self):
        """Detiene ambos motores."""
        self._in1.low(); self._in2.low(); self._ena.duty_u16(0)
        self._in3.low(); self._in4.low(); self._enb.duty_u16(0)
        self._state = "idle"
        self._publicar("idle")

    # ══════════════════════════════════════════════════════════
    #  update() — llamado por el Scheduler
    # ══════════════════════════════════════════════════════════

    def update(self):
        """Procesa el siguiente comando de la cola si el carro está libre."""
        if self._queue and self._state == "idle":
            cmd    = self._queue.pop(0)
            action = cmd.get("action", "")
            dm     = int(cmd.get("dm", 5))

            if action == "recta":
                self._state = "recta"
                self.adelante(dm)
            elif action == "izquierda":
                self._state = "izquierda"
                self.circulo_izquierda(dm)
            elif action == "derecha":
                self._state = "derecha"
                self.circulo_derecha(dm)
            elif action == "stop":
                self.parar()

    # ══════════════════════════════════════════════════════════
    #  Control de motores (privado)
    # ══════════════════════════════════════════════════════════

    def _der_adelante(self, v):
        self._in1.high(); self._in2.low();  self._ena.duty_u16(v)

    def _der_atras(self, v):
        self._in1.low();  self._in2.high(); self._ena.duty_u16(v)

    def _izq_adelante(self, v):
        self._in3.high(); self._in4.low();  self._enb.duty_u16(v)

    def _izq_atras(self, v):
        self._in3.low();  self._in4.high(); self._enb.duty_u16(v)

    # ══════════════════════════════════════════════════════════
    #  PubSub (privado)
    # ══════════════════════════════════════════════════════════

    def _publicar(self, state, dm=0):
        self._state = state
        if self._pubsub:
            self._pubsub.publish("car/state", {"state": state, "dm": dm})