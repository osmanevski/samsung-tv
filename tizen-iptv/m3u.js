/* M3U/M3U8 playlist ayristirici.
 *
 * Beklenen bicim (iptv-org tarzi):
 *   #EXTINF:-1 tvg-id="..." tvg-logo="..." group-title="News",24 TV (1080p)
 *   #EXTVLCOPT:http-user-agent=Mozilla/5.0 ...
 *   https://ornek/playlist.m3u8
 *
 * Donen her kayit: { ad, url, grup, gruplar, logo, id, ajan, uyari }
 * grup    -> gosterimde kullanilan birincil grup
 * gruplar -> "Business;Series" gibi coklu tanimlar ayrilmis hali
 */

function m3uAyristir(metin) {
  var satirlar = metin.split(/\r?\n/);
  var kanallar = [];
  var bekleyen = null;

  for (var i = 0; i < satirlar.length; i++) {
    var s = satirlar[i].trim();
    if (!s) { continue; }

    if (s.indexOf('#EXTINF') === 0) {
      bekleyen = extinfAyristir(s);
    } else if (s.indexOf('#EXTVLCOPT') === 0 && bekleyen) {
      // Bazi kanallar belirli bir User-Agent olmadan 403 donuyor.
      var esles = s.match(/http-user-agent=(.*)$/i);
      if (esles) { bekleyen.ajan = esles[1].trim(); }
    } else if (s.charAt(0) === '#') {
      continue; // diger yonergeler bizi ilgilendirmiyor
    } else if (bekleyen) {
      bekleyen.url = s;
      kanallar.push(bekleyen);
      bekleyen = null;
    }
  }

  return kanallar;
}

function extinfAyristir(satir) {
  var kayit = { ad: '', url: '', grup: 'Diger', gruplar: [], logo: '', id: '',
                ajan: '', uyari: '' };

  // Ad, son virgulden sonrasi. Oznitelik degerlerinde de virgul olabilecegi icin
  // once oznitelik blogunu ayirip oyle bakiyoruz.
  var virgul = satir.lastIndexOf(',');
  if (virgul > -1) { kayit.ad = satir.slice(virgul + 1).trim(); }

  var oznitelikler = virgul > -1 ? satir.slice(0, virgul) : satir;
  var re = /([a-zA-Z0-9-]+)="([^"]*)"/g;
  var m;
  while ((m = re.exec(oznitelikler)) !== null) {
    switch (m[1].toLowerCase()) {
      case 'group-title': if (m[2]) { kayit.grup = m[2]; } break;
      case 'tvg-logo':    kayit.logo = m[2]; break;
      case 'tvg-id':      kayit.id = m[2]; break;
      case 'http-user-agent': kayit.ajan = m[2]; break;
    }
  }

  // "Business;Series" gibi coklu tanimlar var; kanal her iki grupta da gorunmeli.
  kayit.gruplar = kayit.grup.split(';').map(function (g) {
    g = g.trim();
    return g === 'Undefined' ? 'Diger' : g;   // playlist'in dolgu etiketi
  }).filter(function (g) { return g.length > 0; });
  if (!kayit.gruplar.length) { kayit.gruplar = ['Diger']; }
  kayit.grup = kayit.gruplar[0];

  // Playlist'te "[Geo-blocked]", "[Not 24/7]" gibi notlar adin icinde geliyor.
  // Bunlari ayirip ada karistirma; kullaniciya ayri uyari olarak gosterecegiz.
  var not = kayit.ad.match(/\[([^\]]+)\]/);
  if (not) {
    kayit.uyari = not[1];
    kayit.ad = kayit.ad.replace(/\s*\[[^\]]+\]\s*/g, ' ').trim();
  }

  return kayit;
}

/* Gruplari, playlist'teki ilk gorulme sirasina gore dondurur. */
function gruplariCikar(kanallar) {
  var gruplar = ['Tumu'];
  for (var i = 0; i < kanallar.length; i++) {
    var g = kanallar[i].gruplar;
    for (var j = 0; j < g.length; j++) {
      if (gruplar.indexOf(g[j]) === -1) { gruplar.push(g[j]); }
    }
  }
  return gruplar;
}
