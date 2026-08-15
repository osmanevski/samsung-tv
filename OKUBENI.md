# Samsung TV Kumanda

Bu klasör artık script'in **asıl kaynağıdır**. `~/.local/bin/tv` buraya symlink'tir,
yani `tv.py`'yi burada düzenlediğinizde terminaldeki `tv` komutu da anında değişir.

Klasörde git kurulu — her revizyondan sonra `git commit` yapıp geri dönebilirsiniz.

## Klasörde ne var

Bu depoda iki ayrı iş duruyor:

1. **Kumanda** (bu belge) — TV'yi ağ üzerinden kontrol eden script ve paneller.
2. **`tizen-iptv/`** — TV'nin kendisine kurulan IPTV uygulaması. Ayrı ve çok
   daha büyük bir iş; kendi belgesi var: **[`tizen-iptv/OKUBENI.md`](tizen-iptv/OKUBENI.md)**.
   Mimari, ölçülen sınırlar, tuzaklar ve hata ayıklama yöntemleri orada.

## Dosyalar

- `tv.py`  — Samsung Tizen TV'yi kontrol eden Python script'i
- `kumanda/` — tarayıcıdan çalışan kontrol paneli (aşağıda)
- `kamera/` — Mac kamerasını ev ağına yayınlayan ayrı araç
- `tizen-iptv/` — TV'ye kurulan IPTV uygulaması + Mac'teki yönetim sunucusu
- Yerel M3U listeleri `.gitignore` ile dışlanır; `PLAYLIST` değişkeniyle seçilir
- Token `~/.config/samsung-tv/token` içinde durur (git'e girmez, burada tutulmaz)

## Kullanım

    ./tv.py ping                 baglantiyi test et
    ./tv.py <url>                TV tarayicisini bu adreste ac
    ./tv.py key UP DOWN ENTER    kumanda tusu gonder
    ./tv.py text "merhaba"       acik metin kutusuna yaz
    ./tv.py apps                 acilabilen uygulamalari listele
    ./tv.py netflix              Netflix'i ac

## Kontrol paneli (tarayıcı kumandası)

    python3 kumanda/sunucu.py          http://localhost:8091/ adresinde açılır
    python3 kumanda/sunucu.py --ag     telefondan da girilebilsin diye ev ağına açar
    python3 kumanda/sunucu.py 9000     başka port

Sayfada yön tuşları, ses/kanal, medya tuşları, rakamlar, Netflix/YouTube,
TV'de adres açma ve metin yazma var. Klavye de çalışıyor: ok tuşları, Enter = OK,
Backspace = geri, Esc = çıkış, `+`/`-` ses, PgUp/PgDn kanal, `M` sessiz, 0-9 rakam.
Ses, kanal ve yön tuşlarını basılı tutunca tekrar eder.

`☀ AÇ` düğmesi TV'ye Wake-on-LAN sinyali yollar; TV'nin MAC adresi ilk seferde
ARP tablosundan bulunup `~/.config/samsung-tv/mac` içine yazılır. Çalışması için
TV'de Ayarlar → Genel → Ağ → Uzman → "Mobil Cihazla Aç" açık olmalı.

Sunucu TV'ye tek bir websocket bağlantısı kurup açık tutar, koparsa kendi
kendine yeniden bağlanır. Varsayılan olarak sadece bu bilgisayardan erişilir.

TV adresi varsayılan olarak `tv.local` kabul edilir.
Değiştirmek için: `TV_IP=tv-adresi ./tv.py ping`

Not: `token` bir kimlik bilgisidir, paylaşmayın.
