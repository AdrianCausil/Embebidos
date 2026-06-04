"""
test_05_battery.py -- Prueba de bateria 12V
Robot7 | Paso 5

Hardware necesario:
  R1 = 75kohm  entre bateria (+) y GP28
  R2 = 20kohm  entre GP28 y GND
  GP28 -> ADC2

Pasos de calibracion:
  1. Correr este script con la bateria conectada
  2. Medir voltaje real con multimetro en los bornes de la bateria
  3. Calcular: FACTOR = voltaje_multimetro / voltaje_raw_pico
  4. Actualizar VOLTAGE_DROP_FACTOR en battery.py
"""

from battery import BatteryTask, VOLTAGE_DROP_FACTOR
from machine import ADC, Pin
from time import sleep

print("=" * 40)
print("TEST 05 -- Bateria 12V")
print(f"GP28 = ADC2 | Factor actual: {VOLTAGE_DROP_FACTOR}")
print("=" * 40)

# Lectura RAW para calibracion
adc = ADC(Pin(28))
print("\n--- Lectura RAW (para calcular tu factor) ---")
for i in range(5):
    raw   = adc.read_u16()
    v_pin = raw * 3.3 / 65535
    print(f"  v_pin={v_pin:.3f}V  raw={raw}")
    sleep(0.5)

print(f"\n  Si tu multimetro marca 12.0V y v_pin=2.625V")
print(f"  entonces FACTOR = 12.0 / 2.625 = 4.571")

print("\n--- Lectura con factor actual ---")
bat = BatteryTask()
for i in range(8):
    pct, v = bat.read()
    bar = "#" * (pct // 10) + "-" * (10 - pct // 10)
    print(f"  [{bar}] {pct:3d}%  {v:.2f}V")
    sleep(1)

print("\n[OK] Test 05 completo.")
print("Ajusta VOLTAGE_DROP_FACTOR en battery.py si el voltaje no coincide.")