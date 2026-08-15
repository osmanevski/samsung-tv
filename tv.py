#!/usr/bin/env python3
"""
Samsung Tizen TV'yi Mac'ten kontrol et.

  tv <url>              tarayiciyi bu adreste ac
  tv key UP DOWN ENTER  kumanda tusu gonder
  tv text "merhaba"     acik metin kutusuna yaz
  tv apps               DIAL ile acilabilen uygulamalar
  tv netflix | youtube  o uygulamayi ac
  tv ping               baglantiyi test et

Tus adlari: UP DOWN LEFT RIGHT ENTER RETURN HOME EXIT MENU
            VOLUP VOLDOWN MUTE PLAY PAUSE STOP POWER
"""
import socket, ssl, base64, os, json, struct, sys, time, urllib.request

IP = os.environ.get("TV_IP", "tv.local")
PORT = 8002
CFG = os.path.expanduser("~/.config/samsung-tv")
TOKEN_FILE = os.path.join(CFG, "token")
CLIENT_NAME = "Mac"

KEYS = {
    "UP": "KEY_UP", "DOWN": "KEY_DOWN", "LEFT": "KEY_LEFT", "RIGHT": "KEY_RIGHT",
    "ENTER": "KEY_ENTER", "OK": "KEY_ENTER", "RETURN": "KEY_RETURN", "BACK": "KEY_RETURN",
    "HOME": "KEY_HOME", "EXIT": "KEY_EXIT", "MENU": "KEY_MENU",
    "VOLUP": "KEY_VOLUP", "VOLDOWN": "KEY_VOLDOWN", "MUTE": "KEY_MUTE",
    "PLAY": "KEY_PLAY", "PAUSE": "KEY_PAUSE", "STOP": "KEY_STOP", "POWER": "KEY_POWER",
    "CHUP": "KEY_CHUP", "CHDOWN": "KEY_CHDOWN", "CHLIST": "KEY_CH_LIST",
    "SOURCE": "KEY_SOURCE", "INFO": "KEY_INFO", "GUIDE": "KEY_GUIDE",
    "TOOLS": "KEY_TOOLS", "SUBTITLE": "KEY_SUBTITLE",
    "REWIND": "KEY_REWIND", "FF": "KEY_FF", "RECORD": "KEY_REC",
    "RED": "KEY_RED", "GREEN": "KEY_GREEN", "YELLOW": "KEY_YELLOW", "BLUE": "KEY_BLUE",
    **{str(n): f"KEY_{n}" for n in range(10)},
}


def ws_connect(host, port, path, timeout=35):
    s = socket.create_connection((host, port), timeout=timeout)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    s = ctx.wrap_socket(s, server_hostname=host)
    s.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d:
            raise RuntimeError("el sikisma sirasinda baglanti kapandi")
        buf += d
    head, rest = buf.split(b"\r\n\r\n", 1)
    if b"101" not in head.split(b"\r\n")[0]:
        raise RuntimeError(head.decode(errors="replace"))
    return s, rest


class WS:
    def __init__(self, sock, initial=b""):
        self.sock, self.buf = sock, initial

    def _need(self, n):
        while len(self.buf) < n:
            d = self.sock.recv(4096)
            if not d:
                raise RuntimeError("baglanti kapandi")
            self.buf += d

    def send(self, text):
        data = text.encode()
        h = bytearray([0x81])
        n = len(data)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126); h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127); h += struct.pack(">Q", n)
        m = os.urandom(4)
        h += m
        self.sock.sendall(bytes(h) + bytes(b ^ m[i % 4] for i, b in enumerate(data)))

    def recv(self):
        self._need(2)
        b1 = self.buf[1]
        masked, ln, off = b1 & 0x80, b1 & 0x7F, 2
        if ln == 126:
            self._need(4); ln = struct.unpack(">H", self.buf[2:4])[0]; off = 4
        elif ln == 127:
            self._need(10); ln = struct.unpack(">Q", self.buf[2:10])[0]; off = 10
        m = b""
        if masked:
            self._need(off + 4); m = self.buf[off:off + 4]; off += 4
        self._need(off + ln)
        p = self.buf[off:off + ln]
        if masked:
            p = bytes(b ^ m[i % 4] for i, b in enumerate(p))
        self.buf = self.buf[off + ln:]
        return p


def connect():
    os.makedirs(CFG, exist_ok=True)
    token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else ""
    path = f"/api/v2/channels/samsung.remote.control?name={base64.b64encode(CLIENT_NAME.encode()).decode()}"
    if token:
        path += f"&token={token}"
    else:
        print(">>> TV ekranina bak: izin penceresini kumandayla onayla.", file=sys.stderr)
    try:
        sock, rest = ws_connect(IP, PORT, path)
    except (socket.timeout, OSError) as e:
        sys.exit(f"TV'ye ulasilamadi ({IP}): {e}\nTV kapali veya agda degil olabilir.")
    ws = WS(sock, rest)
    msg = json.loads(ws.recv().decode())
    if msg.get("event") != "ms.channel.connect":
        sys.exit(f"beklenmeyen yanit: {msg}")
    new = (msg.get("data") or {}).get("token")
    if new and new != token:
        with open(TOKEN_FILE, "w") as f:
            f.write(new)
        os.chmod(TOKEN_FILE, 0o600)
        print("[eslesme tamam]", file=sys.stderr)
    return ws


def tus_kodu(ad):
    """Kisa adi (UP, OK, 5) TV'nin bekledigi KEY_ koduna cevir."""
    ad = ad.strip()
    return KEYS.get(ad.upper(), ad.upper() if ad.upper().startswith("KEY_") else None)


def tus_gonder(ws, kod):
    ws.send(json.dumps({"method": "ms.remote.control", "params": {
        "Cmd": "Click", "DataOfCmd": kod, "Option": "false",
        "TypeOfRemote": "SendRemoteKey"}}))


def metin_gonder(ws, txt):
    """Ekranda acik olan metin kutusuna yaz."""
    ws.send(json.dumps({"method": "ms.remote.control", "params": {
        "Cmd": base64.b64encode(txt.encode()).decode(),
        "DataOfCmd": "base64", "TypeOfRemote": "SendInputString"}}))


def url_ac(ws, url):
    """TV tarayicisini bu adreste ac. Tam adresi geri dondurur."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ws.send(json.dumps({"method": "ms.channel.emit", "params": {
        "event": "ed.apps.launch", "to": "host",
        "data": {"appId": "org.tizen.browser",
                 "action_type": "NATIVE_LAUNCH", "metaTag": url}}}))
    return url


def uygulama_ac(app):
    """DIAL ile uygulama baslat. (basarili_mi, mesaj) dondurur."""
    req = urllib.request.Request(f"http://{IP}:8080/ws/app/{app}", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return True, f"{app} acildi ({r.status})"
    except Exception as e:
        return False, f"{app} acilamadi: {e}"


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "apps":
        for a in ("Netflix", "YouTube"):
            try:
                with urllib.request.urlopen(f"http://{IP}:8080/ws/app/{a}", timeout=4) as r:
                    print(f"{a}: {'calisiyor' if r.status == 200 else r.status}")
            except Exception as e:
                print(f"{a}: yok ({e})")
        return

    if cmd in ("netflix", "youtube"):
        print(uygulama_ac({"netflix": "Netflix", "youtube": "YouTube"}[cmd])[1])
        return

    ws = connect()

    if cmd == "key":
        if not args:
            sys.exit("tus adi ver. Ornek: tv key DOWN DOWN ENTER")
        for k in args:
            code = tus_kodu(k)
            if not code:
                sys.exit(f"bilinmeyen tus: {k}\nGecerli: {' '.join(sorted(KEYS))}")
            tus_gonder(ws, code)
            time.sleep(0.35)
        print(f"{len(args)} tus gonderildi")

    elif cmd == "text":
        if not args:
            sys.exit("yazilacak metni ver")
        txt = " ".join(args)
        metin_gonder(ws, txt)
        print(f"yazildi: {txt}")

    elif cmd == "ping":
        print("baglanti basarili")

    else:
        print(f"TV'de aciliyor: {url_ac(ws, cmd)}")

    time.sleep(1.5)


if __name__ == "__main__":
    main()
