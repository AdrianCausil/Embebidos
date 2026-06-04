"""
test_01_motors.py — Prueba de motores sin WiFi ni PubSub
Robot7 | Paso 1

Qué hace:
  1. Avanza 3 s
  2. Para 1 s
  3. Gira derecha 90°
  4. Para 1 s
  5. Gira izquierda 90°
  6. Para 1 s
  7. Retrocede 3 s
  8. Para

Qué observar:
  - ¿El carro avanza recto? Si no, ajustar CORRECCION_DER / CORRECCION_IZQ en car.py
  - ¿Los giros son de 90°? Si no, ajustar TIEMPO_GIRO_90 en car.py
  - ¿La velocidad es razonable? Si va muy lento subir VEL_DEFAULT, muy rápido bajar

Si los motores van al revés:
  - Intercambiar los cables del motor físicamente en el L298N, O
  - Intercambiar _in1/_in2 (o _in3/_in4) en car.py

Cómo correr:
  Copiar car.py y test_01_motors.py al Pico.
  Abrir Thonny, abrir test_01_motors.py, presionar Run (F5).
"""

from car import CarTask
from time import sleep

print("=" * 40)
print("TEST 01 — Motores")
print("Conecta: GP16-GP21 → L298N")
print("=" * 40)
sleep(2)   # pausa para colocar el carro en el suelo

car = CarTask()   # sin scheduler ni pubsub

# ── 1. Adelante ──────────────────────────────────────────────
#print("\n[1/7] Adelante 3 s...")
#car.adelante(3)   # 3 dm ≈ 30 cm con calibración por defecto
#sleep(1)

# ── 2. Giro derecha 90° ──────────────────────────────────────
print("[2/7] Giro derecha 90°...")
car.girar_derecha(90)
sleep(1)

# ── 3. Adelante de nuevo ─────────────────────────────────────
#print("[3/7] Adelante 3 s...")
#car.adelante(3)
#sleep(1)

# ── 4. Giro izquierda 90° ────────────────────────────────────
print("[4/7] Giro izquierda 90°...")
car.girar_izquierda(90)
sleep(1)

# ── 5. Circulo izquierda ─────────────────────────────────────
#print("[5/7] Círculo izquierda radio=3 dm...")
car.circulo_izquierda(3)
sleep(1)

# ── 6. Circulo derecha ───────────────────────────────────────
#print("[6/7] Círculo derecha radio=3 dm...")
#car.circulo_derecha(3)
#sleep(1)

# ── 7. Atras ─────────────────────────────────────────────────
print("[7/7] Atras 3 s...")
car.atras(3)
sleep(1)

# ── Fin ──────────────────────────────────────────────────────
car.parar()
print("\n[OK] Test 01 completo.")
print("Ajusta en car.py:")
print("  TIEMPO_DM      si la distancia no es correcta")
print("  TIEMPO_GIRO_90 si los giros no son de 90 grados")
print("  CORRECCION_DER/IZQ si el carro no va recto")