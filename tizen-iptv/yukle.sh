#!/bin/bash
# Uygulamayi paketleyip TV'ye kurar ve calistirir.
#
# "tizen build-web" CLI-only kurulumda Eclipse siniflarini bulamayip patliyor ve
# .buildResult'i guncellemiyor -- eski dosyalarla paketlemek sessiz bir tuzak.
# Bu yuzden kopyalamayi kendimiz yapiyoruz.
set -e

source ~/tizen-tools/env.sh
cd "$(dirname "$0")"

CIHAZ=${TIZEN_DEVICE:-tv}
SDB_ADRES=${TV_SDB_ADDRESS:-tv.local:26101}
UYGULAMA=PublicIptv.Iptv
PLAYLIST=${PLAYLIST:-../kanallar.m3u}

# Playlist'i JS'e goml. Widget file:// kokeninde calistigi icin calisma aninda
# dosya okumak guvenilir degil; metni gomup ayristirmayi TV'de yapiyoruz.
if [ -f "$PLAYLIST" ]; then
  python3 - "$PLAYLIST" > playlist.js <<'PY'
import json, sys
metin = open(sys.argv[1], encoding="utf-8").read()
print("/* yukle.sh tarafindan uretildi -- elle duzenleme, kaynak: %s */" % sys.argv[1])
print("var PLAYLIST_METIN = %s;" % json.dumps(metin, ensure_ascii=False))
PY
  echo "playlist gomuldu: $PLAYLIST ($(grep -c '^#EXTINF' "$PLAYLIST") kanal)"
else
  echo "UYARI: $PLAYLIST bulunamadi, onceki playlist.js kullanilacak"
fi

sdb connect "$SDB_ADRES" >/dev/null 2>&1 || true

rm -rf .buildResult
mkdir -p .buildResult

# IZIN LISTESI, dislama listesi degil. Dislama kullanirken veri dosyasinin adi
# kanallar.json -> katalog.json olarak degisti ve dislama guncellenmedi; 108 MB'lik
# katalog sessizce pakete girip kurulumu 118003 ile patlatti. Uygulamaya ait
# dosyalari tek tek saymak bu hatayi imkansiz kiliyor.
UYGULAMA_DOSYALARI=(config.xml index.html uygulama.js m3u.js playlist.js
                    stil.css icon.png logo.png)

for d in "${UYGULAMA_DOSYALARI[@]}"; do
  if [ ! -f "$d" ]; then
    echo "HATA: uygulama dosyasi eksik: $d" >&2
    exit 1
  fi
  cp "$d" .buildResult/
done

BOYUT=$(du -sk .buildResult | cut -f1)
if [ "$BOYUT" -gt 5120 ]; then
  echo "HATA: paket icerigi ${BOYUT} KB — beklenenden buyuk, bir veri dosyasi karismis olabilir" >&2
  exit 1
fi
echo "paketlenecek: ${#UYGULAMA_DOSYALARI[@]} dosya, ${BOYUT} KB"

tizen package -t wgt -s "${TIZEN_PROFILE:-default}" -o . -- .buildResult | tail -2

# Kurulum ciktisini tail'e borulamak hatayi gizliyordu: boru hattinin cikis kodu
# tail'inki oluyor, `tizen install` patlasa bile betik devam edip eski surumu
# calistiriyor ve "basarili" diyordu. Ciktiyi once dosyaya al, sonra denetle.
tizen install -n IPTV.wgt -t "$CIHAZ" > /tmp/tizen-kurulum.log 2>&1
if grep -q "Failed to install" /tmp/tizen-kurulum.log; then
  echo "HATA: kurulum basarisiz" >&2
  grep -E "install failed|error|Failed" /tmp/tizen-kurulum.log >&2
  exit 1
fi
tail -2 /tmp/tizen-kurulum.log

tizen run -p "$UYGULAMA" -t "$CIHAZ" | tail -1
