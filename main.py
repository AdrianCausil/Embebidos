# main.py — Batería + Sonar HC-SR04 + servidor web
# Pico 2W  +  OLED 1.3" SH1106 I2C (128x64)
# Red: iPhone | IP Pico: 172.20.10.13

import network, socket, time, machine, json
from machine import Pin, time_pulse_us
from sh1106 import SH1106

# ──────────────────────────────────────────────
WIFI_SSID = "iPhone"
WIFI_PASS = "aecv1234"

# ──────────────────────────────────────────────
#  Hardware
# ──────────────────────────────────────────────
i2c  = machine.I2C(1, scl=machine.Pin(3), sda=machine.Pin(2), freq=400000)
oled = SH1106(i2c, addr=0x3C)
adc  = machine.ADC(machine.Pin(26))

# Sonar — GP4=TRIG, GP5=ECHO
TRIG = Pin(4, Pin.OUT)
ECHO = Pin(5, Pin.IN)
TRIG.low()

# Divisor de voltaje: 3 resistencias de 100k
# R1+R2=200k arriba, R3=100k abajo → factor=3.0
FACTOR       = 3.0
V_MAX, V_MIN = 8.40, 6.00

# ──────────────────────────────────────────────
#  Estado global
# ──────────────────────────────────────────────
intervalo  = 2
ultimo_v   = 0.0
ultimo_pct = 0.0
ultimo_cm  = -1

# ──────────────────────────────────────────────
#  Medición batería
# ──────────────────────────────────────────────
def leer_voltaje(muestras=20):
    total = sum(adc.read_u16() for _ in range(muestras))
    v_adc = (total / muestras) * 3.3 / 65535
    return round(v_adc * FACTOR, 2)

def calcular_pct(v):
    return max(0.0, min(100.0, ((v - V_MIN) / (V_MAX - V_MIN)) * 100))

# ──────────────────────────────────────────────
#  Medición sonar
# ──────────────────────────────────────────────
def leer_sonar():
    TRIG.low()
    time.sleep_us(2)
    TRIG.high()
    time.sleep_us(10)
    TRIG.low()
    duracion = time_pulse_us(ECHO, 1, 25000)
    if duracion < 0:
        return -1
    cm = round((duracion * 0.0343) / 2.0, 1)
    if cm < 2 or cm > 400:
        return -1
    return cm

# ──────────────────────────────────────────────
#  OLED
# ──────────────────────────────────────────────
def oled_msg(l1, l2=""):
    oled.fill(0)
    oled.text(l1[:16], 0, 10, 1)
    if l2:
        oled.text(l2[:16], 0, 30, 1)
    oled.show()

def dibujar(v, pct, cm):
    oled.fill(0)
    oled.text("ROBOT11", 0, 0, 1)
    oled.hline(0, 10, 128, 1)
    oled.text("{:.2f}V {:3.0f}%".format(v, pct), 0, 14, 1)
    # Barra batería
    BW = 100
    oled.rect(0, 26, BW, 10, 1)
    fw = int((BW - 2) * pct / 100)
    if fw > 0:
        oled.fill_rect(1, 27, fw, 8, 1)
    oled.hline(0, 40, 128, 1)
    if cm > 0:
        oled.text("Dist:{:.1f}cm".format(cm), 0, 44, 1)
    else:
        oled.text("Dist: -- cm", 0, 44, 1)
    oled.show()

# ──────────────────────────────────────────────
#  WiFi
# ──────────────────────────────────────────────
def conectar_wifi():
    oled_msg("Conectando...", WIFI_SSID)
    w = network.WLAN(network.STA_IF)
    w.active(True)
    w.connect(WIFI_SSID, WIFI_PASS)
    for i in range(30):
        if w.isconnected():
            ip = w.ifconfig()[0]
            oled_msg("WiFi OK", ip)
            print("IP:", ip)
            time.sleep(2)
            return ip
        time.sleep(0.5)
    oled_msg("WiFi FALLO")
    print("WiFi no conectó")
    return "sin-wifi"

# ──────────────────────────────────────────────
#  HTML
# ──────────────────────────────────────────────
HTML = b"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="0">
  <title>Robot11 Sensores</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:Arial,sans-serif;background:#1a1a2e;color:#eee;
         display:flex;flex-direction:column;align-items:center;
         justify-content:center;min-height:100vh;padding:20px}
    .card{background:#16213e;border-radius:16px;padding:30px;
          width:100%;max-width:400px;box-shadow:0 4px 20px #0005}
    h1{text-align:center;margin-bottom:24px;font-size:1.3rem;color:#a0c4ff}
    .sec{margin-bottom:20px}
    .sec-title{color:#a0c4ff;font-size:.8rem;letter-spacing:2px;
               text-transform:uppercase;margin-bottom:10px;
               border-bottom:1px solid #333;padding-bottom:4px}
    .dato{display:flex;justify-content:space-between;
          align-items:center;margin-bottom:8px}
    .label{color:#aaa;font-size:.9rem}
    .valor{font-size:1.8rem;font-weight:bold;color:#fff}
    .barra-bg{background:#333;border-radius:8px;
              height:24px;overflow:hidden;margin:8px 0}
    .barra-fill{height:100%;border-radius:8px;
                transition:width .6s,background .6s;width:0%}
    .estado{text-align:center;font-size:1rem;
            font-weight:bold;margin-top:4px}
    .sonar-val{font-size:2.8rem;font-weight:bold;
               text-align:center;color:#00e676;margin:8px 0}
    .sonar-bg{background:#333;border-radius:8px;
              height:14px;overflow:hidden;margin:6px 0}
    .sonar-fill{height:100%;border-radius:8px;
                background:#00e676;transition:width .4s;width:0%}
    hr{border:none;border-top:1px solid #333;margin:16px 0}
    .form-row{display:flex;gap:10px;align-items:center;
              flex-wrap:wrap;justify-content:center}
    .form-row label{color:#aaa;font-size:.9rem}
    input[type=number]{background:#0f3460;color:#fff;
                       border:1px solid #444;border-radius:8px;
                       padding:8px;width:70px;font-size:1rem}
    button{background:#4361ee;color:#fff;border:none;
           border-radius:8px;padding:9px 18px;
           cursor:pointer;font-size:1rem}
    button:hover{background:#3a0ca3}
    .pie{text-align:center;font-size:.75rem;color:#555;margin-top:14px}
    .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
         background:#4caf50;margin-right:6px;vertical-align:middle;
         animation:pulso 1.5s infinite}
    @keyframes pulso{0%,100%{opacity:1}50%{opacity:.3}}
    .dot.err{background:#f44336;animation:none}
  </style>
</head>
<body>
<div class="card">
  <h1>&#9889; Robot11 &mdash; Sensores</h1>

  <div class="sec">
    <div class="sec-title">Bateria 2S Li-Ion</div>
    <div class="dato">
      <span class="label">Voltaje</span>
      <span class="valor" id="v">--</span>
    </div>
    <div class="dato">
      <span class="label">Nivel</span>
      <span class="valor" id="pct">--</span>
    </div>
    <div class="barra-bg">
      <div class="barra-fill" id="barra"></div>
    </div>
    <div class="estado" id="bat-estado">Cargando...</div>
  </div>

  <hr>

  <div class="sec">
    <div class="sec-title">Sonar HC-SR04</div>
    <div class="sonar-val" id="cm">-- cm</div>
    <div class="sonar-bg">
      <div class="sonar-fill" id="sonar-barra"></div>
    </div>
    <div class="estado" id="sonar-estado" style="color:#00e676">--</div>
  </div>

  <hr>

  <div class="form-row">
    <label>Actualizar cada</label>
    <input type="number" id="seg" value="2" min="1" max="60">
    <label>seg</label>
    <button onclick="setInt()">Aplicar</button>
  </div>

  <p class="pie">
    <span class="dot" id="dot"></span>
    <span id="pie">Conectando...</span>
  </p>
</div>

<script>
var seg=2, timer=null;

function cBat(p){return p>=60?'#4caf50':p>=30?'#ff9800':'#f44336';}
function eBat(p){return p>=75?'Llena \u2714':p>=50?'Buena':p>=25?'Media':'Baja! \u26a0';}
function eSon(c){
  if(c<0) return 'Sin deteccion';
  if(c<10) return '\u26a0 Muy cerca!';
  if(c<30) return 'Cerca';
  if(c<80) return 'Medio';
  return 'Lejos';
}

function actualizar(){
  fetch('/datos?t='+Date.now())
    .then(function(r){return r.json();})
    .then(function(d){
      document.getElementById('v').textContent=d.v.toFixed(2)+' V';
      document.getElementById('pct').textContent=d.pct.toFixed(0)+'%';
      var c=cBat(d.pct);
      var b=document.getElementById('barra');
      b.style.width=Math.max(0,Math.min(100,d.pct)).toFixed(0)+'%';
      b.style.background=c;
      var be=document.getElementById('bat-estado');
      be.textContent=eBat(d.pct); be.style.color=c;

      var cm=d.cm;
      document.getElementById('cm').textContent=cm>0?cm.toFixed(1)+' cm':'-- cm';
      var pSon=cm>0?Math.max(0,Math.min(100,(1-cm/200)*100)):0;
      document.getElementById('sonar-barra').style.width=pSon.toFixed(0)+'%';
      var se=document.getElementById('sonar-estado');
      se.textContent=eSon(cm);

      document.getElementById('dot').className='dot';
      document.getElementById('pie').textContent='Robot11 activo \u2022 172.20.10.13';
    })
    .catch(function(){
      document.getElementById('dot').className='dot err';
      document.getElementById('pie').textContent='Sin respuesta del Pico...';
    });
}

function setInt(){
  var n=parseInt(document.getElementById('seg').value);
  if(isNaN(n)||n<1||n>60){alert('Valor entre 1 y 60');return;}
  seg=n;
  fetch('/intervalo?seg='+n).catch(function(){});
  reiniciar();
}

function reiniciar(){
  if(timer) clearInterval(timer);
  actualizar();
  timer=setInterval(actualizar,seg*1000);
}

reiniciar();
</script>
</body>
</html>"""

# ──────────────────────────────────────────────
#  Servidor web
# ──────────────────────────────────────────────
def send_response(conn, code, ctype, body):
    if isinstance(body, str):
        body = body.encode()
    header = (
        "HTTP/1.1 {} OK\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: close\r\n\r\n"
    ).format(code, ctype, len(body))
    conn.sendall(header.encode() + body)

def manejar(conn):
    global intervalo
    try:
        conn.settimeout(3.0)
        req = b""
        while True:
            chunk = conn.recv(256)
            if not chunk:
                break
            req += chunk
            if b"\r\n\r\n" in req or len(chunk) < 256:
                break
        linea = req.decode("utf-8", "ignore").split("\r\n")[0]

        if "/intervalo" in linea:
            try:
                nuevo = int(linea.split("seg=")[1].split(" ")[0].split("&")[0])
                if 1 <= nuevo <= 60:
                    intervalo = nuevo
            except:
                pass
            send_response(conn, 200, "text/plain", "ok")

        elif "/datos" in linea:
            data = json.dumps({
                "v":   round(ultimo_v,   2),
                "pct": round(ultimo_pct, 1),
                "cm":  ultimo_cm
            })
            send_response(conn, 200, "application/json", data)

        else:
            send_response(conn, 200, "text/html; charset=utf-8", HTML)

    except:
        pass
    finally:
        conn.close()

# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
oled_msg("Robot11", "Iniciando...")
time.sleep(1)

ip = conectar_wifi()

srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 80))
srv.listen(3)
srv.setblocking(False)

print("Servidor web listo en http://{}".format(ip))
oled_msg("Listo!", ip)

ultimo_lectura = 0

while True:
    ahora = time.time()
    if ahora - ultimo_lectura >= intervalo:
        ultimo_v   = leer_voltaje()
        ultimo_pct = calcular_pct(ultimo_v)
        ultimo_cm  = leer_sonar()
        dibujar(ultimo_v, ultimo_pct, ultimo_cm)
        print("[BAT] {}V  {}%  |  [SONAR] {}cm".format(
            ultimo_v, round(ultimo_pct, 1), ultimo_cm))
        ultimo_lectura = ahora
    try:
        conn, _ = srv.accept()
        manejar(conn)
    except OSError:
        pass
    time.sleep_ms(20)