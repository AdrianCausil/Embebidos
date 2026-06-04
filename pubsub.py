"""
pubsub.py — Cliente PubSub sobre TCP
Robot7

Clases:
  SocketClient   conexión TCP no-bloqueante al broker
  Node           nodo PubSub local + puente al broker

Topics tienen prefijo: UDFJC/emb1/robot11/

Uso mínimo:
  from pubsub import SocketClient, Node
  from scheduler import Scheduler

  sched  = Scheduler()
  sock   = SocketClient("192.168.1.x", 5051, sched)
  pubsub = Node(sock)

  pubsub.subscribe("car/cmd", lambda d: print(d))
  pubsub.publish("debug/log", {"msg": "hola"})

  sock.connect()
  sched.run()
"""

import usocket as socket
import ujson as json
import utime
import gc


ROBOT_ID  = "robot11"
TOPIC_PRE = "UDFJC/emb1/" + ROBOT_ID + "/"


class SocketClient:
    """
    Conexión TCP no-bloqueante al broker.
    Se integra con el Scheduler como Task (prioridad 1).

    Protocolo: JSON por línea (newline-delimited JSON).
    Cada mensaje termina en \\n.
    """

    def __init__(self, host, port, scheduler=None,
                 period_ms=50, priority=1):
        self.host      = host
        self.port      = port
        self.period    = period_ms
        self.priority  = priority
        self.next_run  = utime.ticks_ms()

        self.sock      = None
        self.connected = False
        self._rx       = b""
        self._actions  = {}

        if scheduler:
            scheduler.add(self)

    # ══════════════════════════════════════════════════════════
    #  Conexión
    # ══════════════════════════════════════════════════════════

    def connect(self):
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
            print(f"[TCP] Error: {e}")
            self.sock      = None
            self.connected = False
            return False

    def ensure(self):
        """Reconecta si perdió la conexión."""
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

    # ══════════════════════════════════════════════════════════
    #  Envío
    # ══════════════════════════════════════════════════════════

    def send_json(self, obj):
        if not self.connected:
            return False
        try:
            raw = (json.dumps(obj) + "\n").encode()
            self.sock.send(raw)
            return True
        except Exception as e:
            print(f"[TCP] send err: {e}")
            self.connected = False
            self.sock      = None
            return False

    # ══════════════════════════════════════════════════════════
    #  Registro de acciones (despacho de mensajes entrantes)
    # ══════════════════════════════════════════════════════════

    def add_action(self, action, callback):
        self._actions[action] = callback

    # ══════════════════════════════════════════════════════════
    #  update() — llamado por el Scheduler cada period_ms
    # ══════════════════════════════════════════════════════════

    def update(self):
        # Reconectar si es necesario
        if not self.connected:
            self.connect()
            return

        # Recibir datos disponibles (non-blocking)
        try:
            data = self.sock.recv(512)
            if data == b"":
                print("[TCP] Broker cerró la conexión")
                self.connected = False
                return
            if data:
                self._rx += data
        except OSError:
            pass   # sin datos — normal en non-blocking

        # Procesar líneas completas
        while b"\n" in self._rx:
            line, self._rx = self._rx.split(b"\n", 1)
            if not line:
                continue
            try:
                msg    = json.loads(line)
                action = msg.get("action")
                if action in self._actions:
                    self._actions[action](msg)
            except Exception as e:
                print(f"[TCP] JSON err: {e}")


# ══════════════════════════════════════════════════════════════
class Node:
    """
    Nodo PubSub.

    publish(topic, data)      → entrega local + envía al broker
    subscribe(topic, callback) → registra local + notifica al broker

    Los topics son locales (sin prefijo).
    El prefijo UDFJC/emb1/robot11/ se añade solo al hablar con el broker.
    """

    def __init__(self, sock_client, prefix=TOPIC_PRE):
        self.sock   = sock_client
        self.prefix = prefix
        self._subs  = {}   # topic_local → [callback, ...]
        sock_client.add_action("PUB", self._on_broker_pub)

    # ── API pública ────────────────────────────────────────────

    def publish(self, topic, data):
        """Publica en el bus local y en el broker."""
        self._local(topic, data)
        self._broker_pub(topic, data)

    def publish_local(self, topic, data):
        """Publica solo en el bus local, sin enviar al broker."""
        self._local(topic, data)

    def subscribe(self, topic, callback):
        """Suscribe callback y registra en el broker."""
        self._subs.setdefault(topic, []).append(callback)
        self.sock.ensure()
        self.sock.send_json({
            "action": "SUB",
            "topic":  self.prefix + topic
        })
        print(f"[SUB] {callback.__self__.__class__.__name__}"
              f".{callback.__name__} → {topic}")

    # ── Internos ───────────────────────────────────────────────

    def _broker_pub(self, topic, data):
        self.sock.ensure()
        self.sock.send_json({
            "action": "PUB",
            "topic":  self.prefix + topic,
            "data":   data
        })

    def _local(self, topic, data):
        for cb in list(self._subs.get(topic, [])):
            try:
                cb(data)
            except Exception as e:
                print(f"[PubSub] Error '{topic}': {e}")

    def _on_broker_pub(self, msg):
        """Recibe PUB del broker y lo entrega en el bus local."""
        t = msg.get("topic", "")
        if t.startswith(self.prefix):
            local = t[len(self.prefix):]
            self._local(local, msg.get("data", {}))