/* Tizen varsayilan CSP'si inline <script> calistirmiyor; tum JS harici olmali. */

// --- Mac'teki sunucu ------------------------------------------------------
// sunucu.py hem kanal listesini verir hem log beacon'larini toplar.
var MAC = localStorage.getItem('sunucuAdresi') || 'http://computer.local:8099/';
var API_KANALLAR = MAC + 'api/kanallar';
var API_ASIMI = 4000;   // Mac kapaliysa acilisi bu kadardan fazla bekletme

// localStorage bu TV'de 5 MB'da doluyor (olculdu). Kotayi asan bir yazma temiz
// bir QuotaExceededError vermiyor -- uygulamayi kilitliyor, 57 bin kanallik
// (11.9 MB) bir listeyle denendi ve TV'yi yeniden baslatmak gerekti.
// Bu yuzden yazmadan once boyuta bakiyoruz.
var ONBELLEK_SINIRI = 3 * 1024 * 1024;

// TV'de dlog ve kabuk kapali, tek goz bu. Resim-istegi CORS'a takilmaz.

function LOG(m) {
  try { new Image().src = MAC + '?m=' + encodeURIComponent(m) + '&_=' + Date.now(); }
  catch (e) { /* log gonderemiyorsak yapacak bir sey yok */ }
}

window.onerror = function (msg, src, satir, sutun) {
  LOG('HATA: ' + msg + ' @ ' + src + ':' + satir + ':' + sutun);
};

// --- Tus kodlari (Tizen TV) ----------------------------------------------
var TUS = {
  YUKARI: 38, ASAGI: 40, SOL: 37, SAG: 39, OK: 13,
  GERI: 10009, CIKIS: 10182,
  KANAL_YUKARI: 427, KANAL_ASAGI: 428,
  OYNAT_DURAKLAT: 10252, OYNAT: 415, DURAKLAT: 19, DURDUR: 413,
  KIRMIZI: 403,  // listeyi sunucudan yeniden cek
  YESIL: 404,    // arama
  SARI: 405,     // favoriye ekle / cikar
  MAVI: 406      // bolum degistir (Canli / Filmler / Diziler)
};

var FAVORI_GRUBU = 'Favoriler';

/* Ust duzey bolumler. Filmler ve diziler kanal listesine karisinca hem grup
   seridi hem liste kullanilamaz hale geliyordu (4.470 film, 192 canli kanal).
   Diger IPTV uygulamalarindaki gibi ayri bolumler. `tur` alanina dayali. */
var BOLUMLER = [
  { ad: 'Favoriler', tur: null, favori: true },
  { ad: 'Canlı',     tur: 'canli' },
  { ad: 'Filmler',   tur: 'film' },
  { ad: 'Diziler',   tur: 'dizi' }
];
var bolumler = [];       // yalnizca icerigi olanlar
var bolumIndeks = 0;

// Grup seridi kanallarin listedeki sirasina gore dizilirse rastgele gorunuyor.
// Bilinen kategoriler bu sirayla, tanimadiklarimiz alfabetik olarak sona.
var GRUP_SIRASI = ['Ulusal', 'Haber', 'Spor', 'Sinema & Dizi', 'Belgesel',
                   'Çocuk', 'Müzik', 'Yerel', 'Dini', 'Ekonomi', 'Eğitim',
                   'Yaşam', 'Yabancı', 'Test', 'Diğer'];

var PENCERE = 11;        // listede ayni anda cizilen satir sayisi

// Hic baslayamamis yayin ile oynarken kopan yayin ayni sey degil. Ilkinde israr
// anlamsiz (kanal gercekten yok), ikincisinde sart (canli yayinda kopma olagan).
var DENEME_HIC_BASLAMADI = 1;
var DENEME_KOPTU = 5;
// prepareAsync olu bir yayinda ne basari ne hata dondurmeden sessizce asilabiliyor
// (24 TV'de 44 sn beklendi). Kendi zaman asimimiz olmadan kullanici kilitli kaliyor.
var HAZIRLIK_ASIMI = 12000;

// --- Durum ----------------------------------------------------------------
var tumKanallar = [];
var gruplar = [];
var grupIndeks = 0;
var filtreli = [];
var secili = 0;          // filtreli liste icindeki gezinme indeksi
var oynayan = null;      // su an oynayan kanal nesnesi
var oncekiKanal = null;  // RETURN ile donulecek kanal (zap yaparken en cok gereken)
var listeAcik = false;
var deneme = 0;
var oynadiMi = false;    // bu kanal bir kez olsun goruntu verdi mi
// Acilista goruntu gelene kadar olu kanallari atla: hatirlanan kanal yayindan
// kalkmis olabilir ve kullaniciyi bos ekranla karsilamak istemiyoruz.
var acilisModu = true;
var acilistaAtlanan = 0;
var AZAMI_ATLAMA = 5;

// VOD (kayittan yayin) canlidan farkli davranir: suresi vardir, sarilabilir ve
// bitmesi ariza degildir. Canli yayinda getDuration() 0 doner, ayrimi oradan yapiyoruz.
var vodMu = false;
var sureToplam = 0;      // ms
var SARMA = 30000;       // sag/sol ile atlanan sure (ms)
var sarmaHedef = null;   // biriktirilen sarma hedefi, bkz. sar()
var sarmaZaman = null;

// Film izlerken cikip donunce bastan baslamak kabul edilemez. Konum url bazli
// localStorage'da; sonuna yaklasanlar ve daha yeni baslamislar kaydedilmez.
var konumlar = {};       // url -> ms
var konumZaman = null;
var KONUM_ARALIK = 15000;    // bu siklikta kaydet
var KONUM_ESIK = 60000;      // ilk dakikada kaydetme, anlamsiz
var KONUM_SON_PAY = 120000;  // son 2 dakikada kaydetme, film bitmis sayilir
var basarisiz = {};      // url -> true, bu oturumda calismayanlar
// Favoriler TV'de durur, sunucuda degil: Mac kapaliyken de calismali ve
// senkron catismasi olmamali. Kimlik url, boylece liste yenilenince kaybolmaz.
var favoriler = {};      // url -> true

// Kanal numaralari tum liste uzerinden sabit: grup degistirince kaymasin,
// "12" her zaman ayni kanal olsun. url -> numara.
var numaraHarita = {};
var numaraTampon = '';
var numaraZaman = null;
var NUMARA_BEKLEME = 2500;   // son rakamdan sonra bu kadar beklenip gidilir

// Arama kipi: gruplarin yerini alir, tum kanallarda dolasir.
// aramaOdak true iken tuslar metin kutusuna aittir; rakamlari kanal numarasi
// sanip kacirmamak icin tusIsle en basta bu duruma bakar.
var aramaAcik = false;
var aramaOdak = false;
var aramaMetni = '';
var bilgiZaman = null;
var yenidenZaman = null;
var hazirlikZaman = null;
var sonYuzde = -1;

function el(id) { return document.getElementById(id); }

/* Acilis ekranini kaldir. Opak siyah katman durdukca video gorunmez (video web
   katmaninin arkasinda), o yuzden hem basarida hem pes edince cagirmak sart. */
function acilisKapat() {
  var a = el('acilis');
  if (!a || a.classList.contains('gizli')) { return; }
  a.classList.add('gizli');
  // Gecis bitince tamamen kaldir: opaklik 0 olsa da katmanin durmasi
  // eski WebKit'te birlestirmeyi bozabiliyor.
  setTimeout(function () { a.style.display = 'none'; }, 600);
}

function oynaticiDurumu() {
  try { return webapis.avplay.getState(); } catch (e) { return 'NONE'; }
}

function sureBicimle(ms) {
  var t = Math.max(0, Math.floor(ms / 1000));
  var sa = Math.floor(t / 3600);
  var dk = Math.floor((t % 3600) / 60);
  var sn = t % 60;
  var iki = function (n) { return n < 10 ? '0' + n : '' + n; };
  return sa > 0 ? sa + ':' + iki(dk) + ':' + iki(sn) : dk + ':' + iki(sn);
}

function ilerlemeGuncelle(simdi) {
  if (!vodMu || !sureToplam) { return; }
  // Sarma sirasinda oynaticidan gelen eski konum cubugu geri sicratmasin.
  if (sarmaHedef !== null && simdi !== sarmaHedef) { return; }
  el('sure-simdi').textContent = sureBicimle(simdi);
  el('cubuk-dolu').style.width = (simdi / sureToplam * 100) + '%';
}

function durum(metin, hataMi) {
  var e = el('durum-satir');
  e.textContent = metin;
  e.className = hataMi ? 'hata' : '';
  LOG((hataMi ? 'HATA: ' : 'durum: ') + metin);
}

// --- Kanal kaynagi --------------------------------------------------------
/* Uc kademe: Mac'teki sunucu -> son cekilen liste (onbellek) -> pakete gomulu
   playlist. Mac her zaman acik olmayacagi icin ilk kademeye guvenemeyiz. */

/* Son care: pakete gomulu playlist. Mac de onbellek de yoksa (ornegin uygulama
   baska bir TV'ye ilk kez kuruldugunda) en azindan bir liste olsun. */
function gomuluKanallar() {
  return m3uAyristir(PLAYLIST_METIN);
}

function onbellektenKanallar() {
  try {
    var metin = localStorage.getItem('kanalOnbellek');
    if (!metin) { return null; }
    var k = JSON.parse(metin);
    return (k && k.length) ? k : null;
  } catch (e) {
    return null;
  }
}

/* Onbellegi ancak gecerli VE sigacak bir liste alinca tazele. Sinir asilirsa
   yazmayi hic deneme: kota asimi bu TV'de uygulamayi kilitliyor. Onbellek
   guncellenmez, ama eski onbellek yerinde kalir ve uygulama calismaya devam eder. */
function onbellegeYaz(metin) {
  if (metin.length > ONBELLEK_SINIRI) {
    LOG('onbellek atlandi: liste ' + Math.round(metin.length / 1048576 * 10) / 10 +
        ' MB, sinir ' + (ONBELLEK_SINIRI / 1048576) + ' MB');
    return;
  }
  try {
    localStorage.setItem('kanalOnbellek', metin);
  } catch (e) {
    LOG('onbellege yazilamadi: ' + e.name);
  }
}

function kanallariGetir(bitince) {
  var cagrildi = false;
  function son(kanallar, kaynak) {
    if (cagrildi) { return; }
    cagrildi = true;
    bitince(kanallar, kaynak);
  }

  function yedege(sebep) {
    LOG('sunucudan alinamadi (' + sebep + ')');
    var onbellek = onbellektenKanallar();
    if (onbellek) { son(onbellek, 'onbellek'); }
    else { son(gomuluKanallar(), 'gomulu'); }
  }

  var xhr;
  try {
    xhr = new XMLHttpRequest();
    xhr.open('GET', API_KANALLAR + '?_=' + Date.now(), true);
    xhr.timeout = API_ASIMI;
  } catch (e) {
    yedege('xhr acilamadi: ' + e.message);
    return;
  }

  xhr.onload = function () {
    var k = null;
    try { k = JSON.parse(xhr.responseText); } catch (e) { /* asagida ele aliniyor */ }
    if (!k || !k.length) { yedege('yanit bos/bozuk'); return; }
    onbellegeYaz(xhr.responseText);
    son(k, 'sunucu');
  };
  xhr.onerror = function () { yedege('baglanti hatasi'); };
  xhr.ontimeout = function () { yedege('zaman asimi'); };

  try { xhr.send(); } catch (e) { yedege('gonderilemedi: ' + e.message); }
}

/* Kirmizi tus: yonetim arayuzunde yapilan degisikligi TV'ye almak icin. */
function kanallariYenile() {
  durum('liste yenileniyor…');
  kanallariGetir(function (kanallar, kaynak) {
    var oncekiUrl = oynayan ? oynayan.url : null;
    tumKanallar = kanallar;
    numaralariKur();
    bolumleriHazirla();
    gruplariHazirla();
    filtreyiKur();
    if (listeAcik) { bolumleriCiz(); gruplariCiz(); listeCiz(); }
    LOG('yenilendi: ' + kanallar.length + ' kanal (' + kaynak + ')');
    durum(kanallar.length + ' kanal yuklendi (' + kaynak + ')');

    // Oynayan kanal listeden kalktiysa oynatmayi bozma, sadece nesneyi tazele.
    for (var i = 0; i < tumKanallar.length; i++) {
      if (tumKanallar[i].url === oncekiUrl) { oynayan = tumKanallar[i]; break; }
    }
    bilgiGoster(false);
  });
}

// --- Kanal numaralari -----------------------------------------------------
function vodMuKanal(k) { return !!k && k.tur && k.tur !== 'canli'; }

// --- Izleme konumu (yalnizca VOD) ----------------------------------------
function konumlariYukle() {
  try { konumlar = JSON.parse(localStorage.getItem('izlemeKonumlari') || '{}'); }
  catch (e) { konumlar = {}; }
}

function konumlariKaydet() {
  try { localStorage.setItem('izlemeKonumlari', JSON.stringify(konumlar)); }
  catch (e) { LOG('konum kaydedilemedi: ' + e.name); }
}

function konumKaydet() {
  if (!vodMu || !oynayan || !sureToplam) { return; }
  var simdi = 0;
  try { simdi = webapis.avplay.getCurrentTime(); } catch (e) { return; }

  if (simdi < KONUM_ESIK || simdi > sureToplam - KONUM_SON_PAY) {
    // Basta ya da sonda: kaydetmeye degmez, sondaysa kaydi da temizle
    if (konumlar[oynayan.url]) { delete konumlar[oynayan.url]; konumlariKaydet(); }
    return;
  }
  konumlar[oynayan.url] = simdi;
  konumlariKaydet();
}

function konumIzlemeyiBaslat() {
  clearInterval(konumZaman);
  if (!vodMu) { return; }
  konumZaman = setInterval(konumKaydet, KONUM_ARALIK);
}

function konumIzlemeyiDurdur() {
  clearInterval(konumZaman);
  konumZaman = null;
}

/* Numara yalnizca CANLI kanallara verilir. Filmlerde kanal numarasinin anlami
   yok; ayrica 4 binden fazla film numaralari sisirip canli kanallarin
   numaralarini kullanilamaz hale getiriyordu. */
var numaraliKanallar = [];

function numaralariKur() {
  numaraHarita = {};
  numaraliKanallar = [];
  for (var i = 0; i < tumKanallar.length; i++) {
    var k = tumKanallar[i];
    if (vodMuKanal(k)) { continue; }
    numaraliKanallar.push(k);
    numaraHarita[k.url] = numaraliKanallar.length;
  }
}

function azamiBasamak() {
  return String(Math.max(1, numaraliKanallar.length)).length;
}

function numaraGoster(gorunur) {
  el('numara').classList.toggle('gorunur', !!gorunur);
}

function numaraGir(rakam) {
  // Bastaki sifirlar numarayi buyutmesin: "007" uc basamak sayilip erken gitmesin
  if (numaraTampon === '' && rakam === '0') { return; }
  if (numaraTampon.length >= azamiBasamak()) { return; }

  numaraTampon += rakam;
  el('numara-rakam').textContent = numaraTampon;

  var kanal = numaraliKanallar[parseInt(numaraTampon, 10) - 1];
  el('numara-ad').textContent = kanal ? kanal.ad : 'kanal yok';
  el('numara-ad').className = kanal ? '' : 'yok';
  numaraGoster(true);

  clearTimeout(numaraZaman);
  if (numaraTampon.length >= azamiBasamak()) {
    // Daha fazla rakam alamayiz, beklemeye gerek yok
    numaraOnayla();
  } else {
    numaraZaman = setTimeout(numaraOnayla, NUMARA_BEKLEME);
  }
}

function numaraOnayla() {
  clearTimeout(numaraZaman);
  var n = parseInt(numaraTampon, 10);
  numaraTampon = '';
  numaraGoster(false);

  var kanal = numaraliKanallar[n - 1];
  if (!kanal) {
    durum(n + ' numarali kanal yok', true);
    bilgiGoster(false);
    return;
  }

  if (listeAcik) {
    // Kanal gecerli suzgecte yoksa Tumu'ye gec, yoksa imlec kaybolur
    var yer = filtreli.indexOf(kanal);
    if (yer === -1) {
      grupIndeks = gruplar.indexOf('Tumu');
      filtreyiKur();
      yer = filtreli.indexOf(kanal);
      gruplariCiz();
    }
    secili = Math.max(0, yer);
    listeCiz();
  } else {
    kanalAc(kanal);
  }
}

function numaraIptal() {
  clearTimeout(numaraZaman);
  numaraTampon = '';
  numaraGoster(false);
}

// --- Favoriler ------------------------------------------------------------
function favorileriYukle() {
  try {
    var liste = JSON.parse(localStorage.getItem('favoriler') || '[]');
    for (var i = 0; i < liste.length; i++) { favoriler[liste[i]] = true; }
  } catch (e) {
    LOG('favoriler okunamadi: ' + e.message);
  }
}

function favorileriKaydet() {
  var liste = [];
  for (var url in favoriler) { if (favoriler[url]) { liste.push(url); } }
  try {
    localStorage.setItem('favoriler', JSON.stringify(liste));
  } catch (e) {
    LOG('favoriler kaydedilemedi: ' + e.name);
  }
  return liste.length;
}

function favoriSayisi() {
  var n = 0;
  for (var url in favoriler) { if (favoriler[url]) { n++; } }
  return n;
}

/* Sari tus: liste acikken uzerinde gezindigin kanali, kapaliyken oynayani. */
function favoriDegistir() {
  var kanal = listeAcik ? filtreli[secili] : oynayan;
  if (!kanal) { return; }

  if (favoriler[kanal.url]) {
    delete favoriler[kanal.url];
    durum(kanal.ad + ' favorilerden cikarildi');
  } else {
    favoriler[kanal.url] = true;
    durum(kanal.ad + ' favorilere eklendi');
  }
  LOG('favori: ' + kanal.ad + ' -> ' + (favoriler[kanal.url] ? 'ekli' : 'cikti') +
      ' (toplam ' + favorileriKaydet() + ')');

  bilgiGoster(false);
  if (listeAcik) { bolumleriCiz(); }
  if (listeAcik) {
    // Favoriler bolumundeysek liste kisalmis olabilir; yeniden suz.
    if (bolumler[bolumIndeks] && bolumler[bolumIndeks].favori) {
      var eski = secili;
      filtreyiKur();
      secili = Math.min(eski, Math.max(0, filtreli.length - 1));
    }
    listeCiz();
  }
}

// --- Filtre ---------------------------------------------------------------
/* Bolumun kapsadigi kanallar. Favoriler bolumu ture bakmaz. */
function bolumKanallari(b) {
  if (!b) { return tumKanallar; }
  if (b.favori) {
    return tumKanallar.filter(function (k) { return !!favoriler[k.url]; });
  }
  return tumKanallar.filter(function (k) {
    return (k.tur || 'canli') === b.tur;
  });
}

function bolumleriHazirla() {
  var oncekiAd = bolumler[bolumIndeks] && bolumler[bolumIndeks].ad;

  bolumler = BOLUMLER.filter(function (b) {
    // Bos bolumu gostermenin anlami yok; Favoriler bos olsa da dursun ki
    // nasil favori eklenecegi ogrenilebilsin.
    return b.favori || bolumKanallari(b).length > 0;
  });
  if (!bolumler.length) { bolumler = [BOLUMLER[0]]; }

  var yer = oncekiAd ? bolumler.map(function (b) { return b.ad; }).indexOf(oncekiAd) : -1;
  if (yer > -1) { bolumIndeks = yer; }
  else {
    // Acilista Favoriler'e degil ilk dolu bolume dus
    var canli = bolumler.map(function (b) { return b.ad; }).indexOf('Canlı');
    bolumIndeks = canli > -1 ? canli : (bolumler.length > 1 ? 1 : 0);
  }
}

function bolumleriCiz() {
  var h = '';
  for (var i = 0; i < bolumler.length; i++) {
    var adet = bolumKanallari(bolumler[i]).length;
    h += '<span class="bolum' + (i === bolumIndeks ? ' secili' : '') + '">' +
         bolumler[i].ad + '<span class="adet">' + adet + '</span></span>';
  }
  el('bolumler').innerHTML = h;
}

function gruplariHazirla() {
  var oncekiAd = gruplar[grupIndeks];

  // Gruplar artik yalnizca AKTIF BOLUMDEN cikariliyor; yoksa Filmler
  // bolumundeyken canli kanal gruplari da seritte gorunuyordu.
  var kapsam = bolumKanallari(bolumler[bolumIndeks]);
  var ham = gruplariCikar(kapsam).slice(1);   // bastaki 'Tumu' ayri ele alinacak
  ham.sort(function (a, b) {
    var ia = GRUP_SIRASI.indexOf(a), ib = GRUP_SIRASI.indexOf(b);
    if (ia === -1 && ib === -1) { return a < b ? -1 : a > b ? 1 : 0; }
    if (ia === -1) { return 1; }
    if (ib === -1) { return -1; }
    return ia - ib;
  });
  gruplar = ['Tumu'].concat(ham);

  // Aktif grubu INDEKSLE degil ADLA koru: bolum degisince gruplar tamamen
  // degistigi icin indeks anlamsiz kaliyor.
  var yer = oncekiAd ? gruplar.indexOf(oncekiAd) : -1;
  grupIndeks = yer > -1 ? yer : 0;
}

/* Turkce harfleri sadelestir: kullanici "cocuk" yazinca "Çocuk" da bulunsun. */
function sadelestir(s) {
  s = String(s).toLowerCase();
  var kaynak = 'çğıöşüâî', hedef = 'cgiosuai';
  var cikti = '';
  for (var i = 0; i < s.length; i++) {
    var y = kaynak.indexOf(s.charAt(i));
    cikti += y > -1 ? hedef.charAt(y) : s.charAt(i);
  }
  return cikti;
}

function filtreyiKur() {
  if (aramaAcik) {
    var q = sadelestir(aramaMetni.trim());
    filtreli = !q ? [] : tumKanallar.filter(function (k) {
      return sadelestir(k.ad + ' ' + k.grup).indexOf(q) > -1;
    });
    if (secili >= filtreli.length) { secili = Math.max(0, filtreli.length - 1); }
    return;
  }

  var kapsam = bolumKanallari(bolumler[bolumIndeks]);
  var grup = gruplar[grupIndeks];
  filtreli = (!grup || grup === 'Tumu')
    ? kapsam
    : kapsam.filter(function (k) { return k.gruplar.indexOf(grup) > -1; });
  if (secili >= filtreli.length) { secili = Math.max(0, filtreli.length - 1); }
}

// --- Bilgi cubugu ---------------------------------------------------------
function bilgiGoster(kalici) {
  if (!oynayan) { return; }
  el('bilgi-ad').textContent = (favoriler[oynayan.url] ? '★ ' : '') + oynayan.ad;
  el('bilgi-grup').textContent = oynayan.grup + (oynayan.uyari ? ' · ' + oynayan.uyari : '');
  el('onceki-ipucu').textContent = (oncekiKanal && oncekiKanal !== oynayan)
    ? 'RETURN → ' + oncekiKanal.ad : '';
  el('bilgi').classList.add('gorunur');
  clearTimeout(bilgiZaman);
  if (!kalici) { bilgiZaman = setTimeout(bilgiGizle, 4000); }
}

function bilgiGizle() { el('bilgi').classList.remove('gorunur'); }

// --- Kanal listesi --------------------------------------------------------
function gruplariCiz() {
  var h = '';
  for (var i = 0; i < gruplar.length; i++) {
    var ad = gruplar[i] === FAVORI_GRUBU
      ? '★ ' + FAVORI_GRUBU + ' (' + favoriSayisi() + ')'
      : gruplar[i];
    h += '<span class="grup' + (i === grupIndeks ? ' secili' : '') + '">' + ad + '</span>';
  }
  el('gruplar-ic').innerHTML = h;
  seridiKaydir();
}

/* Serit ekrana sigmadiginda secili sekme gorus alanindan cikiyordu (8 kategoride
   yalnizca ilk 5'i gorunuyor, sagdakilere gecince ekranda hicbir sey degismiyordu).
   Secileni ortalayacak kadar kaydir, uclarda tasmayi kirp. */
function seridiKaydir() {
  var kap = el('gruplar');
  var ic = el('gruplar-ic');
  var secilenEl = ic.children[grupIndeks];
  if (!secilenEl) { return; }

  var kapGenislik = kap.clientWidth;
  var icGenislik = ic.scrollWidth;

  if (icGenislik <= kapGenislik) {
    ic.style.transform = 'translateX(0)';
    return;
  }

  var kaydir = secilenEl.offsetLeft - (kapGenislik - secilenEl.offsetWidth) / 2;
  kaydir = Math.max(0, Math.min(kaydir, icGenislik - kapGenislik));
  ic.style.transform = 'translateX(' + (-Math.round(kaydir)) + 'px)';
}

function listeCiz() {
  if (!filtreli.length) {
    var b = bolumler[bolumIndeks];
    el('liste').innerHTML = '<li class="bos-not">' +
      (b && b.favori
        ? 'Henuz favori yok. Bir kanali izlerken ya da listede uzerindeyken SARI tusa bas.'
        : 'Bu grupta kanal yok.') + '</li>';
    el('liste-sayac').textContent = '0';
    return;
  }

  // Yalnizca secilinin cevresindeki pencereyi ciziyoruz: 56 satir + 56 uzak
  // logo eski TV'de gozle gorulur sekilde yavaslatiyor.
  var bas = Math.max(0, Math.min(secili - Math.floor(PENCERE / 2),
                                 filtreli.length - PENCERE));
  if (bas < 0) { bas = 0; }
  var son = Math.min(filtreli.length, bas + PENCERE);

  var h = '';
  for (var i = bas; i < son; i++) {
    var k = filtreli[i];
    var sinif = 'kanal';
    if (i === secili) { sinif += ' secili'; }
    if (k === oynayan) { sinif += ' aktif'; }
    if (basarisiz[k.url]) { sinif += ' olu'; }

    h += '<li class="' + sinif + '">' +
           '<span class="no' + (vodMuKanal(k) ? ' film' : '') + '">' +
             (vodMuKanal(k) ? '▶' : (numaraHarita[k.url] || '')) + '</span>' +
           '<span class="logo">' + (k.logo ? '<img src="' + k.logo + '" alt="">' : '') + '</span>' +
           '<span class="yildiz">' + (favoriler[k.url] ? '★' : '') + '</span>' +
           '<span class="ad">' + k.ad + '</span>' +
           (basarisiz[k.url] ? '<span class="rozet">yayin yok</span>'
                             : (k.uyari ? '<span class="rozet">' + k.uyari + '</span>' : '')) +
         '</li>';
  }
  el('liste').innerHTML = h;
  el('liste-sayac').textContent = (secili + 1) + ' / ' + filtreli.length;
}

// --- Arama ----------------------------------------------------------------
function aramaAc() {
  if (!listeAcik) { listeAc(); }
  aramaAcik = true;
  aramaOdak = true;
  el('liste-katman').classList.add('arama');
  var kutu = el('arama');
  kutu.value = aramaMetni;
  // Odaklanmak TV'nin ekran klavyesini aciyor
  try { kutu.focus(); } catch (e) { LOG('arama odaklanamadi: ' + e.message); }
  secili = 0;
  filtreyiKur();
  listeCiz();
  LOG('arama acildi');
}

function aramaKapat() {
  aramaAcik = false;
  aramaOdak = false;
  aramaMetni = '';
  el('liste-katman').classList.remove('arama');
  try { el('arama').blur(); } catch (e) { /* onemsiz */ }
  secili = 0;
  filtreyiKur();
  gruplariCiz();
  listeCiz();
}

/* Yazmayi bitirip listeye gecis: metin kutusu odagi birakmali, yoksa yon
   tuslari ve OK metin kutusuna gider, listede gezinemezsin. */
function aramadanListeye() {
  if (!filtreli.length) { return; }
  aramaOdak = false;
  try { el('arama').blur(); } catch (e) { /* onemsiz */ }
  el('arama-ipucu').textContent = filtreli.length + ' sonuc · YESIL ile kutuya don';
  secili = 0;
  listeCiz();
}

function listeAc() {
  listeAcik = true;
  // Oynayan kanal filtrede varsa onun uzerinde acilsin
  var yer = filtreli.indexOf(oynayan);
  if (yer > -1) { secili = yer; }
  el('liste-katman').classList.add('gorunur');
  bolumleriCiz();
  gruplariCiz();
  listeCiz();
}

function listeKapat() {
  listeAcik = false;
  el('liste-katman').classList.remove('gorunur');
  if (aramaAcik) {
    aramaAcik = false;
    aramaOdak = false;
    el('liste-katman').classList.remove('arama');
    try { el('arama').blur(); } catch (e) { /* onemsiz */ }
  }
}

// --- Oynatici -------------------------------------------------------------
function oynaticiyiBirak() {
  konumKaydet();          // birakmadan once nerede kaldigimizi yaz
  konumIzlemeyiDurdur();
  clearTimeout(yenidenZaman);
  clearTimeout(hazirlikZaman);
  try {
    var d = oynaticiDurumu();
    if (d === 'PLAYING' || d === 'PAUSED') { webapis.avplay.stop(); }
    if (d !== 'NONE') { webapis.avplay.close(); }
  } catch (e) {
    LOG('birakma sirasinda: ' + e.message);
  }
}

function kanalAc(kanal, yenidenMi) {
  if (!kanal) { return; }

  // Onceki kanali yalnizca gercek bir kanal degisiminde kaydet: yeniden deneme
  // ayni kanal, acilistaki olu kanal atlamalari da geri donulecek yer degil.
  if (!yenidenMi && !acilisModu && oynayan && oynayan !== kanal) {
    oncekiKanal = oynayan;
  }

  oynayan = kanal;
  if (!yenidenMi) { deneme = 0; oynadiMi = false; }

  // Yeni kanal canli mi VOD mu, prepare bitmeden bilinmiyor; once sifirla.
  vodMu = false;
  sureToplam = 0;
  sarmaHedef = null;
  clearTimeout(sarmaZaman);
  el('bilgi').classList.remove('vod');

  LOG('kanal aciliyor: ' + kanal.ad + (yenidenMi ? ' (deneme ' + deneme + ')' : ''));
  bilgiGoster(true);
  durum('baglaniliyor…');
  sonYuzde = -1;

  oynaticiyiBirak();

  try {
    webapis.avplay.open(kanal.url);
    webapis.avplay.setDisplayRect(0, 0, 1920, 1080);
    webapis.avplay.setDisplayMethod('PLAYER_DISPLAY_MODE_LETTER_BOX');
    webapis.avplay.setListener({
      onbufferingstart: function () { durum('arabellek doluyor…'); },
      onbufferingprogress: function (yuzde) {
        if (yuzde - sonYuzde >= 25) { sonYuzde = yuzde; LOG('arabellek %' + yuzde); }
      },
      onbufferingcomplete: function () { durum('oynuyor'); },
      oncurrentplaytime: function (ms) { ilerlemeGuncelle(ms); },
      onstreamcompleted: function () {
        // VOD'da bitis normaldir, ariza degil; yeniden baglanmaya calisma.
        if (vodMu) {
          konumIzlemeyiDurdur();
          if (konumlar[kanal.url]) { delete konumlar[kanal.url]; konumlariKaydet(); }
          durum('bitti');
          bilgiGoster(true);
          try { webapis.avplay.stop(); } catch (e) { /* zaten durmus */ }
          LOG('VOD bitti: ' + kanal.ad);
        } else {
          basarisizlik('yayin kesildi');
        }
      },
      onerror: function (e) { basarisizlik('oynatma hatasi: ' + e); },
      onevent: function (tip, veri) { LOG('avplay: ' + tip + (veri ? ' ' + veri : '')); }
    });

    // Bekci: prepareAsync geri donmezse kullaniciyi kilitli birakma.
    hazirlikZaman = setTimeout(function () {
      if (oynaticiDurumu() !== 'PLAYING') { basarisizlik('yanit yok (zaman asimi)'); }
    }, HAZIRLIK_ASIMI);

    webapis.avplay.prepareAsync(
      function () {
        clearTimeout(hazirlikZaman);
        webapis.avplay.play();
        deneme = 0;
        oynadiMi = true;
        acilisModu = false;
        acilisKapat();
        delete basarisiz[kanal.url];

        // Canli yayinda getDuration() 0 doner; sifirdan buyukse elimizde VOD var.
        try { sureToplam = webapis.avplay.getDuration() || 0; } catch (e2) { sureToplam = 0; }
        vodMu = sureToplam > 0;
        if (vodMu) {
          el('bilgi').classList.add('vod');
          el('sure-toplam').textContent = sureBicimle(sureToplam);
          ilerlemeGuncelle(0);

          // Kaldigi yerden devam: film ortasinda birakildiysa oraya atla
          var kayitli = konumlar[kanal.url];
          if (kayitli && kayitli > KONUM_ESIK && kayitli < sureToplam - KONUM_SON_PAY) {
            try {
              webapis.avplay.seekTo(kayitli);
              ilerlemeGuncelle(kayitli);
              durum('kaldigin yerden: ' + sureBicimle(kayitli));
              bilgiGoster(false);
              LOG('devam: ' + kanal.ad + ' @ ' + sureBicimle(kayitli));
            } catch (e3) {
              LOG('devam edilemedi: ' + e3.message);
            }
          }
          konumIzlemeyiBaslat();
        }
        LOG((vodMu ? 'VOD' : 'canli') + ' — sure=' + sureBicimle(sureToplam));
        // Son kanali ancak calistigini gorunce kaydet; yoksa olu bir kanal
        // secildiginde uygulama her acilista oraya donuyor.
        try { localStorage.setItem('sonKanalUrl', kanal.url); } catch (e2) { /* onemsiz */ }
        durum('oynuyor');
        bilgiGoster(false);
      },
      function (e) {
        clearTimeout(hazirlikZaman);
        basarisizlik('hazirlik basarisiz: ' + (e && e.message ? e.message : e));
      }
    );
  } catch (e) {
    basarisizlik('istisna: ' + e.message);
  }
}

/* Canli yayinda kopma normal, birkac kez denemeye deger. Ama kanal gercekten
   yayinda degilse (playlist'te 13 tanesi oyle) sonsuz donguye girmemeli. */
function basarisizlik(sebep) {
  var kanal = oynayan;
  var azami = oynadiMi ? DENEME_KOPTU : DENEME_HIC_BASLAMADI;
  deneme++;
  if (deneme <= azami) {
    durum(sebep + ' — yeniden deneniyor (' + deneme + '/' + azami + ')', true);
    clearTimeout(yenidenZaman);
    yenidenZaman = setTimeout(function () { kanalAc(kanal, true); }, 3000);
  } else {
    basarisiz[kanal.url] = true;
    LOG('vazgecildi: ' + kanal.ad + ' (' + sebep + ')');

    if (acilisModu && acilistaAtlanan < AZAMI_ATLAMA) {
      acilistaAtlanan++;
      durum('bu kanal yayin vermiyor — sonrakine geciliyor', true);
      if (listeAcik) { listeCiz(); }
      komsuKanal(1);
      return;
    }

    acilisKapat();  // yoksa kullanici siyah ekranin ardinda kalir
    durum('bu kanal yayin vermiyor — baska bir kanal sec', true);
    bilgiGoster(true);
    if (listeAcik) { listeCiz(); }
  }
}

function oynatDuraklat() {
  if (oynaticiDurumu() === 'PLAYING') {
    webapis.avplay.pause();
    konumKaydet();
    durum('durakladi');
    bilgiGoster(true);   // duraklatiliyken cubuk ekranda kalsin
  } else {
    webapis.avplay.play();
    durum('oynuyor');
    bilgiGoster(false);
  }
}

/* VOD'da ileri/geri sarma.
 *
 * Her basista dogrudan seekTo cagirmak islemiyor: HLS'te seek segment sinirina
 * oturuyor ve yeniden arabellek doldururken getCurrentTime() bir sure eski
 * degeri donduruyor. Arka arkaya basinca ikinci sarma yanlis yerden hesaplanip
 * konum geri kayiyor (olculdu: 0:55 -> 1:25 sonrasi 1:05).
 *
 * Cozum: basislari hedefte biriktir, cubugu aninda guncelle, seekTo'yu bir
 * duraklamadan sonra tek seferde yap. Ayni zamanda tusa basili tutmayi da
 * dogru calistiriyor. */
function sar(fark) {
  if (!vodMu || !sureToplam) { return; }

  var taban = sarmaHedef;
  if (taban === null) {
    try { taban = webapis.avplay.getCurrentTime(); } catch (e) { return; }
  }

  sarmaHedef = Math.min(Math.max(taban + fark, 0), Math.max(sureToplam - 2000, 0));
  ilerlemeGuncelle(sarmaHedef);
  bilgiGoster(true);   // sarma bitene kadar cubuk ekranda kalsin

  clearTimeout(sarmaZaman);
  sarmaZaman = setTimeout(function () {
    var hedef = sarmaHedef;
    sarmaHedef = null;
    try {
      webapis.avplay.seekTo(hedef);
      LOG('sarma -> ' + sureBicimle(hedef));
    } catch (e) {
      LOG('sarma HATA: ' + e.message);
    }
    bilgiGoster(false);
  }, 400);
}

function komsuKanal(yon) {
  var yer = filtreli.indexOf(oynayan);
  if (yer === -1) { yer = 0; }
  var yeni = (yer + yon + filtreli.length) % filtreli.length;
  kanalAc(filtreli[yeni]);
}

// --- Tuslar ---------------------------------------------------------------
function tusIsle(kod) {
  acilisModu = false;  // kullanici devreye girdiyse artik kendiliginden atlama
  acilisKapat();       // listeyi acmak isteyebilir, acilis ekranini bekletme

  // Arama kutusunda yazarken tuslar oraya ait: rakamlari kanal numarasi sanma,
  // harfleri kisayola cevirme. Yalnizca cikis ve listeye gecis bize ait.
  if (aramaAcik && aramaOdak) {
    if (kod === TUS.ASAGI) { aramadanListeye(); return; }
    if (kod === TUS.GERI) { aramaKapat(); return; }
    if (kod === TUS.YESIL) { aramaKapat(); return; }
    return;
  }

  // Rakamlar her seyden once: numara girerken diger tuslarin devreye girmemesi lazim
  if (kod >= 48 && kod <= 57) { numaraGir(String(kod - 48)); return; }

  if (numaraTampon) {
    // Numara girisi surerken OK onaylar, GERI iptal eder; digerleri girisi bozmasin
    if (kod === TUS.OK) { numaraOnayla(); return; }
    if (kod === TUS.GERI) { numaraIptal(); return; }
  }

  if (listeAcik) {
    switch (kod) {
      case TUS.YUKARI:
        secili = (secili - 1 + filtreli.length) % filtreli.length; listeCiz(); return;
      case TUS.ASAGI:
        secili = (secili + 1) % filtreli.length; listeCiz(); return;
      case TUS.SOL:
        if (aramaAcik) { return; }   // aramada grup kavrami yok
        grupIndeks = (grupIndeks - 1 + gruplar.length) % gruplar.length;
        secili = 0; filtreyiKur(); gruplariCiz(); listeCiz(); return;
      case TUS.SAG:
        if (aramaAcik) { return; }
        grupIndeks = (grupIndeks + 1) % gruplar.length;
        secili = 0; filtreyiKur(); gruplariCiz(); listeCiz(); return;
      case TUS.MAVI:
        bolumIndeks = (bolumIndeks + 1) % bolumler.length;
        grupIndeks = 0; secili = 0;
        gruplariHazirla(); filtreyiKur();
        bolumleriCiz(); gruplariCiz(); listeCiz();
        return;
      case TUS.YESIL:
        aramaAc(); return;
      case TUS.OK:
        if (!filtreli[secili]) { return; }
        listeKapat();
        if (aramaAcik) { aramaKapat(); }
        if (filtreli[secili] !== oynayan) { kanalAc(filtreli[secili]); }
        else { bilgiGoster(false); }
        return;
      case TUS.SARI:
        favoriDegistir(); return;
      case TUS.KIRMIZI:
        kanallariYenile(); return;
      case TUS.GERI:
        if (aramaAcik) { aramaKapat(); return; }
        listeKapat(); return;
      default:
        return;
    }
  }

  switch (kod) {
    case TUS.OK:
      // VOD'da OK'in dogal karsiligi oynat/duraklat; canlida duraklatmanin
      // anlami olmadigi icin orada listeyi aciyor.
      if (vodMu) { oynatDuraklat(); } else { listeAc(); }
      return;
    case TUS.YUKARI:
    case TUS.ASAGI:
      listeAc(); return;
    case TUS.SOL:
    case TUS.SAG:
      if (vodMu) { sar(kod === TUS.SAG ? SARMA : -SARMA); }
      return;
    case TUS.KANAL_YUKARI:
      komsuKanal(1); return;
    case TUS.KANAL_ASAGI:
      komsuKanal(-1); return;
    case TUS.OYNAT_DURAKLAT:
    case TUS.DURAKLAT:
      oynatDuraklat(); return;
    case TUS.OYNAT:
      webapis.avplay.play(); durum('oynuyor'); return;
    case TUS.SARI:
      favoriDegistir(); return;
    case TUS.MAVI:
      listeAc();
      bolumIndeks = (bolumIndeks + 1) % bolumler.length;
      grupIndeks = 0; secili = 0;
      gruplariHazirla(); filtreyiKur();
      bolumleriCiz(); gruplariCiz(); listeCiz();
      return;
    case TUS.YESIL:
      aramaAc(); return;
    case TUS.KIRMIZI:
      kanallariYenile(); return;

    case TUS.GERI:
      // Zap yaparken en cok gereken sey: iki kanal arasinda gidip gelmek.
      // kanalAc oncekiKanal'i tazeledigi icin tekrar basinca geri gelinir.
      if (oncekiKanal && oncekiKanal !== oynayan) {
        LOG('onceki kanala donuluyor: ' + oncekiKanal.ad);
        kanalAc(oncekiKanal);
        return;
      }
      // Donulecek kanal yoksa cikis: yoksa uygulamada kilitli kalinir
      durum('donulecek kanal yok — cikiliyor');
      /* falls through */
    case TUS.CIKIS:
      oynaticiyiBirak();
      tizen.application.getCurrentApplication().exit();
      return;
    default:
      LOG('tus: ' + kod);
  }
}

// --- Baslangic ------------------------------------------------------------
(function () {
  if (typeof webapis === 'undefined' || !webapis.avplay) {
    acilisKapat();
    durum('AVPlay yok — bu TV\'de oynatilamaz', true);
    el('bilgi').classList.add('gorunur');
    return;
  }

  // Emniyet: beklenmedik bir sekilde hicbir sey olmazsa siyah ekranda birakma.
  setTimeout(acilisKapat, 45000);

  try {
    ['MediaPlayPause', 'MediaPlay', 'MediaPause', 'MediaStop',
     'ChannelUp', 'ChannelDown', 'ColorF0Red', 'ColorF1Green', 'ColorF2Yellow', 'ColorF3Blue',
     '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'].forEach(function (k) {
      tizen.tvinputdevice.registerKey(k);
    });
  } catch (e) {
    LOG('tus kaydi HATA: ' + e.message);
  }

  document.addEventListener('keydown', function (e) { tusIsle(e.keyCode); });

  el('arama').addEventListener('input', function () {
    aramaMetni = this.value;
    secili = 0;
    filtreyiKur();
    el('arama-ipucu').textContent = aramaMetni.trim()
      ? filtreli.length + ' sonuc · ASAGI ile listeye gec'
      : 'Yazdiktan sonra ASAGI ile listeye gec';
    listeCiz();
  });

  favorileriYukle();
  konumlariYukle();
  el('acilis-yazi').textContent = 'kanal listesi aliniyor…';

  kanallariGetir(function (kanallar, kaynak) {
    tumKanallar = kanallar;
    numaralariKur();
    bolumleriHazirla();
    gruplariHazirla();
    filtreyiKur();
    LOG('kanal listesi: ' + tumKanallar.length + ' kanal, ' +
        (gruplar.length - 1) + ' grup (kaynak: ' + kaynak + ')');

    if (!tumKanallar.length) {
      acilisKapat();
      durum('kanal listesi bos', true);
      el('bilgi').classList.add('gorunur');
      return;
    }

    el('acilis-yazi').textContent = 'baglaniliyor…';

    // Kaldigi kanaldan devam
    var son = null;
    try { son = localStorage.getItem('sonKanalUrl'); } catch (e) { /* onemsiz */ }
    var baslangic = tumKanallar[0];
    if (son) {
      for (var i = 0; i < tumKanallar.length; i++) {
        if (tumKanallar[i].url === son) { baslangic = tumKanallar[i]; break; }
      }
    }
    kanalAc(baslangic);
  });
})();
