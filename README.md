================================================================================
                            ROBOT7 - README
          Sistema autónomo de detección de colores y manipulación
                Raspberry Pi Pico 2W + OV7670 + L298N
================================================================================

Autores:
  - Fabian Alexander García Téllez     (20211005138)
  - Adrian Elias Causil Villadiego     (20211005122)

================================================================================
1. DESCRIPCIÓN GENERAL
================================================================================

ROBOT7 es un vehículo autónomo capaz de:
  • Reconocer objetos de colores (rojo, verde, azul) mediante una cámara OV7670.
  • Acercarse a ellos, levantarlos con un brazo de 3 servos, girar 60°, depositarlos
    y finalmente volver a home.
  • Comunicarse con un broker en PC para monitorización y ajuste de parámetros.
  • Ejecutar toda la lógica en la propia Raspberry Pi Pico 2W usando MicroPython.

El sistema está dividido en tareas cooperativas (scheduler) que gestionan:
  - Cámara (cálculo de centroides RGB a 80x60)
  - Control de motores DC (L298N con PWM y corrección de trayectoria)
  - Movimiento suave del brazo (120 pasos con ease-in-out)
  - Sensor ultrasónico HC-SR04 (opcional)
  - Comunicación PubSub con el PC

================================================================================
2. HARDWARE Y CONEXIONES
================================================================================

Componentes principales:
  • 1 Raspberry Pi Pico 2W
  • 1 Cámara OV7670 (módulo sin FIFO)
  • 1 Puente H L298N (para 2 motores DC)
  • 3 Servomotores (brazo: base, hombro, codo)
  • 1 Sensor ultrasónico HC-SR04 (opcional)
  • Batería externa 7.2V-12V para motores y puente H
  • Fuente 5V/2A para servos (opcional)

┌─────────────────────────────────────────────────────────────────┐
│ PINES PICO │ CONEXIÓN                                            │
├────────────┼─────────────────────────────────────────────────────┤
│ GP0 - GP7  │ Datos D0-D7 de la cámara OV7670                    │
│ GP8        │ PCLK (pixel clock)                                  │
│ GP9        │ MCLK (master clock, PWM 16 MHz)                    │
│ GP12       │ HREF                                                │
│ GP13       │ VSYNC                                               │
│ GP14       │ RESET (cámara)                                      │
│ GP15       │ SHUTDOWN (cámara)                                   │
│ GP16       │ SDA (I2C0)                                          │
│ GP17       │ SCL (I2C0)                                          │
│ GP18       │ Servo BASE                                          │
│ GP19       │ Servo HOMBRO                                        │
│ GP20       │ Servo CODO                                          │
│ GP21,GP22  │ IN1, IN2 del L298N (motor A)                       │
│ GP26,GP27  │ IN3, IN4 del L298N (motor B)                       │
│ GP10       │ ENA (PWM velocidad motor A)                         │
│ GP11       │ ENB (PWM velocidad motor B)                         │
│ GP28       │ TRIG (HC-SR04) – opcional                           │
│ GP29       │ ECHO (HC-SR04) – con divisor 10k/20k               │
└────────────┴─────────────────────────────────────────────────────┘

Nota: El sensor HC-SR04 es opcional. En la versión final del código se ha
      desactivado su uso (retroceso después de soltar se eliminó).

================================================================================
3. SOFTWARE: ARCHIVOS DEL PROYECTO
================================================================================

Todos los archivos deben copiarse a la Raspberry Pi Pico (raíz o carpeta).

Archivo          | Función
-----------------|---------------------------------------------------------------
main.py          | Programa principal. Modo "Derecho": detecta colores,
                 |  baja brazo, avanza, sube, gira 60°, suelta y termina.
car.py           | Control de motores DC con corrección de factores.
arm.py           | Movimiento suave de 3 servos (cola de movimientos, ease-in-out).
camera.py        | Captura rápida (80x60) y cálculo de centroides RGB.
distance.py      | Sensor ultrasónico HC-SR04 (si se usa).
scheduler.py     | Planificador cooperativo (Task, Scheduler).
pubsub.py        | Cliente TCP PubSub (SocketClient) y nodo local.
ov7670.py        | Driver base de la cámara (PIO, DMA, registros básicos).
ov7670_wrapper.py| Configuración de registros (tamaño, RGB, test pattern).
broker.py        | Servidor en PC que maneja WebSocket (puerto 5052) y TCP (5051).

En la PC también se puede usar una página web (frontend.html) para monitorizar
los centroides y cambiar parámetros en caliente.

================================================================================
4. FLUJO DE FUNCIONAMIENTO
================================================================================

1. Al encender, la Pico se conecta al WiFi (SSID: A35deFabian, pass: FAGTAAAA)
   y al broker (IP 10.182.144.3, puerto 5051).

2. La tarea CameraTask captura frames a 80x60 y calcula continuamente los
   centroides (coordenada X) de rojo, verde y azul.

3. La AutonomyTask (en main.py) muestra los valores cada segundo en la consola.
   Permanece en estado "IDLE" hasta que los tres colores superan sus umbrales
   (por defecto: TH_RED=-10, TH_GREEN=20, TH_BLUE=-8).

4. Cuando se detectan los tres colores, se ejecuta la secuencia:

   [ARM_DOWN] → baja brazo (comando "abajo", espera 1.5 s)
   [FORWARD]  → avanza durante 1400 ms (velocidad 50)
   [ARM_UP]   → sube brazo (recoge la pieza, espera 1.5 s)
   [TURN]     → gira a la derecha durante 1700 ms (aproximadamente 90°, se puede
                ajustar a 60° cambiando TURN_90_MS por TURN_60_MS ≈ 1200 ms)
   [PAUSE]    → pausa de 1 segundo
   [DELIVER_DOWN] → baja brazo (suelta la pieza, espera 1.5 s)
   [FINAL_UP] → sube brazo a HOME y finaliza.

5. El carro se detiene y el brazo se queda en home. La secuencia se ejecuta una
   sola vez (para repetir hay que reiniciar la Pico).

================================================================================
5. PARÁMETROS AJUSTABLES (en main.py)
================================================================================

Variable            | Valor por defecto | Qué controla
--------------------|-------------------|---------------------------------------------
FORWARD_TIME_MS     | 1400              | Tiempo de avance después de bajar brazo (ms)
TURN_90_MS          | 1700              | Tiempo de giro para 90° (ajustar a 60°)
DELIVER_PAUSE_MS    | 1000              | Pausa tras el giro antes de soltar (ms)
ARM_DOWN_WAIT_SEC   | 1.5               | Duración del movimiento "abajo" (segundos)
ARM_UP_WAIT_SEC     | 1.5               | Duración del movimiento "arriba" (segundos)
TH_RED, TH_GREEN, TH_BLUE | -10, 20, -8   | Umbrales de centroides (píxeles)
MIN_CONSECUTIVE     | 2                 | Nº de detecciones seguidas para activarse

Puedes cambiar estos valores directamente en el código o enviarlos vía broker
(tópico "autonomy/config") si se implementa el manejador correspondiente.

================================================================================
6. CONTROL DE MOTORES Y CORRECCIÓN DE TRAYECTORIA
================================================================================

El archivo car.py aplica factores de corrección para que el robot avance recto:

   self.factor_der = 1.0   (motor derecho, ENA en GP10)
   self.factor_izq = 0.9   (motor izquierdo, ENB en GP11)

Si el robot se desvía a la izquierda (rueda derecha más rápida), reducir
factor_der o aumentar factor_izq. Si se desvía a la derecha, hacer lo inverso.

Para calibrar, ejecuta el script de prueba que avanza durante unos segundos
y ajusta iterativamente.

================================================================================
7. COMUNICACIÓN CON EL BROKER
================================================================================

En la PC:
  - Ejecutar `broker.py` (requiere Python 3.8+ y websockets: pip install websockets)
  - El broker abre dos puertos:
      * TCP 5051 para conexión con la Pico
      * WebSocket 5052 para la interfaz web

La Pico se conecta automáticamente al broker usando la IP configurada en main.py.

Tópicos utilizados (prefijo "UDFJC/emb1/robot11/"):
  - car/cmd        : enviar órdenes al carro
  - arm/cmd        : enviar órdenes al brazo (abajo, arriba, home)
  - camera/centroids: publica los centroides (si se usa camera_vision.py)
  - distance/data  : publica la distancia (si se usa sensor)
  - autonomy/state : estado de la autonomía (opcional)

Ejemplo de comando desde el broker (enviar vía WebSocket):
   {"action": "PUB", "topic": "UDFJC/emb1/robot11/arm/cmd", "data": {"action": "abajo"}}

================================================================================
8. CÓMO EJECUTAR
================================================================================

En la PC (broker):
  1. Abrir una terminal en la carpeta donde está broker.py.
  2. Ejecutar: python broker.py
  3. Anotar la IP que muestra (ej. 10.182.144.3). Esa IP debe coincidir con la
     constante BROKER_IP en main.py.

En la Raspberry Pi Pico (usando Thonny o ampy):
  1. Copiar todos los archivos .py a la placa.
  2. Editar main.py y ajustar WIFI_SSID, WIFI_PASS, BROKER_IP y BROKER_PORT.
  3. Guardar y ejecutar main.py.
  4. Observar la consola: se mostrarán los valores de los centroides cada segundo.
  5. Colocar el robot frente a tres objetos de colores (rojo, verde, azul) a unos
     20-30 cm de distancia. La secuencia comenzará automáticamente.

Para usar la interfaz web:
  - Abrir el archivo frontend.html (o vision.html) en un navegador.
  - Conectar al WebSocket del broker (ws://IP_BROKER:5052).
  - Verás los centroides en tiempo real y podrás cambiar parámetros.

================================================================================
9. POSIBLES PROBLEMAS Y SOLUCIONES
================================================================================

| Síntoma                         | Causa probable                     | Solución                                                        |
|---------------------------------|------------------------------------|-----------------------------------------------------------------|
| El carro no avanza              | Batería del L298N baja o jumpers   | Usar batería >7V; puentear ENA/ENB o ajustar PWM correctamente. |
|                                 | de ENA/ENB quitados                |                                                                 |
| La cámara no detecta colores    | Umbrales inadecuados o poca luz    | Modificar _TH en camera.py (r_min, g_max, etc.); añadir luz.    |
| El brazo se mueve bruscamente   | Alimentación insuficiente para     | Conectar servos a una fuente externa de 5V/2A (no a la Pico).   |
|                                 | los servos                         |                                                                 |
| Error "[Errno 113] EHOSTUNREACH"| IP del broker incorrecta o PC      | Verificar IP con ipconfig/ifconfig; asegurar que broker.py corre|
|                                 | no accesible                       | y que el firewall permite puerto 5051.                          |
| El robot no gira lo que debe    | Tiempo de giro mal calibrado       | Medir tiempo real para 90° a velocidad 50 y ajustar TURN_90_MS. |
| No se ve el vídeo en la web     | Se usa camera.py (sin vídeo)       | Para vídeo, utilizar camera_task.py y el frontend adecuado.     |
|                                 |                                    | Nota: camera.py es más rápido para detección.                   |

================================================================================
10. MEJORAS FUTURAS (sugerencias)
================================================================================

- Implementar modos Auto (gira buscando colores) y Manual (recogida por trigger)
  mediante un selector en la interfaz web.
- Añadir un botón de reinicio en la web para repetir la secuencia sin resetear.
- Utilizar el sensor ultrasónico para un acercamiento más preciso (avance hasta
  distancia objetivo).
- Guardar parámetros de calibración en una EEPROM/archivo para mantenerlos
  entre reinicios.
- Incorporar un segundo brazo o pinza más robusta.

================================================================================
11. CRÉDITOS Y AGRADECIMIENTOS
================================================================================

Este proyecto ha sido desarrollado íntegramente por:

   • Fabian Alexander García Téllez     (20211005138)
   • Adrian Elias Causil Villadiego     (20211005122)

Como trabajo final de la asignatura "Sistemas Embebidos" (Electrónica).

Agradecemos a los profesores por las herramientas y conocimientos proporcionados.

================================================================================
                             FIN DEL README
================================================================================
