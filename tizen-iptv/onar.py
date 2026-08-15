#!/usr/bin/env python3
"""Bozulmus katalog.json'dan kurtarilabilen kanallari toplar.

Eszamanli iki yazma ayni gecici dosyayi kullandiginda dosya birbirine giriyor
ve `json.load` tamamini reddediyor. Oysa kayitlarin buyuk cogunlugu saglam.

`indent=2` ile yazildigi icin her kayit satir basinda iki bosluk + '{' ile
basliyor; dosyayi buradan bolup her parcayi tek tek ayristiriyoruz. Bozulan
yalnizca eklenme noktasindaki birkac kayit oluyor.

Kullanim:  python3 onar.py [girdi] [cikti]
"""
import json
import os
import sys

KOK = os.path.dirname(os.path.abspath(__file__))


def onar(girdi, cikti):
    metin = open(girdi, encoding="utf-8", errors="replace").read()
    print(f"okundu: {len(metin):,} karakter")

    parcalar = metin.split("\n  {")
    print(f"aday kayit: {len(parcalar) - 1:,}")

    saglam, bozuk = [], 0
    for i, p in enumerate(parcalar):
        if i == 0:
            continue                     # dizinin acilisi
        govde = "{" + p
        govde = govde.rstrip()
        for son in ("},", "}"):          # kayit sonundaki virgul / dizi kapanisi
            if govde.endswith(son):
                govde = govde[:-len(son)] + "}"
                break
        else:
            kesim = govde.rfind("\n  }")
            if kesim == -1:
                bozuk += 1
                continue
            govde = govde[:kesim] + "\n  }"

        try:
            k = json.loads(govde)
        except ValueError:
            bozuk += 1
            continue
        if isinstance(k, dict) and k.get("url"):
            saglam.append(k)
        else:
            bozuk += 1

    # Bolunme noktasinda ayni kayit iki kez cikmis olabilir
    gorulen, benzersiz = set(), []
    for k in saglam:
        if k["url"] in gorulen:
            continue
        gorulen.add(k["url"])
        benzersiz.append(k)

    print(f"kurtarilan: {len(saglam):,} | benzersiz: {len(benzersiz):,} | bozuk: {bozuk}")
    secili = sum(1 for k in benzersiz if k.get("sec"))
    print(f"secili (TV'ye giden): {secili}")

    json.dump(benzersiz, open(cikti, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"yazildi: {cikti}")
    return benzersiz


if __name__ == "__main__":
    g = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KOK, "katalog.json")
    c = sys.argv[2] if len(sys.argv) > 2 else os.path.join(KOK, "katalog.onarilmis.json")
    onar(g, c)
