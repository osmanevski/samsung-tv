#!/usr/bin/env python3
"""
Samsung TV kumandasi - tarayicidan calisan kontrol paneli.

  python3 sunucu.py         8091 portunda baslar -> http://localhost:8091/
  python3 sunucu.py 9000    baska port
  python3 sunucu.py --ag    ev agindaki cihazlara da acar (telefondan girmek icin)

TV ile konusan kod ust klasordeki tv.py'de; burasi ona web yuzu takar.
TV'ye tek bir websocket baglantisi acilir, acik tutulur, koparsa kendi kendine
yeniden baglanir.
"""
import http.server, socketserver, threading, os, sys, re, json, socket, subprocess

BURASI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(BURASI))
import tv  # noqa: E402  (yol ayarlandiktan sonra)

PORT = 8091
AGA_AC = False
for a in sys.argv[1:]:
    if a in ("--ag", "-a"):
        AGA_AC = True
    elif a.isdigit():
        PORT = int(a)

EN_UZUN_GOVDE = 4096          # POST govdesi icin ust sinir
MAC_DOSYA = os.path.join(tv.CFG, "mac")   # WoL icin TV'nin MAC adresi
TUS_DESENI = re.compile(r"^KEY_[A-Z0-9_]{1,24}$")

_kilit = threading.RLock()
_ws = None            # TV'ye acik baglanti (yoksa None)
_son_hata = ""        # bos = sorun yok; baglanti sadece henuz kurulmamis


# --- TV baglantisi ------------------------------------------------------
def _yut(ws):
    """TV'nin gonderdigi bildirimleri oku at; okunmazsa soket tamponu dolar."""
    global _ws
    while True:
        try:
            ws.recv()
        except socket.timeout:
            continue
        except Exception:
            with _kilit:
                if _ws is ws:
                    _ws = None
            return


def _baglan():
    """Acik baglantiyi dondur, yoksa kur. Basarisizsa RuntimeError."""
    global _ws
    if _ws is not None:
        return _ws
    try:
        ws = tv.connect()          # token okuma/yazma isini tv.py yapiyor
    except SystemExit as e:        # tv.connect hata olunca cikmak ister; biz cikmayalim
        raise RuntimeError(str(e) or "TV'ye baglanilamadi")
    _ws = ws
    threading.Thread(target=_yut, args=(ws,), daemon=True).start()
    return ws


def gonder(is_yapan):
    """is_yapan(ws) calistir; baglanti kopmussa bir kez yenileyip tekrar dene."""
    global _ws, _son_hata
    with _kilit:
        for deneme in (1, 2):
            try:
                sonuc = is_yapan(_baglan())
                _son_hata = ""
                return sonuc
            except OSError:        # koptu; ikinci turda yeniden baglanir
                _ws = None
                if deneme == 2:
                    _son_hata = "TV baglantisi koptu"
                    raise RuntimeError(_son_hata)
            except RuntimeError as e:
                _son_hata = str(e)
                raise


# --- TV'yi uyandirma (Wake-on-LAN) --------------------------------------
def mac_bul():
    """TV'nin MAC adresi: once env, sonra ARP tablosu, sonra onbellek dosyasi.

    TV tamamen kapaninca ARP kaydi silinir; bu yuzden acikken gorduugumuzu
    saklariz, kapaliyken oradan okuruz.
    """
    m = os.environ.get("TV_MAC")
    if not m:
        try:
            cikti = subprocess.run(["arp", "-n", tv.IP], capture_output=True,
                                   text=True, timeout=3).stdout
            bulunan = re.search(r"\b((?:[0-9a-f]{1,2}:){5}[0-9a-f]{1,2})\b", cikti, re.I)
            if bulunan:
                m = ":".join(p.zfill(2) for p in bulunan.group(1).split(":"))
                os.makedirs(tv.CFG, exist_ok=True)
                with open(MAC_DOSYA, "w") as f:
                    f.write(m)
        except (OSError, subprocess.SubprocessError):
            pass
    if not m and os.path.exists(MAC_DOSYA):
        m = open(MAC_DOSYA).read().strip()
    return m


def uyandir():
    mac = mac_bul()
    if not mac:
        return False, "TV'nin MAC adresi bilinmiyor (TV bir kez acikken calistir)"
    ham = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    paket = b"\xff" * 6 + ham * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for hedef in ("255.255.255.255", tv.IP):
            for port in (9, 7):
                s.sendto(paket, (hedef, port))
    finally:
        s.close()
    return True, f"uyandirma sinyali gonderildi ({mac})"


# --- HTTP ---------------------------------------------------------------
class Isleyici(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, bicim, *a):
        pass  # sessiz calis

    def _json(self, govde, kod=200):
        veri = json.dumps(govde, ensure_ascii=False).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(veri)

    def _govde(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > EN_UZUN_GOVDE:
            return ""
        return self.rfile.read(n).decode("utf-8", "replace").strip()

    def do_GET(self):
        yol = self.path.split("?")[0]
        if yol == "/":
            try:
                with open(os.path.join(BURASI, "kumanda.html"), "rb") as f:
                    govde = f.read()
            except OSError:
                self.send_error(404, "kumanda.html bulunamadi")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(govde)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(govde)
        elif yol == "/durum":
            self._json({"bagli": _ws is not None, "ip": tv.IP, "mesaj": _son_hata})
        else:
            self.send_error(404, "yok")

    def do_POST(self):
        yol = self.path.split("?")[0]
        govde = self._govde()
        try:
            if yol == "/tus":
                kod = tv.tus_kodu(govde)
                if not kod or not TUS_DESENI.match(kod):
                    return self._json({"tamam": False, "mesaj": f"bilinmeyen tus: {govde}"}, 400)
                gonder(lambda ws: tv.tus_gonder(ws, kod))
                return self._json({"tamam": True, "mesaj": kod[4:]})

            if yol == "/metin":
                if not govde:
                    return self._json({"tamam": False, "mesaj": "metin bos"}, 400)
                gonder(lambda ws: tv.metin_gonder(ws, govde))
                return self._json({"tamam": True, "mesaj": f"yazildi: {govde}"})

            if yol == "/url":
                if not govde:
                    return self._json({"tamam": False, "mesaj": "adres bos"}, 400)
                adres = gonder(lambda ws: tv.url_ac(ws, govde))
                return self._json({"tamam": True, "mesaj": f"aciliyor: {adres}"})

            if yol == "/uygulama":
                if govde not in ("Netflix", "YouTube"):
                    return self._json({"tamam": False, "mesaj": "bilinmeyen uygulama"}, 400)
                tamam, mesaj = tv.uygulama_ac(govde)   # DIAL, websocket gerekmez
                return self._json({"tamam": tamam, "mesaj": mesaj})

            if yol == "/uyandir":
                tamam, mesaj = uyandir()
                return self._json({"tamam": tamam, "mesaj": mesaj})

            self.send_error(404, "yok")
        except RuntimeError as e:
            self._json({"tamam": False, "mesaj": str(e)}, 502)


class Sunucu(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def yerel_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((tv.IP, 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    adres = "0.0.0.0" if AGA_AC else "127.0.0.1"
    print(f"Kumanda paneli : http://localhost:{PORT}/")
    if AGA_AC:
        print(f"Agdaki cihazlar: http://{yerel_ip()}:{PORT}/")
    print(f"TV             : {tv.IP}")
    print("Durdurmak icin Ctrl+C\n")
    try:
        Sunucu((adres, PORT), Isleyici).serve_forever()
    except KeyboardInterrupt:
        print("\ndurduruldu")
