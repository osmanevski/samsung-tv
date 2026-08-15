#!/usr/bin/env python3
"""Katalogdaki kanallari Turkce kategorilere yeniden ayirir.

Playlist'ten gelen `group-title` degerleri ise yaramiyordu: 184 kanalin 95'i
"Diger" ve "General" kovalarindaydi, etiketler Ingilizce ve tutarsizdi
(Animation 1 kanal, Series 2 kanal).

Once ada gore acik eslesme, sonra kural tabanli tahmin, kalanlar "Diger".
Emin olunmayanlar ekrana basilir; yonetim arayuzunden elle duzeltilebilir.

Kullanim:  python3 kategorile.py [--uygula]
Argumansiz calistirinca yalnizca ne yapacagini gosterir, dosyaya dokunmaz.
"""
import json
import os
import re
import sys

KOK = os.path.dirname(os.path.abspath(__file__))
KATALOG = os.path.join(KOK, "katalog.json")

# Kanal adinin basi (kucuk harfe cevrilmis, "(1080p)" gibi ekler atilmis) -> kategori
ACIK = {
    # --- Ulusal genel yayin ---
    "trt 1": "Ulusal", "trt 2": "Ulusal", "trt 3": "Ulusal",
    "trt turk": "Ulusal", "trt avaz": "Ulusal", "trt kurdi": "Ulusal",
    "atv": "Ulusal", "a2tv": "Ulusal", "kanal d": "Ulusal", "euro d": "Ulusal",
    "star tv": "Ulusal", "tv 8": "Ulusal", "now tv": "Ulusal", "teve2": "Ulusal",
    "beyaz tv": "Ulusal", "flash tv": "Ulusal", "tv4": "Ulusal",
    "kanal 7": "Ulusal", "kanal 7 avrupa": "Ulusal", "360 tv": "Ulusal",
    "4u tv": "Ulusal", "tivi 6": "Ulusal",

    # --- Haber ---
    "24 tv": "Haber", "a haber": "Haber", "akit tv": "Haber",
    "haberturk tv": "Haber", "halk tv": "Haber", "tele 1": "Haber",
    "tv 100": "Haber", "tvnet": "Haber", "ulke tv": "Haber",
    "trt haber": "Haber", "tgrt haber": "Haber", "haber global": "Haber",
    "turkhaber": "Haber", "tv 24": "Haber", "dha": "Haber",
    "flash haber tv": "Haber", "tbmm tv": "Haber", "ntv": "Haber",

    # --- Spor ---
    "a spor": "Spor", "htspor tv": "Spor", "trt spor": "Spor",
    "trt spor yildiz": "Spor", "tabii spor 6": "Spor",
    "s sport": "Spor", "s sport 2": "Spor", "fb tv": "Spor",
    "tjk tv": "Spor", "tjk tv 2": "Spor", "satranc tv": "Spor",

    # --- Cocuk ---
    "trt cocuk": "Çocuk", "trt diyanet cocuk": "Çocuk",
    "minika cocuk": "Çocuk", "minika go": "Çocuk",
    "babytv turkiye": "Çocuk", "disney jr.": "Çocuk", "zarok tv": "Çocuk",

    # --- Belgesel ---
    "trt belgesel": "Belgesel", "tgrt belgesel tv": "Belgesel",
    "national geographic": "Belgesel", "national geographic wild": "Belgesel",
    "bbc earth turkiye": "Belgesel", "cgtn documentary": "Belgesel",
    "natural tv": "Belgesel", "gzt": "Belgesel",

    # --- Muzik ---
    "trt muzik": "Müzik", "kral pop tv": "Müzik", "dream turk": "Müzik",
    "med muzik": "Müzik", "kn music tv": "Müzik",
    "number 1 turk": "Müzik", "number 1 tv": "Müzik", "number 1 ask": "Müzik",
    "number 1 damar": "Müzik", "number 1 dance": "Müzik",
    "power tv": "Müzik", "power turk": "Müzik", "power dance": "Müzik",
    "power love": "Müzik", "power turk akustik": "Müzik",
    "power turk slow": "Müzik", "power turk taptaze": "Müzik",

    # --- Sinema ve dizi ---
    "fx": "Sinema & Dizi", "filmbox": "Sinema & Dizi",
    "moviesmart turk": "Sinema & Dizi", "bbc first turkiye": "Sinema & Dizi",

    # --- Ekonomi ---
    "bloomberg ht": "Ekonomi", "bloomberght": "Ekonomi",
    "cnbc-e": "Ekonomi", "finans turk tv": "Ekonomi",

    # --- Egitim ---
    "trt eba ilkokul": "Eğitim", "trt eba ortaokul": "Eğitim",
    "trt eba lise": "Eğitim",

    # --- Dini ---
    "diyanet tv": "Dini", "lalegul tv": "Dini", "semerkand tv": "Dini",
    "dost tv": "Dini", "diyar tv": "Dini", "ilke tv": "Dini",
    "meltem tv": "Dini", "vav tv": "Dini", "sat7 turk": "Dini",
    "hilal tv": "Dini", "kanal hayat": "Dini", "yol tv": "Dini",

    # --- Yasam ---
    "ciftci tv": "Yaşam", "fortuna tv": "Yaşam", "rtg int.": "Yaşam",
    "sercem tv": "Yaşam", "bizimev tv": "Yaşam", "tempo tv": "Yaşam",

    # --- Yabanci / uluslararasi ---
    "elsharq tv": "Yabancı", "mekameleen tv": "Yabancı",
    "almahriah tv": "Yabancı", "persiana turkiye": "Yabancı",
    "al rafidain": "Yabancı", "al-zahra tv turkic": "Yabancı",
    "luys tv": "Yabancı", "qaf tv": "Yabancı",

    # --- Yerel, adindan sehir anlasilmayanlar ---
    "kay tv": "Yerel",        # Kayseri
    "er tv": "Yerel",         # Erzurum
    "sun rtv": "Yerel",       # Adana
    "ton tv": "Yerel",        # Trabzon
    "kanal firat": "Yerel",   # Elazig
    "life tv": "Yerel",       # Izmir

    "mux test vod": "Test",
}

# Yerel yayin: sehir/ilce adi tasiyanlar
SEHIRLER = [
    "adana", "alanya", "anadolu", "antalya", "aras", "bursa", "cay", "cekmekoy",
    "deniz postasi", "edessa", "erzurum", "es tv", "etv kayseri", "etv manisa",
    "guneydogu", "haber61", "hunat", "icel", "karadeniz", "kayseri", "kocaeli",
    "konya", "mavikaradeniz", "olay", "trabzon", "urfa", "van 65", "altas",
    "benguturk", "kent turk", "aksu",
]

# "Kanal 23", "TV 41" gibi numarali adlar Turkiye'de neredeyse her zaman yerel
NUMARALI = re.compile(r"^(kanal|tv|tivi)\s*\d+$")


def sadelestir(ad):
    """"TRT Çocuk (720p)" -> "trt cocuk". Cozunurluk eki ve Turkce karakterler gider."""
    ad = re.sub(r"\s*\(\d+p\)\s*", " ", ad)
    ad = re.sub(r"\s*\[[^\]]*\]\s*", " ", ad)
    ad = ad.strip().lower()
    for a, b in [("ç", "c"), ("ğ", "g"), ("ı", "i"), ("ö", "o"),
                 ("ş", "s"), ("ü", "u"), ("î", "i"), ("â", "a")]:
        ad = ad.replace(a, b)
    return re.sub(r"\s+", " ", ad)


def kategori_bul(ad):
    sade = sadelestir(ad)

    if sade in ACIK:
        return ACIK[sade], "acik"

    # "Habertürk TV (720p)" ile "Habertürk TV (1080p)" ayni kanal
    for anahtar, kat in ACIK.items():
        if sade == anahtar or sade.startswith(anahtar + " "):
            return kat, "acik"

    for sehir in SEHIRLER:
        if sehir in sade:
            return "Yerel", "kural: sehir adi"

    if NUMARALI.match(sade):
        return "Yerel", "kural: numarali ad"

    if "spor" in sade or "sport" in sade:
        return "Spor", "kural: ad"
    if "haber" in sade or "news" in sade:
        return "Haber", "kural: ad"
    if "muzik" in sade or "music" in sade:
        return "Müzik", "kural: ad"
    if "cocuk" in sade or "kids" in sade:
        return "Çocuk", "kural: ad"
    if "belgesel" in sade:
        return "Belgesel", "kural: ad"

    return "Diğer", "eslesmedi"


def main():
    uygula = "--uygula" in sys.argv
    katalog = json.load(open(KATALOG, encoding="utf-8"))

    dagilim, emin_degil = {}, []
    for k in katalog:
        kat, nasil = kategori_bul(k["ad"])
        k["grup"] = kat
        k["gruplar"] = [kat]
        dagilim[kat] = dagilim.get(kat, 0) + 1
        if nasil != "acik":
            emin_degil.append((k["ad"], kat, nasil, k["sec"]))

    print("=== yeni dagilim ===")
    for kat, n in sorted(dagilim.items(), key=lambda x: -x[1]):
        print(f"  {kat:<16} {n}")

    print(f"\n=== acik eslesme disinda kalanlar ({len(emin_degil)}) ===")
    for ad, kat, nasil, secili in emin_degil:
        isaret = "TV" if secili else "  "
        print(f"  {isaret} {ad:<42} -> {kat:<12} ({nasil})")

    if uygula:
        json.dump(katalog, open(KATALOG, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"\nkatalog.json guncellendi ({len(katalog)} kanal)")
    else:
        print("\n(deneme calistirmasi — dosya degismedi, uygulamak icin: --uygula)")


if __name__ == "__main__":
    main()
