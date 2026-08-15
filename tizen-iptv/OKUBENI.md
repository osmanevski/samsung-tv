# Tizen IPTV — Samsung TV için kendi IPTV uygulaması

Tizen 4.0 ve üzeri Samsung TV'lerde çalışmak üzere geliştirilmiş IPTV
uygulaması. Kanal listesi bilgisayardaki bir yönetim sunucusundan gelir.

Bu belge **devretmek için** yazıldı: yeni bir oturuma, başka bir yapay zekaya ya
da altı ay sonraki kendine. Bilinmesi gereken ama koda bakarak anlaşılmayan her
şey burada. Ölçümler bu TV'de yapıldı, tahmin değil.

---

## 1. Sistem nasıl çalışıyor

```
Bilgisayar (computer.local)                TV (tv.local)
┌─────────────────────────┐                ┌──────────────────────┐
│ sunucu.py  :8099        │                │  PublicIptv.Iptv     │
│  ├ /            yönetim │◀── tarayıcı    │   ├ uygulama.js      │
│  ├ /api/ara  filtre+syf │                │   ├ m3u.js           │
│  ├ /api/facet  seçenek  │                │   └ AVPlay (webapis) │
│  ├ /api/kanal  düzenle  │                │                      │
│  ├ /api/toplu  toplu iş │                │                      │
│  ├ /api/kaynaklar özet  │                │                      │
│  ├ /api/kanallar seçili │───── XHR ─────▶│                      │
│  └ /?m=…      TV logları│◀── beacon ─────│                      │
│                         │                └──────────────────────┘
│ katalog.json            │                        ▲
└─────────────────────────┘                        │
                                              sdb / .wgt kurulumu
```

Kanal listesi **üç kademeli** alınır: sunucu → `localStorage` önbelleği →
pakete gömülü `playlist.js`. Mac her zaman açık olmayacağı için ilk kademeye
güvenilemez. Sunucu kapalıyken önbellekten açıldığı test edildi.

---

## 2. Hızlı başlangıç

```bash
# 1) Yönetim sunucusu (kanal listesi + TV logları) — açık kalmalı
python3 tizen-iptv/sunucu.py
#    Zaten çalışan varsa port dolu hatası verir. Süreç adı sadece "sunucu.py"
#    olduğu için `pkill -f tizen-iptv/sunucu.py` TUTMAZ; porta göre öldür:
#    for p in $(lsof -nP -iTCP:8099 -sTCP:LISTEN -t); do kill -9 $p; done
#    Yönetim arayüzü:  http://computer.local:8099/

# 2) Uygulamayı derleyip TV'ye kur ve çalıştır
./tizen-iptv/yukle.sh
```

`yukle.sh` her şeyi yapar: playlist'i gömer, paketler, imzalar, kurar, başlatır.

TV'de kanal listesini yenilemek için **kırmızı tuş** — yeniden kurmaya gerek yok.

---

## 3. Dosyalar

| Dosya | Görevi |
|---|---|
| `index.html` | Uygulama iskeleti. Video için `<object type="application/avplayer">` |
| `uygulama.js` | Oynatıcı, kanal listesi, tuşlar, hata kurtarma, favoriler, numara girişi |
| `m3u.js` | M3U/M3U8 ayrıştırıcı (`tvg-logo`, `group-title`, `http-user-agent`, `[Geo-blocked]` notları) |
| `stil.css` | Tüm stiller. **Inline stil çalışmaz**, bkz. Tuzak 1 |
| `config.xml` | Widget tanımı. `required_version="4.0"` |
| `playlist.js` | **Üretilmiş dosya**, elle düzenleme. `yukle.sh` `.m3u`'yu gömer. Sadece son çare yedek |
| `sunucu.py` | Mac'teki yönetim sunucusu + TV log toplayıcı (port 8099) |
| `yonetim.html` | Tarayıcıdan kanal yönetimi. Pakete girmez |
| `katalog.json` | Tüm kanallar + `sec` işareti. Asıl veri burada |
| `kategorile.py` | Kanalları Türkçe kategorilere ayırır (`--uygula` ile yazar) |
| `yukle.sh` | Paketle + kur + çalıştır |
| `inceleyici.py` | TV'de JS çalıştırır (Web Inspector / CDP). Hata ayıklamanın tek yolu |
| `onar.py` | Bozuk `katalog.json`'dan kurtarılabilen kayıtları toplar |
| `logo.png`, `icon.png` | Marka görselleri |

---

## 4. Ortam

| | |
|---|---|
| TV | Tizen 4.0+, örnek ad: `tv.local` |
| Bilgisayar | Örnek ad: `computer.local` |
| Uygulama kimliği | `PublicIptv.Iptv` |
| sdb | `sdb connect "$TV_IP:26101"` |
| Sertifika | Kendi Tizen author sertifikanız |
| Security profile | `TIZEN_PROFILE` ortam değişkeni; varsayılan `default` |
| Araçlar | `~/tizen-studio` (CLI), ortam: `source ~/tizen-tools/env.sh` |

**Samsung sertifikası, Samsung hesabı ve DUID kaydı GEREKMİYOR.** Bu TV düz Tizen
author sertifikasını kabul ediyor. Eclipse'li Tizen Studio da gereksiz, CLI yeter.
TV Extension 4.0 artık indirilemiyor ama gerek de yok.

**Kırılganlık — Mac'in IP'si üç yere gömülü.** Değişirse üçünü de güncelle:

1. `uygulama.js` içindeki `MAC` sabiti (TV kanal listesini buradan çeker)
2. TV'nin Developer Mode **Host PC IP** alanı (`sdb connect` buna bakar)
3. Panelin açıldığı adres

Wi-Fi'de **Özel Wi-Fi Adresi ağ başına** bir ayardır. Ağ değişince bilgisayarın
IP adresi de değişebilir ve panel erişilemez görünebilir. Teşhis yolu: önce
`127.0.0.1` ile dene; yanıt veriyorsa sorun ağ yapılandırmasındadır.

---

## 5. Bu TV'de ölçülen sınırlar

| Kanal | JSON | parse | filtre | grup çıkarma |
|---|---|---|---|---|
| 1.000 | 0,2 MB | 7 ms | 9 ms | 4 ms |
| 10.000 | 2,05 MB | 74 ms | 5 ms | 13 ms |
| 57.000 | 11,9 MB | 449 ms | 25 ms | 62 ms |

- **CPU sorun değil.** 57 bin kanal açılışta bir kez ~450 ms.
- **Bellek sorun değil.** 57 bin nesne tutulurken uygulama yanıt veriyor.
  (`performance.memory` bu derlemede donmuş, 9.5 MB'da sabit — güvenme.)
- **`localStorage` 5,1 MB'da doluyor.** Asıl duvar bu.
- Gerçek sınır teknik değil kullanılabilirlik: 910 kategori şeride sığmıyor,
  57 bin satır kumandayla gezilemiyor. **TV'de pratik üst sınır ~2.000 kanal.**

**Katalog tarafı ayrı bir ölçek.** Xtream panelleri 250 bin+ kanal döndürebiliyor;
gerçek bir çekimde katalog 280.053 kanala ve `katalog.json` 128 MB'a çıktı. Bunun
sonuçları ve alınan önlemler:

- `sunucu.py` katalogu **bellekte önbelleğe alır** (mtime + boyut ile geçersizler).
  Olmasaydı her `/api/kanallar` isteğinde 128 MB parse edilirdi (~1 sn) — TV'nin
  XHR zaman aşımı 4 sn, yani katalog bir kat büyüse TV önbelleğe düşerdi.
- **Yönetim arayüzü katalogu hiç indirmez.** Filtreleme, arama ve sayfalama
  sunucuda yapılır (`/api/ara`); tarayıcıya yalnızca görünen 100 satır iner.
  İlk tasarımda katalogun tamamı tarayıcıya iniyordu ve 20.000 kanalda duvara
  çarpıyordu; bu sınır kaldırıldı.
- Ölçüm (sentetik 250.000 kanal, 67 MB): ilk sayfa 0,70 sn / **30 KB**,
  arama 0,05 sn, grup+arama 0,04 sn, 2500. sayfaya atlama 0,27 sn,
  `/api/facet` 0,09 sn / 652 bayt.
- **"Kaydet" yok.** 250 bin kanalı tarayıcıda tutup topluca kaydetmek mümkün
  olmadığı için her değişiklik anında sunucuya yazılır. Yazmalar biriktirilip
  1,5 sn'lik duraklamadan sonra tek seferde diske geçer (`kaydet_ertelenmis`);
  toplu işlemler ve silmeler hemen yazılır, çıkışta `atexit` bekleyeni boşaltır.
- Toplu işlemler filtreyi **sunucuda yeniden hesaplar** (`/api/toplu`);
  tarayıcı 250 bin url göndermek zorunda değil.
- Denetleme yalnızca görünen sayfaya uygulanır; 250 bin kanalı denemek saatler
  sürer. Sonuçlar sunucuda tutulur, "durum" filtresi onları kullanır.

---

## 6. Tuzaklar

Hepsi yaşandı. Tekrar düşmemek için.

**1 — Inline `<script>` ve `<style>` çalışmaz.**
Tizen'in varsayılan CSP'si `'self'` diyor. Belirti: uygulama açılıyor ama
**tamamen siyah ekran**. DOM aslında dolu; stil uygulanmadığı için siyah zemine
siyah yazı çıkıyor ve JS hiç çalışmıyor. Tüm CSS/JS harici dosyada olmalı.
Uzak `<script>` de engellenir — bu yüzden JSONP kullanılamaz, XHR + CORS şart.

**2 — `tizen build-web` patlıyor ve `.buildResult`'ı güncellemiyor.**
CLI-only kurulumda `ClassNotFoundException: org.eclipse.core.runtime.Plugin`.
Sessiz tuzak: `tizen package` eski dosyalarla paketleyip **başarıyla** bitiyor,
değişiklikler TV'ye hiç gitmiyor. `yukle.sh` kopyalamayı kendi yapıyor, hep onu kullan.

**3 — Sayfa zemini şeffaf olmalı.**
AVPlay video karesini web katmanının **arkasındaki** donanım düzlemine çiziyor.
Opak bir `background` videoyu tamamen örter. Açılış ekranı bu yüzden üç ayrı
yerden kapatılıyor (görüntü geldi / kanal ölü / kullanıcı tuşa bastı).

**4 — `prepareAsync` ölü yayında sessizce asılır.**
Ne başarı ne hata callback'i gelir; 24 TV'de 44 saniye beklendi. Kendi zaman
aşımı bekçin olmadan kullanıcı "bağlanılıyor" ekranında kilitli kalır
(`HAZIRLIK_ASIMI = 12000`).

**5 — `localStorage` kota aşımı uygulamayı kilitliyor.**
Temiz bir `QuotaExceededError` vermiyor. 11,9 MB'lık bir yazma denemesi TV'yi
kilitledi, yeniden başlatmak gerekti. `onbellegeYaz()` yazmadan önce boyuta
bakıyor (`ONBELLEK_SINIRI = 3 MB`). **Bu korumayı kaldırma.**

**6 — TV'de `dlog` ve `sdb shell` kapalı.**
Samsung perakende modelinde "closed" döner. Sadece `sdb shell 0 <komut>`
arayüzü çalışır: `0 was_kill`, `0 debug`.

**7 — Grup şeridine başa öğe eklemek `grupIndeks`'i kaydırır.**
Favoriler eklenince açılışta aktif grup boş Favoriler oldu, liste bomboş göründü.
`gruplariHazirla()` aktif grubu **indeksle değil adla** korur.

**8 — Eşzamanlı yazma katalogu bozar.**
`sunucu.py` çok iş parçacıklı. İki yazma aynı anda çalışıp aynı geçici dosyaya
yazınca dosya birbirine giriyor ve `json.load` tamamını reddediyor — 113 MB'lık
katalog bir kez böyle bozuldu ve sunucu açılamaz hale geldi. Belirti: kayıt
ortasında kesilip başka bir kaydın devam etmesi
(`"kaynak": "...&output,\n "grup": ...`).
Önlem: `_dosya_kilidi` ile yazmalar sıraya alınıyor **ve** her yazma kendi
geçici adını kullanıyor (`katalog.json.<pid>.<tid>.tmp`). İkisi de gerekli.
Ayrıca `katalog_oku()` artık bozuk dosyada ölmüyor: `onar.py` ile kurtarmayı
deniyor, olmazsa bozuğu kenara koyup boş katalogla açılıyor.

`onar.py` — bozuk katalogdan kurtarılabilenleri toplar. `indent=2` ile
yazıldığı için her kayıt `\n  {` ile başlıyor; dosya buradan bölünüp her parça
tek tek ayrıştırılıyor. Gerçek kurtarmada 243.697 adaydan 234.139 benzersiz
kanal kurtarıldı, 60 kayıt okunamadı.

**9 — Paketleme dışlama listesiyle yapılmamalı.**
`yukle.sh` önce "şunlar hariç her şeyi paketle" diyordu. Veri dosyasının adı
`kanallar.json` → `katalog.json` olarak değişince dışlama güncellenmedi ve
108 MB'lık katalog sessizce pakete girdi. Belirti: `install failed[118003]`.
Üstelik `tizen install | tail -2` kullanıldığı için boru hattının çıkış kodu
`tail`'inki oluyor, betik hatayı yutup **eski sürümü çalıştırıyor ve
"başarılı" diyordu** — TV'de neden değişiklik görünmediği anlaşılmıyordu.
Şimdi `yukle.sh` uygulama dosyalarını **tek tek sayıyor** (izin listesi),
paket 5 MB'ı aşarsa duruyor ve kurulum çıktısını denetleyip hata varsa
`exit 1` veriyor. Sağlıklı paket ~79 KB.

**10 — python.org kurulumunda kök sertifika demeti boş.**
Her https isteği `CERTIFICATE_VERIFY_FAILED` verir. `sunucu.py` `certifi`
demetini açıkça kullanıyor (`SSL_BAGLAM`).

---

## 7. Kanal listesi akışı

`katalog.json` **her şeyi** tutar (Mac'te kalır). Her kayıtta:

```json
{ "ad": "...", "url": "...", "grup": "Haber", "gruplar": ["Haber"],
  "logo": "...", "id": "...", "ajan": "", "uyari": "",
  "kaynak": "elle | <çekildiği URL>", "sec": true }
```

`/api/kanallar` yalnızca `sec: true` olanları, `sec` ve `kaynak` alanları
atılmış halde döner — her bayt önbellek sınırından yiyor.

**Uzak kaynaktan güncelleme** (`/api/kaynak-cek`): kimlik **url**'dir.
Aynı url'in `sec` işareti korunur; elle eklenenler ve başka kaynaklar dokunulmaz
ve url'leriyle kopyayı engeller; bu kaynaktan gelip artık listede olmayanlar düşer.
(Kopya engeli olmadan aynı kanal listede iki kez çıkıyordu.)

**Kontrol panelinde filtreler:** arama (ad, grup, adres ve **kaynak** alanını
tarar), grup, TV'de seçili/seçisiz, **kaynak** (alan adı + kanal sayısı ile
listelenir), test durumu. Hepsi birlikte çalışır. Toplu seçim ve toplu silme
o an filtreye uyan **tüm** kanallara uygulanır, yalnızca görünen sayfaya değil.
Arayüz metinlerinde "süzme" değil **"filtreleme"** sözcüğü kullanılıyor.

**Toplu temizlik** iki yoldan:
`/api/kaynak-sil` bir kaynaktan gelen tüm kanalları sunucuda siler (arayüzde
`Kaynaklar` penceresi) — **anında kalıcıdır**, Kaydet beklemez.
Arayüzdeki `Süzülenleri sil` ise süzgece uyanları tarayıcıda siler, Kaydet'e
kadar geri alınabilir (sayfayı yenilemek yeter).

## 8. Canlı yayın mı film mi (`tur` alanı)

Katalogdaki her kayıtta `tur` var: `canli` · `film` · `dizi`.
Sunucu **adrese bakarak** belirliyor (`tur_bul`), grup adına değil:

```
film  : http://…/movie/USER/PASS/2909748.mp4     → /movie/ yolu
dizi  : http://…/series/USER/PASS/…              → /series/ yolu
film  : …/herhangi.mp4|.mkv|.avi|…               → video uzantısı
canlı : http://…/USER/PASS/221029.m3u8           → diğer her şey
```

Grup adına bakmak yanıltıcıydı: "Movie-Drama" adında canlı kanal da olabiliyor.

**Bölümler.** TV'de üst düzey bölümler var: **Favoriler · Canlı · Filmler ·
Diziler**, **MAVİ** tuşla değişir. Boş bölüm gösterilmez (Favoriler hariç).
Grup şeridi yalnızca aktif bölümün gruplarını gösterir — yoksa Filmler'deyken
canlı kanal grupları da şeritte çıkıyordu. Açılışta Canlı bölümü seçili.
Ölçüldü: Canlı 192 kanal / 16 grup, Filmler 4.470 kanal / 1 grup, sızma yok.

**TV'de sonuçları:**
- **Kanal numarası yalnızca canlı kanallara verilir.** 4.470 film numaraları
  şişirip canlı kanalların numaralarını kullanılamaz hale getiriyordu.
  Listede filmlerde numara yerine **▶** çıkar. `numaraliKanallar` dizisi
  numaralamanın tek kaynağı.
- **Kaldığı yerden devam.** İzleme konumu url bazlı `localStorage`'da
  (`izlemeKonumlari`), 15 sn'de bir ve kanal değişimi / duraklatma anında
  yazılır. İlk dakika ve son 2 dakika kaydedilmez (anlamsız); film bitince
  kayıt silinir ki bir dahakine baştan başlasın.
  Doğrulandı: 3:38'de bırakılan film dönüşte 3:38'den devam etti.

## 9. Filmler neden canlı yayın kadar iyi çalışmıyor

Test ortamında ölçüldü. Kısa cevap: **uygulamada eksik yok, kaynak dosyalarda var.**

| Bulgu | Ölçüm |
|---|---|
| Ölü film oranı | **%60** (sıralı, tek bağlantıyla 25 filmde 10 çalıştı) |
| MKV | 0/4 çalıştı — hem ölü oranı yüksek hem AVPlay'de zayıf |
| Video kodeği | okunabilen her dosyada **H.264** — sorun değil |
| Ses kodeği | okunabilenlerde **AAC** — sorun değil |
| `moov` konumu | **dosyanın sonunda**, ~2,5 MB indeks → açılış ve sarma yavaş |
| Eş zamanlı bağlantı | **1** — başka bir istek yayını düşürüyor |
| VOD için HLS | **yok**; `.m3u8`, `.ts`, uzantısız — hepsi ham mp4 dönüyor |

Canlı yayın hızlı çünkü HLS AVPlay'in en güçlü yolu: küçük manifest, önceden
kesilmiş parçalar, indeks manifestte. İlerlemeli bir MP4'te indeks dosyanın
sonunda; oynatıcı başlamadan önce kuyruğu çekmek zorunda.

**Tuzak:** sağlayıcı ölü filmlerde **HTTP 200 + HTML hata sayfası** dönüyor.
Yalnızca durum koduna bakan bir denetleme bunları "çalışıyor" sayar. `url_dene`
artık içerik türüne ve ilk baytlara da bakıyor, `-1` (video değil) döndürüyor.

**Yapılabilecekler (yapılmadı):** ölüleri ayıklamak (Denetle → durum
"çalışmayanlar" → Filtrelenenleri sil), ve kalanlar için Mac'te ffmpeg ile
anlık remux — `moov`'u başa almak ya da HLS'e çevirmek TV'ye tam istediğini
verir. İkincisi ffmpeg, CPU ve Mac'in açık olmasını gerektirir.

**Sınır:** HLS VOD (`.m3u8` ama `#EXT-X-PLAYLIST-TYPE:VOD`) adresten ayırt
edilemiyor, `canli` görünür. Oynatma etkilenmez — oynatıcı VOD'u çalışma anında
`getDuration()` ile zaten anlıyor; yalnızca numara/rozet yanlış olur.

**Kategoriler** playlist'in `group-title` değerlerinden gelmiyor — onlar
kullanılamazdı (184 kanalın 95'i "Diger"/"General"). `kategorile.py` Türkçe
taksonomiye çeviriyor: Ulusal, Haber, Spor, Sinema & Dizi, Belgesel, Çocuk,
Müzik, Yerel, Dini, Ekonomi, Eğitim, Yaşam, Yabancı, Test, Diğer.
En büyük kazanç **Yerel** (48 kanal) — Türkiye playlist'lerinin yarısı yerel istasyon.
Şerit sırası `uygulama.js` içindeki `GRUP_SIRASI` ile belirlenir.

---

## 10. Kumanda tuşları

| Tuş | Liste kapalı | Liste açık |
|---|---|---|
| **OK** | canlıda liste açar, VOD'da oynat/duraklat | seçili kanalı aç |
| **▲ ▼** | liste açar | listede gezin |
| **◀ ▶** | VOD'da ±30 sn sar | grup değiştir |
| **0-9** | kanal numarası gir | numarayı listede bul |
| **CH+ / CH−** | önceki/sonraki kanal (aktif gruptan) | — |
| **MAVİ** | listeyi açıp bölüm değiştir | bölüm değiştir (Canlı/Filmler/Diziler) |
| **YEŞİL** | aramayı aç | aramayı aç / kutuya dön |
| **SARI** | oynayanı favoriye ekle/çıkar | seçiliyi favoriye ekle/çıkar |
| **KIRMIZI** | listeyi sunucudan yenile | aynı |
| **RETURN** | **önceki kanala dön** (tekrar basınca geri gelir) | listeyi (veya aramayı) kapat |
| **EXIT** | uygulamadan çık | — |

**RETURN = önceki kanal.** Zap yaparken en çok gereken davranış: iki kanal
arasında gidip gelmek. `kanalAc` her gerçek kanal değişiminde `oncekiKanal`'ı
tazelediği için tekrar basınca geri dönülür. Yeniden deneme ve açılıştaki ölü
kanal atlamaları kaydedilmez — onlar dönülecek yer değil.
Bilgi çubuğunda `RETURN → <kanal adı>` yazıyor.

Çıkış **EXIT** tuşuyla. Emniyet: hiç kanal değiştirilmemişse (dönülecek yer yok)
RETURN yine çıkarır, yoksa uygulamada kilitli kalma ihtimali olurdu.

**Arama.** YEŞİL ile açılır, grup şeridinin yerini alır (arama tüm gruplarda
dolaşır). Metin kutusuna odaklanmak TV'nin kendi ekran klavyesini açıyor.
Yazarken tuşlar kutuya aittir — rakamlar kanal numarası sanılmaz; bunu
`aramaOdak` bayrağı sağlıyor ve `tusIsle` en başta ona bakıyor. **AŞAĞI** ile
listeye geçilir (odak bırakılmazsa yön tuşları kutuda kalır ve listede
gezinilemez). Türkçe harfler sadeleştirilir: "cocuk" yazınca "Çocuk" bulunur.

**Grup şeridi kayar.** 18 kategoride şerit 2265 piksel, görüş alanı 660 piksel.
Dış kap kırpar, iç kap `translateX` ile kayar ve seçili sekme ortalanır.
Önce `overflow: hidden` vardı ama kaydırma yoktu; sağa gidince seçili sekme
ekrandan çıkıyor ve hiçbir şey değişmiyormuş gibi görünüyordu. Eski WebKit'te
`scrollLeft` ve `scrollIntoView` güvenilir olmadığı için transform kullanıldı.

Numaralar `tumKanallar` içindeki sıradır, grup süzgecinden bağımsız.
Favoriler TV'nin `localStorage`'ında (url bazlı), sunucuda değil.

---

## 11. Hata ayıklama

TV'de konsol yok. İki araç var:

**Beacon logları** — uygulamadaki `LOG()` Mac'e resim isteği atar (CORS'a
takılmaz). `sunucu.py` çalışırken terminalde `TV: …` önekiyle akar.

**Web Inspector** — TV'de doğrudan JS çalıştırır:

```bash
source ~/tizen-tools/env.sh
sdb -s "$TV_IP:26101" shell 0 debug PublicIptv.Iptv   # port verir
python3 inceleyici.py <port> "JSON.stringify({k:tumKanallar.length})"
python3 inceleyici.py <port> @dosya.js                    # uzun ifadeler
```

Siyah ekran teşhisi (Tuzak 1) bununla çıktı.

**Yönetim arayüzünü görsel doğrulama** — Chrome eklentisi bağlanmıyorsa:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --window-size=1500,6400 \
  --virtual-time-budget=6000 --screenshot=cikti.png "http://computer.local:8099/"
```

---

## 12. Açık karar: "Kaydet" düğmesi kaldırıldı

Panelde sağ üstte bir **Kaydet** düğmesi vardı, artık yok. Bilerek kaldırıldı —
eksik değil.

**Neden.** Eski tasarımda tarayıcı kataloğun tamamını bellekte tutuyordu;
düzenlemeler orada birikiyor, Kaydet hepsini birden gönderiyordu. Panel sunucu
tabanlı hale gelince (bkz. bölüm 5) tarayıcıda kataloğun tamamı kalmadı —
yalnızca görünen 100 satır var. 234 bin kanalın 233.900'ü hiç indirilmemişken
"hepsini kaydet" demek mümkün değil.

**Şimdi nasıl.** Her değişiklik anında sunucuya yazılıyor: kutucuk işaretlenince,
metin alanında yazma bırakılınca (700 ms), toplu işlemde hemen. Diske yazma
1,5 sn biriktiriliyor (`kaydet_ertelenmis`) ki her tıklamada 104 MB yazılmasın.

**Kaybedilen.** "Kaydetmeden sayfayı yenile, geri alınır" emniyeti gitti.
Silme ve toplu işlemlerde onay penceresi var, ama yanlışlıkla değiştirilen bir
kutucuğun geri alması yok.

**Telafi için düşünülenler (yapılmadı, karar bekliyor):**

1. **Kaydedildi göstergesi** — sağ üstte kalıcı bir işaret: yazma gitti mi,
   hata mı aldı. Şu an yalnızca birkaç saniye görünen bir bildirim var, kaçıyor.
   Ucuz iş.
2. **Toplu işlemler için geri alma** — silme/toplu seçim öncesi katalog kopyası
   alınıp "son işlemi geri al" düğmesi. Büyük kaynakların yanlışlıkla silinmesi
   durumunda yeniden indirme ihtiyacını ortadan kaldırır.

**Önerilmeyen:** Kaydet'i geri getirip yalnızca görünen sayfayı kapsayacak
şekilde ("bu sayfayı kaydet") tanımlamak. Yarısı çalışan bir düğme kafa
karıştırır.

---

## 13. Yapılacaklar

Öncelik sırasına göre. Her madde tek başına ele alınabilir; "neden" kısmı
ölçümlere dayanıyor, tahmine değil.

### Öncelik 1 — Film oynatmayı kullanılabilir hale getirmek

Ölçümler bölüm 9'da. Sıra önemli: 1.1 ve 1.2 ucuz ve büyük kazanç, 1.3 asıl
çözüm ama büyük iş.

**1.1 · Ölü filmleri ayıkla** — başarısızlıkların %60'ını siler.
Panelde: bir sayfayı **Denetle** → durum filtresi "çalışmayanlar" →
**Filtrelenenleri sil**. Sayfa sayfa yapmak 4.470 film için çok yavaş
(sağlayıcıda `max_connections: 1`).
*Yapılacak:* arka planda çalışan toplu denetleme — filtreye uyan tüm kanalları
sırayla dener, ilerlemeyi bildirir, sonuçları saklar. Sunucuda bir iş kuyruğu
ve `/api/denetim-durumu` ucu gerekir.

**1.2 · MKV'leri at** — ölçümde 0/4 çalıştı, üstelik AVPlay MKV'de en zayıf.
*Yapılacak:* panele "uzantı" filtresi ya da doğrudan
`kaynak-sil` benzeri bir "mkv olanları sil" işlemi.

**1.3 · Mac'te anlık remux (ffmpeg)** — kalan %40'ın sarma ve açılış sorununu
bitirir. Sorun: `moov` dosyanın sonunda, ~2,5 MB; oynatıcı başlamadan kuyruğu
çekmek zorunda. Çözüm: `sunucu.py` filmi aracılasın ve ffmpeg ile ya `moov`'u
başa alsın (`-movflags faststart`) ya da HLS'e çevirsin — TV'ye tam istediği
biçimi vermiş oluruz.
*Bedeli:* `brew install ffmpeg`, CPU, ve izlerken Mac'in açık olması.
*Dikkat:* sağlayıcıda tek bağlantı hakkı var; aracı sunucu bunu tüketir,
aynı anda başka bir cihaz izleyemez.

### Öncelik 2 — Panelde emniyet

**2.1 · Kaydedildi göstergesi** — sağ üstte kalıcı bir işaret. Şu an yalnızca
birkaç saniye görünen bildirim var, kaçıyor. Ucuz iş. Bkz. bölüm 12.

**2.2 · Toplu işlemler için geri alma** — silme/toplu seçim öncesi katalog
kopyası + "son işlemi geri al". 250 binlik kaynak bir kez yanlışlıkla silindi.

### Öncelik 3 — Özellikler

**3.1 · EPG** — altyapı hazır, XMLTV kaynağı bağlanmadı. Xtream panellerinde
`xmltv.php?username=…&password=…` ucu var.

**3.2 · Sunucu açılışta başlasın** — launchd plist; şu an elle çalıştırılıyor
ve unutulunca TV önbellekten açılıyor.

**3.3 · Kendi yayınını yapma** — ffmpeg → HLS → `/yayin/` zinciri tasarlandı,
kurulmadı. 1.3 ile aynı altyapıyı paylaşır, ikisi birlikte yapılmalı.

**3.4 · Mac adresini gömmekten kurtul** — şu an `uygulama.js`, TV'nin Developer
Mode ayarı ve panel adresi olmak üzere üç yere gömülü. Ağ değişince üçü birden
bozuluyor. Çözüm: TV uygulaması sunucuyu ağda kendisi bulsun (mDNS/Bonjour ya
da yayın adresi taraması), ya da en azından IP `localStorage`'dan okunup TV'de
düzenlenebilsin.

**3.5 · Yabancı kanallar için kategori kuralları** — `kategorile.py` yalnızca
Türkçe kanalları tanıyor; katalogdaki 230 bin yabancı kanalın çoğu "Diğer"de.

### Bilerek yapılmayanlar

- **Satır sıralama (↑↓)** — sayfalı ve 234 binlik bir listede anlamsızdı, kaldırıldı.
- **Panelde "Kaydet"** — bkz. bölüm 12, gerekçesiyle birlikte.

---

## 14. Not

Uygulama `.wgt` olarak imzalanıp kuruluyor; Developer Mode TV'de **açık kalmalı**,
kapanırsa uygulama çalışmaz. Sertifika ~2 yıl geçerli, sonra yeniden imzalamak gerek.
