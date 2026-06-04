"""
broker.py -- Broker PubSub
Robot7 

TCP  puerto 5051  <- Raspberry Pi Pico 2W
WS   puerto 5052  <- Navegador (frontend.html)

Cómo correr:
  pip install websockets
  python broker.py
"""

import asyncio
import websockets
import socket
import json


class TCPClient:
    def __init__(self, writer):
        self.writer = writer
    async def send(self, msg):
        try:
            self.writer.write((msg + "\n").encode())
            await self.writer.drain()
        except Exception as e:
            print(f"[TCP] send err: {e}")
    def __repr__(self):
        return f"TCP({id(self)%1000})"


class WSClient:
    def __init__(self, ws):
        self.ws = ws
    async def send(self, msg):
        try:
            await self.ws.send(msg)
        except Exception as e:
            print(f"[WS] send err: {e}")
    def __repr__(self):
        return f"WS({id(self)%1000})"


class PubSub:
    def __init__(self):
        self._subs = {}

    def subscribe(self, client, topic):
        self._subs.setdefault(topic, set()).add(client)
        print(f"[SUB] {client} -> {topic}")

    def unsubscribe_all(self, client):
        for clients in self._subs.values():
            clients.discard(client)
        print(f"[UNSUB] {client}")

    async def publish(self, topic, data, origin=None):
        msg     = json.dumps({"action":"PUB","topic":topic,"data":data})
        clients = self._subs.get(topic, set())
        # Solo imprimir si no es frame (evitar spam)
        if "camera" not in topic:
            print(f"[PUB] {topic} -> {len(clients)} cliente(s)")
        for c in list(clients):
            if c != origin:
                await c.send(msg)


class TCPServer:
    def __init__(self, pubsub, host = "172.20.10.4", port=5051):
        self.pubsub = pubsub
        self.host   = host
        self.port   = port

    async def handle(self, reader, writer):
        client  = TCPClient(writer)
        print(f"[TCP] Pico conectado: {writer.get_extra_info('peername')}")
        buf = b""
        try:
            while True:
                # Leer en chunks hasta encontrar \n
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                # Procesar todas las líneas completas
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        pkt    = json.loads(line.decode())
                        action = pkt.get("action")
                        if action == "SUB":
                            self.pubsub.subscribe(client, pkt["topic"])
                        elif action == "PUB":
                            await self.pubsub.publish(
                                pkt["topic"], pkt.get("data",{}), origin=client
                            )
                    except Exception as e:
                        print(f"[TCP] parse err: {e} len={len(line)}")
        except Exception as e:
            print(f"[TCP] err: {e}")
        finally:
            self.pubsub.unsubscribe_all(client)
            writer.close()

    async def start(self):
        srv = await asyncio.start_server(self.handle, self.host, self.port)
        print(f"[TCP] Escuchando en {self.host}:{self.port}")
        return srv


class WSServer:
    def __init__(self, pubsub, host = "172.20.10.4", port=5052):
        self.pubsub = pubsub
        self.host   = host
        self.port   = port

    async def handle(self, websocket):
        client = WSClient(websocket)
        print(f"[WS] Navegador conectado")
        try:
            async for message in websocket:
                try:
                    pkt    = json.loads(message)
                    action = pkt.get("action")
                    if action == "SUB":
                        self.pubsub.subscribe(client, pkt["topic"])
                    elif action == "PUB":
                        await self.pubsub.publish(
                            pkt["topic"], pkt.get("data",{}), origin=client
                        )
                except Exception as e:
                    print(f"[WS] parse err: {e}")
        except Exception as e:
            print(f"[WS] err: {e}")
        finally:
            self.pubsub.unsubscribe_all(client)

    async def start(self):
        srv = await websockets.serve(
            self.handle, self.host, self.port,
            max_size=10*1024*1024   # 10MB max frame WS
        )
        print(f"[WS] Escuchando en {self.host}:{self.port}")
        return srv


async def main():
    ip = socket.gethostbyname(socket.gethostname())
    print("="*45)
    print(f"  BROKER Robot7")
    print(f"  IP local : {ip}")
    print(f"  TCP Pico : 5051")
    print(f"  WS Web   : 5052")
    print("="*45)
    pubsub = PubSub()
    tcp    = TCPServer(pubsub)
    ws     = WSServer(pubsub)
    await tcp.start()
    await ws.start()
    print("\nBroker listo.\n")
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())