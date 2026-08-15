#!/usr/bin/env python3
"""TV'deki uygulamanin Web Inspector'ina baglanip JS calistirir.

TV'de dlog ve kabuk kapali; hata ayiklamanin tek guvenilir yolu bu.
Once uygulamayi debug modunda baslat:
    sdb -s "$TV_IP:26101" shell 0 debug PublicIptv.Iptv
Cikan portu ver:
    python3 inceleyici.py 35395 "document.body.innerHTML.length"
Ifade verilmezse varsayilan bir teshis paketi calistirir.
"""
import base64
import json
import os
import socket
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tv import WS  # websocket cerceve kodunu tekrar yazmayalim

# Varsayilan TV; yonetim arayuzunu basssiz Chrome'da denetlemek icin
# INCELE_HOST=127.0.0.1 ile baska bir hedefe yoneltilebilir.
TV = os.environ.get("INCELE_HOST", "tv.local")

VARSAYILAN = """(function () {
  return JSON.stringify({
    baslik: document.title,
    hazir: document.readyState,
    bodyUzunluk: document.body ? document.body.innerHTML.length : -1,
    bodyBas: document.body ? document.body.innerHTML.slice(0, 200) : null,
    h1: document.querySelector('h1') ? document.querySelector('h1').textContent : null,
    govdeYuksek: document.body ? document.body.offsetHeight : -1,
    tizen: typeof tizen,
    webapis: typeof webapis,
    logVar: typeof window.LOG
  });
})()"""


def ws_ac(host, port, path, timeout=15):
    """Sifresiz websocket el sikismasi (tv.py'deki surum TLS sariyor)."""
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    anahtar = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {anahtar}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = s.recv(4096)
        if not d:
            raise RuntimeError("el sikisma sirasinda baglanti kapandi")
        buf += d
    bas, kalan = buf.split(b"\r\n\r\n", 1)
    if b"101" not in bas.split(b"\r\n")[0]:
        raise RuntimeError(bas.decode(errors="replace"))
    return WS(s, kalan)


def main():
    port = sys.argv[1]
    ifade = sys.argv[2] if len(sys.argv) > 2 else VARSAYILAN
    # "@dosya.js" ile uzun ifadeleri dosyadan oku
    if ifade.startswith("@"):
        with open(ifade[1:], encoding="utf-8") as f:
            ifade = f.read()

    with urllib.request.urlopen(f"http://{TV}:{port}/json", timeout=8) as r:
        hedefler = json.load(r)

    # Yalnizca gercek sayfalar: Chrome'da liste eklenti arka plan sayfalari ve
    # service worker'larla basliyor, korlemesine ilkini almak yanlis hedefe baglar.
    sayfalar = [h for h in hedefler
                if h.get("type") == "page" and h.get("webSocketDebuggerUrl")]
    if not sayfalar:
        sys.exit("inspector'da sayfa yok (bulunan hedefler: %s)"
                 % ", ".join(h.get("type", "?") for h in hedefler))
    yol = sayfalar[0]["webSocketDebuggerUrl"].split(port, 1)[1]

    ws = ws_ac(TV, int(port), yol)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.send(json.dumps({
        "id": 2, "method": "Runtime.evaluate",
        "params": {"expression": ifade, "returnByValue": True},
    }))

    for _ in range(40):
        mesaj = json.loads(ws.recv())
        if mesaj.get("id") == 2:
            sonuc = mesaj.get("result", {})
            if "exceptionDetails" in sonuc:
                print("JS ISTISNASI:", json.dumps(sonuc["exceptionDetails"], indent=2))
            deger = sonuc.get("result", {}).get("value")
            try:
                print(json.dumps(json.loads(deger), indent=2, ensure_ascii=False))
            except (TypeError, ValueError):
                print(deger)
            return
        if mesaj.get("method") in ("Runtime.consoleAPICalled", "Runtime.exceptionThrown"):
            print("KONSOL:", json.dumps(mesaj["params"])[:400])


if __name__ == "__main__":
    main()
