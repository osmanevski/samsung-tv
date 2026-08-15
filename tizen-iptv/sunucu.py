#!/usr/bin/env python3
"""Kanal yonetim sunucusu + TV log toplayici.

Iki kavram var ve ayri tutulmalari onemli:

  KATALOG  -- elindeki tum kanallar. Bir Xtream saglayicisi 50 bin+ donebiliyor.
              `katalog.json` icinde, yalnizca Mac'te durur.
  YAYIN    -- katalogda `sec: true` isaretlenenler. TV sadece bunu ceker.

Ayrim zorunlu: TV'de localStorage 5 MB'da doluyor ve kotayi asan yazma
uygulamayi kilitliyor (olculdu). Ayrica 910 kategori kumandayla gezilemiyor.

Uc noktalar:
  /                      -> yonetim arayuzu
  /api/kanallar          -> TV'nin cektigi liste (yalnizca secilenler)
  /api/katalog           -> tum katalog (GET) / kayit (POST)
  /api/kaynak-cek        -> uzak M3U veya Xtream get.php adresinden guncelle
  /api/m3u-ice-aktar     -> yapistirilan M3U metnini ayristir
  /api/m3u               -> secilenleri M3U olarak disa aktar
  /api/dene              -> toplu erisim testi
  /?m=...                -> TV uygulamasinin log beacon'lari

Kullanim:  python3 sunucu.py
"""
import atexit
import concurrent.futures
import datetime
import http.server
import json
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

PORT = 8099
KOK = os.path.dirname(os.path.abspath(__file__))
KATALOG_DOSYASI = os.path.join(KOK, "katalog.json")
ESKI_DOSYA = os.path.join(KOK, "kanallar.json")   # ilk surumden gecis icin
TOHUM_M3U = os.path.join(KOK, "..", "turkiye-origin-iptv.m3u")

# TV'nin onbellek siniri 3 MB; kanal basina ~210 bayt JSON ile bu ~14 bin kanal
# eder. Uyariyi cok daha erken veriyoruz cunku asil sinir kumandayla gezilebilirlik.
UYARI_SINIRI = 2000

# 1x1 seffaf GIF - log beacon'ina gecerli bir resim donmek gerekiyor
BOS_GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
           b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
           b"\x00\x02\x02D\x01\x00;")


# --- M3U ayristirma (uygulamadaki m3u.js ile ayni kurallar) ----------------

def m3u_ayristir(metin):
    kanallar, bekleyen = [], None
    for satir in metin.splitlines():
        s = satir.strip()
        if not s:
            continue
        if s.startswith("#EXTINF"):
            bekleyen = _extinf_ayristir(s)
        elif s.startswith("#EXTVLCOPT") and bekleyen:
            m = re.search(r"http-user-agent=(.*)$", s, re.I)
            if m:
                bekleyen["ajan"] = m.group(1).strip()
        elif s.startswith("#"):
            continue
        elif bekleyen:
            bekleyen["url"] = s
            kanallar.append(bekleyen)
            bekleyen = None
    return kanallar


def _extinf_ayristir(satir):
    kayit = {"ad": "", "url": "", "grup": "Diger", "gruplar": [],
             "logo": "", "id": "", "ajan": "", "uyari": ""}

    virgul = satir.rfind(",")
    if virgul > -1:
        kayit["ad"] = satir[virgul + 1:].strip()

    oznitelikler = satir[:virgul] if virgul > -1 else satir
    for ad, deger in re.findall(r'([a-zA-Z0-9-]+)="([^"]*)"', oznitelikler):
        dusuk = ad.lower()
        if dusuk == "group-title" and deger:
            kayit["grup"] = deger
        elif dusuk == "tvg-logo":
            kayit["logo"] = deger
        elif dusuk == "tvg-id":
            kayit["id"] = deger
        elif dusuk == "http-user-agent":
            kayit["ajan"] = deger

    gruplar = [g.strip() for g in kayit["grup"].split(";") if g.strip()]
    gruplar = ["Diger" if g == "Undefined" else g for g in gruplar] or ["Diger"]
    kayit["gruplar"] = gruplar
    kayit["grup"] = gruplar[0]

    not_ = re.search(r"\[([^\]]+)\]", kayit["ad"])
    if not_:
        kayit["uyari"] = not_.group(1)
        kayit["ad"] = re.sub(r"\s*\[[^\]]+\]\s*", " ", kayit["ad"]).strip()

    return kayit


def m3u_uret(kanallar):
    satirlar = ["#EXTM3U"]
    for k in kanallar:
        ad = k["ad"] + (" [%s]" % k["uyari"] if k.get("uyari") else "")
        oz = 'tvg-id="%s" tvg-logo="%s" group-title="%s"' % (
            k.get("id", ""), k.get("logo", ""), ";".join(k.get("gruplar") or [k.get("grup", "Diger")]))
        if k.get("ajan"):
            oz += ' http-user-agent="%s"' % k["ajan"]
        satirlar.append("#EXTINF:-1 %s,%s" % (oz, ad))
        if k.get("ajan"):
            satirlar.append("#EXTVLCOPT:http-user-agent=%s" % k["ajan"])
        satirlar.append(k["url"])
    return "\n".join(satirlar) + "\n"


# --- Depolama -------------------------------------------------------------

VIDEO_UZANTILARI = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".mpg", ".mpeg", ".wmv")


def tur_bul(url, grup=""):
    """Canli yayin mi kayittan video mu.

    Xtream'de yol belirleyici: /movie/USER/PASS/id.mp4 ve /series/... VOD,
    /USER/PASS/id.m3u8 canli. Grup adina bakmak yanilticiydi ("Movie-Drama"
    adinda canli kanal da olabiliyor), o yuzden once adrese bakiyoruz.
    """
    u = (url or "").lower().split("?")[0]
    if "/movie/" in u:
        return "film"
    if "/series/" in u:
        return "dizi"
    if u.endswith(VIDEO_UZANTILARI):
        return "film"
    return "canli"


def _tamamla(k, kaynak="elle", secili=True):
    """Eksik alanlari doldurur; elle eklenen ve ice aktarilan kayitlari esitler."""
    k.setdefault("ad", "")
    k.setdefault("url", "")
    k.setdefault("grup", "Diger")
    k.setdefault("gruplar", [k["grup"]])
    k.setdefault("logo", "")
    k.setdefault("id", "")
    k.setdefault("ajan", "")
    k.setdefault("uyari", "")
    k.setdefault("kaynak", kaynak)
    k.setdefault("sec", secili)
    k.setdefault("tur", tur_bul(k.get("url", ""), k.get("grup", "")))
    return k


# Katalog 280 bin kanala kadar buyuyebiliyor (128 MB JSON). Her istekte bastan
# okumak TV'nin /api/kanallar cagrisini ~1 sn'ye cikariyordu; TV'nin XHR zaman
# asimi 4 sn, yani katalog bir kat daha buyuse TV onbellege duserdi.
# Dosya degismedikce bellekteki kopyayi kullan.
_onbellek = {"mtime": None, "boyut": None, "veri": None}
_kilit = threading.Lock()


def katalog_oku():
    if os.path.exists(KATALOG_DOSYASI):
        st = os.stat(KATALOG_DOSYASI)
        with _kilit:
            if (_onbellek["veri"] is not None
                    and _onbellek["mtime"] == st.st_mtime
                    and _onbellek["boyut"] == st.st_size):
                return _onbellek["veri"]

        try:
            with open(KATALOG_DOSYASI, encoding="utf-8") as f:
                veri = [_tamamla(k) for k in json.load(f)]
        except ValueError as e:
            # Bozuk katalog sunucuyu tamamen olduruyordu. Bozugu kenara koyup
            # kurtarilabileni al; hicbir sey kurtulmazsa bos listeyle devam et
            # ki arayuz acilsin ve kullanici kaynagi yeniden cekebilsin.
            print(f"katalog.json okunamadi ({e}); onarim deneniyor…", flush=True)
            bozuk = KATALOG_DOSYASI + ".bozuk"
            try:
                import onar
                veri = [_tamamla(k) for k in onar.onar(KATALOG_DOSYASI, bozuk + ".json")]
                os.replace(bozuk + ".json", KATALOG_DOSYASI)
                st = os.stat(KATALOG_DOSYASI)
                print(f"onarildi: {len(veri)} kanal kurtarildi", flush=True)
            except Exception as e2:
                print(f"ONARILAMADI: {e2}. Bos katalogla aciliyor; "
                      f"bozuk dosya {bozuk} olarak saklandi.", flush=True)
                os.replace(KATALOG_DOSYASI, bozuk)
                return []

        with _kilit:
            _onbellek.update({"mtime": st.st_mtime, "boyut": st.st_size, "veri": veri})
        return veri

    # Onceki surumun kanallar.json'i varsa onu katalog yap, hepsi secili
    if os.path.exists(ESKI_DOSYA):
        with open(ESKI_DOSYA, encoding="utf-8") as f:
            katalog = [_tamamla(k) for k in json.load(f)]
        print(f"kanallar.json katalog.json'a tasindi ({len(katalog)} kanal, hepsi secili)")
        katalog_yaz(katalog)
        return katalog

    # Ilk calistirma: kullanicinin .m3u dosyasindan tohumla
    if os.path.exists(TOHUM_M3U):
        with open(TOHUM_M3U, encoding="utf-8") as f:
            katalog = [_tamamla(k) for k in m3u_ayristir(f.read())]
        print(f"katalog yok, {os.path.basename(TOHUM_M3U)} dosyasindan "
              f"{len(katalog)} kanal tohumlandi")
        katalog_yaz(katalog)
        return katalog

    return []


# Yazmalar SIRAYLA yapilmali. Sunucu cok is parcacikli; iki yazma ayni anda
# calisip ayni gecici dosyaya yazinca dosya birbirine giriyor ve katalog
# tamamen okunamaz hale geliyor (113 MB'lik katalog bir kez boyle bozuldu,
# onar.py ile kurtarildi). Kilit + her yazmaya ozel gecici ad, ikisi de sart.
_dosya_kilidi = threading.Lock()


def katalog_yaz(katalog):
    with _dosya_kilidi:
        # Gecici ada surec ve is parcacigi kimligi giriyor ki iki yazma
        # ayni dosyayi paylasmasin.
        gecici = "%s.%d.%d.tmp" % (KATALOG_DOSYASI, os.getpid(),
                                   threading.get_ident())
        try:
            with open(gecici, "w", encoding="utf-8") as f:
                json.dump(katalog, f, ensure_ascii=False, indent=2)
            os.replace(gecici, KATALOG_DOSYASI)
        except BaseException:
            if os.path.exists(gecici):
                os.remove(gecici)      # yarim dosya birakma
            raise

        st = os.stat(KATALOG_DOSYASI)
        with _kilit:
            _onbellek.update({"mtime": st.st_mtime, "boyut": st.st_size,
                              "veri": katalog})
            _indeks.update({"veri": None, "icin": None})


# --- Arama indeksi --------------------------------------------------------
# 250 bin kanalda her istekte ad+grup+url+kaynak birlestirip kucultmek pahali.
# Katalogla birlikte bir kez kuruluyor, katalog degisince atiliyor.
_indeks = {"veri": None, "icin": None}


# Turkce harfleri sadelestir: "ask masal" yazan "Aşk Masalı"yi bulsun.
# Bu olmadan panelde arama sessizce 0 sonuc donuyordu.
_TR_CEVIRI = str.maketrans("çğıİöşüÇĞÖŞÜâîû", "cgiiosucgosuaiu")


def sadelestir(s):
    return (s or "").translate(_TR_CEVIRI).lower()


def arama_indeksi(katalog):
    with _kilit:
        if _indeks["icin"] is katalog and _indeks["veri"] is not None:
            return _indeks["veri"]
    veri = [sadelestir(k["ad"] + " " + k["grup"] + " " + k["url"] + " " +
                       (k.get("kaynak") or "")) for k in katalog]
    with _kilit:
        _indeks.update({"veri": veri, "icin": katalog})
    return veri


# Denetleme sonuclari bellekte: 250 bin kanali tarayiciya tasiyip orada
# tutmanin anlami yok, filtreleme de sunucuda yapiliyor.
_test_sonuclari = {}


def katalogu_filtrele(katalog, q="", grup="", kaynak="", sec="", durum=""):
    indeks = arama_indeksi(katalog)
    q = sadelestir((q or "").strip())
    sonuc = []

    for i, k in enumerate(katalog):
        if kaynak and (k.get("kaynak") or "elle") != kaynak:
            continue
        if sec == "secili" and not k.get("sec"):
            continue
        if sec == "secisiz" and k.get("sec"):
            continue
        if grup and grup not in (k.get("gruplar") or [k.get("grup")]):
            continue
        if durum:
            kod = _test_sonuclari.get(k["url"])
            if kod is None:
                continue
            if durum == "iyi" and kod != 200:
                continue
            if durum == "kotu" and kod == 200:
                continue
        if q and q not in indeks[i]:
            continue
        sonuc.append((i, k))

    return sonuc


def grup_ozeti(katalog, azami=400):
    """Grup listesi + sayilari. 250 bin kanalda binlerce grup olabiliyor;
    acilir listeye sigmasi icin en kalabaliklardan azami kadari donuyor."""
    sayilar = {}
    for k in katalog:
        for g in (k.get("gruplar") or [k.get("grup", "Diger")]):
            sayilar[g] = sayilar.get(g, 0) + 1
    siralanmis = sorted(sayilar.items(), key=lambda x: -x[1])[:azami]
    return [{"grup": g, "sayi": n} for g, n in siralanmis]


def kaynak_ozeti(katalog):
    """Kaynak basina kanal ve secili sayisi. Arayuz 280 bin satiri indirmeden
    hangi kaynagin ne kadar yer kapladigini gorebilsin diye."""
    ozet = {}
    for k in katalog:
        kay = k.get("kaynak") or "elle"
        d = ozet.setdefault(kay, {"kaynak": kay, "toplam": 0, "secili": 0})
        d["toplam"] += 1
        if k.get("sec"):
            d["secili"] += 1
    return sorted(ozet.values(), key=lambda d: -d["toplam"])


# 128 MB'lik katalogu her kutucuk isaretinde diske yazmak 1-3 saniye suruyor.
# Degisiklikleri biriktirip bir duraklamadan sonra tek seferde yaziyoruz;
# toplu islemler ve silmeler ise hemen yazilir.
_yazma_kilidi = threading.Lock()
_yazma_zamanlayici = None


def kaydet_ertelenmis(katalog, gecikme=1.5):
    global _yazma_zamanlayici
    with _yazma_kilidi:
        if _yazma_zamanlayici is not None:
            _yazma_zamanlayici.cancel()
        _yazma_zamanlayici = threading.Timer(gecikme, katalog_yaz, args=(katalog,))
        _yazma_zamanlayici.daemon = True
        _yazma_zamanlayici.start()


def bekleyeni_yaz():
    """Cikista ya da toplu islemden once bekleyen yazmayi hemen bitir."""
    global _yazma_zamanlayici
    with _yazma_kilidi:
        z = _yazma_zamanlayici
        _yazma_zamanlayici = None
    if z is not None and z.is_alive():
        z.cancel()
        katalog_yaz(katalog_oku())


def secilenler(katalog):
    """TV'ye giden liste. `sec` ve `kaynak` alanlarini disarida birakiyoruz:
    TV'yi ilgilendirmiyor ve her bayt onbellek sinirindan yiyor."""
    disari = []
    for k in katalog:
        if not k.get("sec"):
            continue
        disari.append({key: k[key] for key in
                       ("ad", "url", "grup", "gruplar", "logo", "id", "ajan",
                        "uyari", "tur")})
    return disari


def kaynaktan_guncelle(katalog, url):
    """Uzak M3U / Xtream get.php adresinden katalogu tazeler.

    Kimlik url'dir. Kurallar:
      - Ayni url'in `sec` isareti korunur (yeniden secmek zorunda kalma).
      - Elle eklenenler ve baska kaynaklardan gelenler dokunulmaz; ustelik
        url'leri kaynaktan gelen kopyayi engeller, yoksa ayni kanal listede
        iki kez cikiyor (olculdu: 57 elle + 166 uzak = 223, 39'u kopya).
      - Bu kaynaktan gelip artik listede olmayanlar dusurulur; saglayici kaldirmis.
    """
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(istek, timeout=120, context=SSL_BAGLAM) as r:
        metin = r.read().decode("utf-8", errors="replace")

    # M3U olmayan bir yanit (giris sayfasi, hata metni, JSON…) sessizce "0 kanal
    # geldi" olarak gecmemeli; kullanici neyin yanlis gittigini anlayamiyor.
    bas = metin.lstrip()[:512]
    if "#EXTM3U" not in bas and "#EXTINF" not in metin[:4096]:
        ornek = " ".join(bas.split())[:160]
        raise ValueError("yanit M3U degil. Sunucunun dondugu ilk satirlar: " + ornek)

    yeniler = m3u_ayristir(metin)
    if not yeniler:
        raise ValueError("M3U ayristirildi ama icinde kanal yok "
                         "(%d bayt geldi)" % len(metin))

    onceki_sec = {k["url"]: k.get("sec", False) for k in katalog}

    # Bu kaynaktan gelmeyen her sey kalir ve url'leriyle kopyayi engeller.
    korunan = [k for k in katalog if k.get("kaynak") != url]
    tutulan_urller = set(k["url"] for k in korunan)

    taze, gorulen = [], set()
    for k in yeniler:
        if k["url"] in tutulan_urller or k["url"] in gorulen:
            continue          # zaten var ya da kaynagin kendi icinde tekrarlanmis
        gorulen.add(k["url"])
        _tamamla(k, kaynak=url, secili=onceki_sec.get(k["url"], False))
        k["kaynak"] = url
        taze.append(k)

    return korunan + taze, len(taze)


# --- HTTPS ----------------------------------------------------------------

def _ssl_baglami():
    """python.org kurulumlarinda kok sertifika demeti yapilandirilmamis geliyor
    (`ssl.get_default_verify_paths()` bos doner) ve her https istegi
    CERTIFICATE_VERIFY_FAILED ile patliyor. certifi varsa onu kullan."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_BAGLAM = _ssl_baglami()


# --- Kanal testi ----------------------------------------------------------
# Tarayicidan yapilamaz: yayin sunuculari CORS basligi gondermedigi icin
# fetch() sonucu okunamiyor. Bu yuzden olcumu sunucu tarafinda yapiyoruz.

# Durum kodu tek basina yetmiyor: bu saglayici olu filmlerde HTTP 200 donup
# HTML hata sayfasi veriyor. Icerik turune de bakmazsak olu kayitlar
# "calisiyor" gorunuyor (olculdu: 25 filmin 15'i boyle).
ICERIK_YOK = -1   # baglandi ama donen sey video/playlist degil


def url_dene(url, zaman_asimi=10):
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                 "Range": "bytes=0-2047"})
    try:
        with urllib.request.urlopen(istek, timeout=zaman_asimi, context=SSL_BAGLAM) as r:
            tur = (r.headers.get("Content-Type") or "").lower()
            bas = r.read(2048)
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0

    if "html" in tur or bas[:6].lower() in (b"<html>", b"<!doct"):
        return ICERIK_YOK
    # HLS playlist ya da ikili video akisi bekliyoruz
    if ("mpegurl" in tur or "video" in tur or "octet-stream" in tur
            or bas.lstrip()[:7] == b"#EXTM3U"):
        return 200
    return ICERIK_YOK


ZAMAN_ASIMI = -2   # denetleme suresi doldu, sonuc alinamadi


def toplu_dene(urller, toplam_sure=90):
    """Toplu erisim testi, TOPLAM sure siniriyla.

    Sinir sart: saglayici yaniti damla damla gonderdiginde urlopen'in zaman
    asimi hic tetiklenmiyor (her bayt sayaci sifirliyor) ve istek sonsuza kadar
    asili kaliyor. Bir kez sunucunun tamamini yanit veremez hale getirdi.
    """
    sonuc = {}
    havuz = concurrent.futures.ThreadPoolExecutor(max_workers=12)
    isler = {havuz.submit(url_dene, u): u for u in urller}
    tamam, bekleyen = concurrent.futures.wait(isler, timeout=toplam_sure)

    for i in tamam:
        try:
            sonuc[isler[i]] = i.result()
        except Exception:
            sonuc[isler[i]] = 0
    for i in bekleyen:
        sonuc[isler[i]] = ZAMAN_ASIMI
        i.cancel()

    # Asili is parcaciklarini beklemeden don; havuz kendi temizlenir.
    havuz.shutdown(wait=False)
    if bekleyen:
        print(f"  denetleme: {len(bekleyen)} istek {toplam_sure} sn icinde "
              f"bitmedi, zaman asimi sayildi", flush=True)
    return sonuc


# --- HTTP -----------------------------------------------------------------

class Sunucu(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _yanit(self, govde, tur="application/json; charset=utf-8", kod=200):
        if isinstance(govde, str):
            govde = govde.encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        # TV file:// kokeninde calisiyor; bu baslik olmadan XHR reddedilir.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def do_OPTIONS(self):
        self._yanit(b"", "text/plain", 204)

    def do_GET(self):
        parca = urllib.parse.urlparse(self.path)
        sorgu = urllib.parse.parse_qs(parca.query)

        # TV log beacon'i: / adresine ?m=... ile geliyor
        if "m" in sorgu:
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] TV: {sorgu['m'][0]}", flush=True)
            self._yanit(BOS_GIF, "image/gif")
            return

        if parca.path in ("/", "/index.html"):
            with open(os.path.join(KOK, "yonetim.html"), encoding="utf-8") as f:
                self._yanit(f.read(), "text/html; charset=utf-8")
            return

        # TV bunu ceker: yalnizca secilenler
        if parca.path == "/api/kanallar":
            self._yanit(json.dumps(secilenler(katalog_oku()), ensure_ascii=False))
            return

        # Yonetim arayuzu bunu ceker: her sey
        if parca.path == "/api/katalog":
            self._yanit(json.dumps(katalog_oku(), ensure_ascii=False))
            return

        # Sunucu tarafli arama + sayfalama. Arayuz katalogun tamamini asla
        # indirmez; 250 bin kanalda tek calisan yol bu.
        if parca.path == "/api/ara":
            katalog = katalog_oku()
            tek = lambda ad, vars="": sorgu.get(ad, [vars])[0]
            eslesen = katalogu_filtrele(
                katalog, q=tek("q"), grup=tek("grup"), kaynak=tek("kaynak"),
                sec=tek("sec"), durum=tek("durum"))

            boyut = max(1, min(500, int(tek("boyut", "100"))))
            sayfa = max(0, int(tek("sayfa", "0")))
            bas = sayfa * boyut
            dilim = eslesen[bas:bas + boyut]

            kanallar = []
            for sira, k in dilim:
                kayit = dict(k)
                kayit["sira"] = sira + 1          # katalogdaki gercek sira
                kayit["durum"] = _test_sonuclari.get(k["url"])
                kanallar.append(kayit)

            self._yanit(json.dumps({
                "toplam": len(eslesen), "sayfa": sayfa, "boyut": boyut,
                "katalogToplam": len(katalog),
                "secili": sum(1 for k in katalog if k.get("sec")),
                "kanallar": kanallar,
            }, ensure_ascii=False))
            return

        # Filtre secenekleri: grup ve kaynak listeleri
        if parca.path == "/api/facet":
            katalog = katalog_oku()
            self._yanit(json.dumps({
                "toplam": len(katalog),
                "secili": sum(1 for k in katalog if k.get("sec")),
                "gruplar": grup_ozeti(katalog),
                "kaynaklar": kaynak_ozeti(katalog),
                "uyariSiniri": UYARI_SINIRI,
            }, ensure_ascii=False))
            return

        # Kaynak ozeti: katalog buyudugunde arayuz once bunu cekip karar verir
        if parca.path == "/api/kaynaklar":
            katalog = katalog_oku()
            self._yanit(json.dumps({
                "toplam": len(katalog),
                "secili": sum(1 for k in katalog if k.get("sec")),
                "kaynaklar": kaynak_ozeti(katalog),
            }, ensure_ascii=False))
            return

        if parca.path == "/api/m3u":
            katalog = katalog_oku()
            tumu = sorgu.get("tumu", ["0"])[0] == "1"
            self._yanit(m3u_uret(katalog if tumu else secilenler(katalog)),
                        "text/plain; charset=utf-8")
            return

        self._yanit(json.dumps({"hata": "bulunamadi"}), kod=404)

    def do_POST(self):
        parca = urllib.parse.urlparse(self.path)
        uzunluk = int(self.headers.get("Content-Length", 0))
        govde = self.rfile.read(uzunluk).decode("utf-8") if uzunluk else ""

        if parca.path == "/api/katalog":
            try:
                katalog = [_tamamla(k) for k in json.loads(govde)]
            except ValueError as e:
                self._yanit(json.dumps({"hata": str(e)}), kod=400)
                return
            katalog_yaz(katalog)
            secili = sum(1 for k in katalog if k.get("sec"))
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] kaydedildi: {len(katalog)} kanal katalogda, "
                  f"{secili} tanesi TV'de", flush=True)
            self._yanit(json.dumps({"tamam": True, "katalog": len(katalog),
                                    "secili": secili, "uyariSiniri": UYARI_SINIRI}))
            return

        if parca.path == "/api/kaynak-cek":
            try:
                url = json.loads(govde)["url"].strip()
            except (ValueError, KeyError) as e:
                self._yanit(json.dumps({"hata": "adres okunamadi: %s" % e}), kod=400)
                return
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] kaynak cekiliyor: {url}", flush=True)
            try:
                katalog, gelen = kaynaktan_guncelle(katalog_oku(), url)
            except Exception as e:
                print(f"[{saat}] kaynak hatasi: {e}", flush=True)
                self._yanit(json.dumps({"hata": str(e)}), kod=502)
                return
            katalog_yaz(katalog)
            secili = sum(1 for k in katalog if k.get("sec"))
            print(f"[{saat}] kaynaktan {gelen} kanal geldi, katalog {len(katalog)}, "
                  f"{secili} secili", flush=True)
            self._yanit(json.dumps({"tamam": True, "gelen": gelen,
                                    "katalog": len(katalog), "secili": secili}))
            return

        if parca.path == "/api/m3u-ice-aktar":
            kanallar = m3u_ayristir(govde)
            self._yanit(json.dumps(kanallar, ensure_ascii=False))
            return

        # Yapistirilan M3U'yu ayristirip dogrudan kataloga ekler. Arayuz artik
        # katalogu bellekte tutmadigi icin ekleme de sunucuda yapilmali.
        if parca.path == "/api/m3u-ice-aktar-kaydet":
            yeniler = m3u_ayristir(govde)
            if not yeniler:
                self._yanit(json.dumps({"hata": "metinde kanal bulunamadi"}), kod=400)
                return

            bekleyeni_yaz()
            katalog = katalog_oku()
            mevcut = set(k["url"] for k in katalog)
            eklenen = []
            for k in yeniler:
                if k["url"] in mevcut:
                    continue          # ayni adres iki kez durmasin
                mevcut.add(k["url"])
                _tamamla(k, kaynak="elle", secili=False)
                k["kaynak"] = "elle"
                eklenen.append(k)

            if eklenen:
                with _kilit:
                    _indeks["veri"] = None
                katalog_yaz(katalog + eklenen)
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] elle eklendi: {len(eklenen)} kanal "
                  f"({len(yeniler) - len(eklenen)} kopya atlandi)", flush=True)
            self._yanit(json.dumps({"tamam": True, "eklenen": len(eklenen),
                                    "atlanan": len(yeniler) - len(eklenen)}))
            return

        # Tek kanal duzenleme. Kimlik url; katalogdaki sira degisebiliyor.
        if parca.path == "/api/kanal":
            try:
                istek = json.loads(govde)
                url = istek["url"]
            except (ValueError, KeyError) as e:
                self._yanit(json.dumps({"hata": "istek okunamadi: %s" % e}), kod=400)
                return

            katalog = katalog_oku()
            hedef = next((k for k in katalog if k["url"] == url), None)
            if hedef is None:
                self._yanit(json.dumps({"hata": "kanal bulunamadi"}), kod=404)
                return

            if istek.get("sil"):
                kalan = [k for k in katalog if k is not hedef]
                with _kilit:
                    _indeks["veri"] = None
                katalog_yaz(kalan)
                self._yanit(json.dumps({"tamam": True, "silindi": True,
                                        "katalog": len(kalan),
                                        "secili": sum(1 for k in kalan if k.get("sec"))}))
                return

            for alan in ("ad", "sec", "logo", "ajan", "uyari"):
                if alan in istek:
                    hedef[alan] = istek[alan]
            if "gruplar" in istek:
                gruplar = [g.strip() for g in istek["gruplar"] if g.strip()] or ["Diger"]
                hedef["gruplar"] = gruplar
                hedef["grup"] = gruplar[0]
            if "yeniUrl" in istek and istek["yeniUrl"] != url:
                hedef["url"] = istek["yeniUrl"]

            with _kilit:
                _indeks["veri"] = None       # arama indeksi bayatladi
            kaydet_ertelenmis(katalog)
            self._yanit(json.dumps({"tamam": True,
                                    "secili": sum(1 for k in katalog if k.get("sec"))}))
            return

        # Filtreye uyan HER kanala uygulanan toplu islem. Filtre sunucuda
        # yeniden hesaplanir; tarayici 250 bin url gondermek zorunda kalmasin.
        if parca.path == "/api/toplu":
            try:
                istek = json.loads(govde)
                islem = istek["islem"]
                f = istek.get("filtre", {})
            except (ValueError, KeyError) as e:
                self._yanit(json.dumps({"hata": "istek okunamadi: %s" % e}), kod=400)
                return

            bekleyeni_yaz()
            katalog = katalog_oku()
            eslesen = katalogu_filtrele(
                katalog, q=f.get("q", ""), grup=f.get("grup", ""),
                kaynak=f.get("kaynak", ""), sec=f.get("sec", ""),
                durum=f.get("durum", ""))

            saat = datetime.datetime.now().strftime("%H:%M:%S")
            if islem in ("sec", "secme"):
                deger = islem == "sec"
                for _, k in eslesen:
                    k["sec"] = deger
                katalog_yaz(katalog)
                kalan = katalog
            elif islem == "sil":
                silinecek = set(id(k) for _, k in eslesen)
                kalan = [k for k in katalog if id(k) not in silinecek]
                with _kilit:
                    _indeks["veri"] = None
                katalog_yaz(kalan)
            else:
                self._yanit(json.dumps({"hata": "bilinmeyen islem: %s" % islem}), kod=400)
                return

            print(f"[{saat}] toplu {islem}: {len(eslesen)} kanal, "
                  f"katalogda {len(kalan)} kaldi", flush=True)
            self._yanit(json.dumps({"tamam": True, "etkilenen": len(eslesen),
                                    "katalog": len(kalan),
                                    "secili": sum(1 for k in kalan if k.get("sec"))}))
            return

        # Bir kaynaktan gelen tum kanallari sil. Sunucuda yapiliyor: 266 bin
        # satiri tarayiciya indirip orada silmek makul degil.
        if parca.path == "/api/kaynak-sil":
            try:
                hedef = json.loads(govde)["kaynak"]
            except (ValueError, KeyError) as e:
                self._yanit(json.dumps({"hata": "kaynak okunamadi: %s" % e}), kod=400)
                return

            katalog = katalog_oku()
            kalan = [k for k in katalog if (k.get("kaynak") or "elle") != hedef]
            silinen = len(katalog) - len(kalan)
            if silinen:
                katalog_yaz(kalan)
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] kaynak silindi: {hedef[:60]} -> {silinen} kanal, "
                  f"katalogda {len(kalan)} kaldi", flush=True)
            self._yanit(json.dumps({"tamam": True, "silinen": silinen,
                                    "katalog": len(kalan),
                                    "secili": sum(1 for k in kalan if k.get("sec"))}))
            return

        if parca.path == "/api/dene":
            urller = json.loads(govde)
            saat = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{saat}] {len(urller)} kanal deneniyor…", flush=True)
            sonuc = toplu_dene(urller)
            _test_sonuclari.update(sonuc)   # durum filtresi bunu kullaniyor
            self._yanit(json.dumps(sonuc))
            return

        self._yanit(json.dumps({"hata": "bulunamadi"}), kod=404)

    def log_message(self, *a):
        pass  # varsayilan erisim logunu sustur


def yerel_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


atexit.register(bekleyeni_yaz)


if __name__ == "__main__":
    katalog = katalog_oku()
    secili = sum(1 for k in katalog if k.get("sec"))
    ip = yerel_ip()
    print(f"Kanal yonetimi : http://{ip}:{PORT}/")
    print(f"Katalog        : {len(katalog)} kanal")
    print(f"TV'nin cektigi : http://{ip}:{PORT}/api/kanallar  ({secili} secili kanal)")
    print("Ctrl+C ile cik")
    http.server.ThreadingHTTPServer(("", PORT), Sunucu).serve_forever()
