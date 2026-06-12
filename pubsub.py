"""
pubsub.py — Cliente PubSub sobre TCP
Robot11 | MicroPython - Raspberry Pi Pico 2W

Clases:
    SocketClient   conexión TCP no-bloqueante al broker (es una Task)
    Node           nodo PubSub local con puente al broker

Prefijo de tópicos: UDFJC/emb1/robot11/
Los módulos trabajan con tópicos cortos (sin prefijo).
El prefijo se agrega automáticamente al hablar con el broker.

Uso mínimo:
    from scheduler import Scheduler
    from pubsub    import SocketClient, Node

    sched  = Scheduler()
    sock   = SocketClient("192.168.x.x", 5051, sched)
    pubsub = Node(sock)

    pubsub.subscribe("test/pong", lambda d: print("pong:", d))
    pubsub.publish("test/ping", {"msg": "hola"})

    sched.run()
"""

import usocket as socket
import ujson   as json
import utime


ROBOT_ID   = "robot11"
TOPIC_PRE  = "UDFJC/emb1/" + ROBOT_ID + "/"


# ─────────────────────────────────────────────────────────────
class SocketClient:
    """
    Conexión TCP no-bloqueante al broker del PC.
    Se registra en el Scheduler como Task con prioridad 1.

    Protocolo: JSON por línea (newline-delimited JSON, \\n).
    """

    def __init__(self, host, port, scheduler,
                 period_ms=50, priority=1):
        self.host      = host
        self.port      = port
        self.period    = period_ms
        self.priority  = priority
        self.next_run  = utime.ticks_ms()

        self.sock      = None
        self.connected = False
        self._rx       = b""
        self._actions  = {}          # "PUB" → callback

        scheduler.add(self)

    # ── Conexión ──────────────────────────────────────────────

    def connect(self):
        """Intenta conectar al broker. Retorna True si éxito."""
        try:
            addr = socket.getaddrinfo(self.host, self.port)[0][-1]
            s    = socket.socket()
            s.connect(addr)
            s.setblocking(False)
            self.sock      = s
            self.connected = True
            print(f"[TCP] Conectado a {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[TCP] Fallo conexión: {e}")
            self.sock      = None
            self.connected = False
            return False

    def ensure(self):
        """Reconecta si la conexión se perdió."""
        if not self.connected or self.sock is None:
            self.connect()

    def disconnect(self):
        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        self.sock      = None
        self.connected = False
        print("[TCP] Desconectado.")

    # ── Envío con reintentos (optimizado para EAGAIN) ─────────────────

    def send_json(self, obj):
        """Serializa obj a JSON y lo envía con \\n al final.
        Reintenta hasta 5 veces si el buffer de salida está lleno (EAGAIN)."""
        if not self.connected:
            return False
        raw = (json.dumps(obj) + "\n").encode()
        for attempt in range(5):
            try:
                self.sock.send(raw)
                return True
            except OSError as e:
                if e.errno == 11:  # EAGAIN (buffer lleno)
                    utime.sleep_ms(5)   # esperar un poco y reintentar
                    continue
                else:
                    raise
            except Exception as e:
                print(f"[TCP] send error: {e}")
                break
        # Si llegamos aquí, falló después de reintentos
        self.connected = False
        self.sock = None
        return False

    # ── Registro de acciones ──────────────────────────────────

    def add_action(self, action, callback):
        """Registra un callback para un tipo de acción entrante."""
        self._actions[action] = callback

    # ── update() — llamado por el Scheduler ───────────────────

    def update(self):
        # Reconectar si es necesario
        if not self.connected:
            self.connect()
            return

        # Recibir datos disponibles (non-blocking)
        try:
            data = self.sock.recv(512)
            if data == b"":
                print("[TCP] Broker cerró la conexión.")
                self.connected = False
                return
            if data:
                self._rx += data
        except OSError:
            pass   # sin datos disponibles, es normal en non-blocking

        # Procesar todas las líneas completas
        while b"\n" in self._rx:
            line, self._rx = self._rx.split(b"\n", 1)
            if not line:
                continue
            try:
                msg    = json.loads(line)
                action = msg.get("action")
                cb     = self._actions.get(action)
                if cb:
                    cb(msg)
            except Exception as e:
                print(f"[TCP] JSON parse error: {e}")


# ─────────────────────────────────────────────────────────────
class Node:
    """
    Nodo PubSub local con puente al broker.

    publish(topic, data)       → entrega local + envía al broker
    publish_local(topic, data) → solo entrega local (sin broker)
    subscribe(topic, callback) → registra local + avisa al broker
    """

    def __init__(self, sock_client, prefix=TOPIC_PRE):
        self.sock   = sock_client
        self.prefix = prefix
        self._subs  = {}   # topic_local → [callback, ...]
        sock_client.add_action("PUB", self._on_broker_pub)

    # ── API pública ───────────────────────────────────────────

    def publish(self, topic, data):
        """Publica en el bus local y envía al broker."""
        self._deliver_local(topic, data)
        self._send_to_broker(topic, data)

    def publish_local(self, topic, data):
        """Publica solo en el bus local, sin enviar al broker."""
        self._deliver_local(topic, data)

    def subscribe(self, topic, callback):
        """Suscribe callback al tópico y lo registra en el broker."""
        self._subs.setdefault(topic, []).append(callback)
        self.sock.ensure()
        self.sock.send_json({
            "action": "SUB",
            "topic":  self.prefix + topic
        })
        # Nombre legible del callback
        try:
            name = f"{callback.__self__.__class__.__name__}.{callback.__name__}"
        except AttributeError:
            name = str(callback)
        print(f"[NODE] Suscrito: {name} → {topic}")

    # ── Internos ──────────────────────────────────────────────

    def _send_to_broker(self, topic, data):
        self.sock.ensure()
        self.sock.send_json({
            "action": "PUB",
            "topic":  self.prefix + topic,
            "data":   data
        })

    def _deliver_local(self, topic, data):
        for cb in list(self._subs.get(topic, [])):
            try:
                cb(data)
            except Exception as e:
                print(f"[NODE] Error en callback '{topic}': {e}")

    def _on_broker_pub(self, msg):
        """Recibe PUB del broker y lo entrega en el bus local."""
        t = msg.get("topic", "")
        if t.startswith(self.prefix):
            local_topic = t[len(self.prefix):]
            self._deliver_local(local_topic, msg.get("data", {}))