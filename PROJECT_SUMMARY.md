# LastWarBot — Proje Özeti

Windows üzerinde çalışan, **"Last War: Survival"** oyununu ekran görüntüsü + OpenCV şablon eşleştirme + Tesseract OCR ile otomatikleştiren bir masaüstü bot. Python ile yazılmış, PyInstaller ile `LastWarBot.exe` haline getiriliyor. Oyun penceresi her PC'de aynı sabit piksel boyutuna (**1717×965**) kilitleniyor ki tüm koordinatlar PC'den PC'ye değişmesin.

Aşağıdaki tüm akışlar `main.py` ve `parameters/config.json`'daki **güncel** değerlere göre yazıldı.

---

## 1. Başlatma akışı (otomatik, exe açılınca — tuşla tetiklenmiyor)

| # | Adım | Bekleme |
|---|---|---|
| 1 | Loglama kurulur, DPI-awareness ayarlanır, config.json okunur | — |
| 2 | Tesseract yolu ayarlanır (önce `tesseract_bin/` taşınabilir sürüm aranır, yoksa config'teki sabit yol) | — |
| 3 | Konsol penceresi sanal ekranın en sağına taşınır (`console_window`, 190×1000) | — |
| 4 | Kısayollar konsola ve `kutuphane/kisayollar.log`'a yazılır | — |
| 5 | Oyun penceresi aranır; açık değilse `LastWarLauncher.exe` başlatılır | pencere için en fazla **40 sn** beklenir (`window_wait_seconds`) |
| 6 | Pencere **1717×965** boyutuna sabitlenir, sol üste taşınır (8 deneme, aralarda **1.0 sn**) | — |
| 7 | *(sadece oyun bu çalıştırmada yeni açıldıysa)* 3 başlangıç tıklaması yapılır | önce **5.0 sn** bekle (`initial_delay_seconds`), tıklamalar arası **0.5 sn** |
| 8 | Başlangıç tıklamalarından sonra ESC basılır | — |
| 9 | Klavye dinleyicisi başlar, ana döngü başlar. **300 sn'lik ESC döngüsü varsayılan açık** (`escape_enabled: true`) | — |

---

## 2. Ana döngü (sürekli çalışır, tuşla tetiklenmiyor)

Her turda sırasıyla:

1. **R modu açıksa** → Uyarı/Artı taraması çalışır (bkz. bölüm 6)
2. **5 dakikada bir** (`window_check_interval_seconds`) → oyun penceresi hâlâ var mı kontrol edilir; yoksa oyun otomatik yeniden başlatılır (bölüm 8)
3. **Her turda** → `disconnect.png`, `oyundanCikNew.png`, `paylas.png` taranır (bölüm 7)
4. **O tuşu basıldıysa** → manuel metin taraması (bölüm 6 değil, `text_scan_region` üzerinde tek seferlik OCR)
5. **Her turda** → kazı/yonca/tren taraması (bölüm 3-5, tren varsayılan kapalı) + aktiviteler (şu an `activities` boş, hiçbir şey yapmıyor)
6. Döngü sonunda **1.0 sn** bekle (`scan_interval_seconds`), başa dön

---

## 3. Kazı (excavation) akışı — otomatik, `kazi.png` bulununca tetiklenir

| # | Adım | Bekleme (önce) |
|---|---|---|
| 1 | `kazi.png` bulunur → ESC döngüsü **130 sn** pasife alınır (`escape_pause_seconds_kazi`, arka planda, akışı bloklamaz) | — |
| 2 | İkona tıkla | yok |
| 3 | Bekle | **0 sn** (`text_scan_delay_seconds`) |
| 4 | `(1075,243)`'e tıkla | **0.8 sn** (`pre_ocr_delay_seconds`) |
| 5 | OCR taraması ("Test Uçuşu Arızası" / "Hazineyi kaz" aranır) | yok, tıklamadan hemen sonra başlar |
| 6 | Bulunursa hedef metnin üstüne tıkla | yok (bulununca hemen) |
| 7 | **(bulunduysa)** Ralli modu (R) açıksa **130 sn** pasife alınır (`rally_pause_seconds`) | — |
| 8 | Harita sıçraması için bekle | **2.0 sn** (`map_jump_wait_seconds`) |
| 9 | Pencere merkezine tıkla | yok |
| 10 | `(856,592)`'ye tıkla | **0.5 sn** (`follow_up_click_delay_seconds`) |
| 11 | Saldır tıklaması `(856,746)` | **0.5 sn** |
| 12 | **Sayaç izleme başlar** (bkz. aşağı) | — |

**Sayaç izleme** (`wait_for_countdown_then_burst_click`):
- Bölge `(807,383)-(891,419)`'daki sayaç (`02:00:00`'dan başlar) her **1.0 sn**'de bir okunur, her okuma hem konsola hem `logs/application.log`'a yazılır
- **15 saniye veya altına** düşünce, `(856,460)`'a **20 saniye boyunca saniyede 10** kez tıklanır (120s güvenlik sınırı var)

---

## 4. Yonca (clover) / Şanslı Hediye akışı — otomatik, `yonca.png` bulununca tetiklenir

| # | Adım | Bekleme (önce) |
|---|---|---|
| 1 | `yonca.png` bulunur → ESC döngüsü **30 sn** pasife alınır (`escape_pause_seconds_yonca`) | — |
| 2 | İkona tıkla | yok |
| 3 | Bekle | **0 sn** (`text_scan_delay_seconds`) |
| 4 | `(1090,235)`'e tıkla (başlangıçtaki 3. tıklamayla aynı koordinat) | **0.8 sn** (`pre_ocr_delay_seconds`) |
| 5 | OCR taraması ("Şanslı Hediye" / "anslı Hediye" aranır) | yok |
| 6 | Bulunursa hedef metnin üstüne tıkla | yok (bulununca hemen) |
| 7 | **(bulunduysa)** `(859,668)`'e tıkla | **1.0 sn** (`post_match_click_delay_seconds`) |
| 8 | **3 kere** ESC bas | aralarda **0.5 sn** (`escape_between_presses_seconds`) |

Bulunamazsa: tek ESC basılır, akış biter.

---

## 5. Tren akışı — otomatik, `tren.png` bulununca tetiklenir. **Varsayılan kapalı**, `P` ile açılır

| # | Adım | Bekleme (önce) |
|---|---|---|
| 1 | `(19,532)-(73,580)` bölgesinde `tren.png` sürekli aranır (sadece `P` ile açıksa) | — |
| 2 | Bulunursa ortasına tıkla, 300 sn'lik ESC döngüsü durdurulur | — |
| 3 | `(1049,316)`'ya tıkla | **2 sn** (`step1_wait_seconds`) |
| 4 | `(1049,316)`'ya tıkla | **5 sn** (`step2_wait_seconds`) |
| 5 | `(1049,316)`'ya 2 kere tıkla | önce **2 sn** (`step3_wait_seconds`), aralarında **0.5 sn** (`double_click_interval_seconds`) |
| 6 | `(974,701)`'e tıkla | **1 sn** (`step4_wait_seconds`) |
| 7 | ESC bas | **0.5 sn** (`escape_delay_seconds`) |
| 8 | ESC döngüsü öncesindeki durumuna döndürülür (açıktıysa tekrar açılır) | — |

---

## 6. Uyarı / Artı akışı — `R` tuşuyla açılıp kapatılan sürekli tarama

| # | Adım | Bekleme (önce) |
|---|---|---|
| 1 | `(1616,578)-(1698,649)` bölgesinde kırmızı uyarı hedefi aranır (renk + `uyari.png`) | — |
| 2 | Bulunursa bölge merkezine tıkla | yok |
| 3 | Ekranın açılmasını bekle | **1.0 sn** |
| 4 | `(918,305)-(1095,389)` bölgesi OCR'lanır, "Kıyamet Eliti" + seviye>24 kontrolü yapılır | — |
| 5 | Şart sağlanmazsa ESC basılıp çıkılır | — |
| 6 | Şart sağlanırsa `(831,272)-(899,341)`'de yeşil artı aranır; bulunursa merkezine tıkla | — |
| 7 | Saldır tıklaması `(856,746)` | **1.5 sn** (`arti_click_delay_seconds`) |
| 8 | Akış biter | sonrasında **1.0 sn** bekle |

Artı bulunamazsa: ESC basılır.

---

## 7. Sürekli arka plan taramaları (her ana döngü turunda, tuşla tetiklenmiyor)

| Taranan | Bölge | Bulununca |
|---|---|---|
| `disconnect.png` | `game_monitor.disconnect_scan_region` = `(647,331)-(1074,653)` | `(860,544)`'e tıkla, oyunu yeniden başlat (bölüm 8) |
| `oyundanCikNew.png` | `game_monitor.popup_scan_region` = `(647,331)-(1074,653)` | ESC bas |
| `paylas.png` | `text_scan_region` = `(604,165)-(1105,846)` | ESC bas |
| Periyodik ESC | — | `E` açıksa (varsayılan açık) her **300 sn**'de (`escape_interval_seconds`) bir ESC bas |

---

## 8. Oyun kapanma / yeniden başlatma akışı — otomatik tetiklenir

Tetikleyiciler: `disconnect.png` bulunması **veya** 5 dakikada bir yapılan pencere kontrolünün pencereyi bulamaması.

| # | Adım | Bekleme |
|---|---|---|
| 1 | Oyun süreci hâlâ çalışıyor mu kontrol edilir | **1 sn** |
| 2a | **Çalışıyorsa**: pencere bulunup yeniden 1717×965'e sabitlenir | — |
| 2b | **Çalışmıyorsa**: yeniden başlatmadan önce bekle | **60 sn** (`restart_delay_seconds`) |
| 3 | Oyun başlatılır, pencere aranır | en fazla **40 sn** (`window_wait_seconds`) |
| 4 | Pencere sabitlenir, başlangıç tıklamaları tekrar yapılır (bölüm 1, adım 7-8) | — |

---

## 9. Klavye kısayolları (`pynput` global dinleyici)

| Tuş | İşlev |
|---|---|
| `S` | Botu durdurur |
| `J` | Bir sonraki sol tıklamanın koordinatını loglar — **hook değil**, `GetAsyncKeyState` ile 20ms aralıklarla yoklama yapar (oyun mouse girdisini özel yakaladığında normal hook çalışmıyordu), 15 sn içinde tıklama gelmezse iptal olur. Pencere bu bekleme sırasında yeniden başlarsa hata vermeden sadece ekran koordinatını loglar |
| `O` | Manuel metin taraması: `(1075,243)`'e tıklar (0.5 sn bekleyip), sonra `text_scan_region`'ı OCR'lar |
| `T` | Kırmızı çerçeveli debug ekran görüntüsü modunu aç/kapat — kod içinde taranan **6 bölgenin hepsini** işaretler: `kazi_arama`, `mesaj_ekrani`, `cikis_arama`, `disconnect_arama`, `sayac_arama`, `tren_arama` |
| `E` | Periyodik ESC döngüsünü (300 sn, varsayılan açık) aç/kapat |
| `R` | Uyarı/Artı taramasını (bölüm 6) aç/kapat |
| `P` | Tren taramasını (bölüm 5) aç/kapat — varsayılan kapalı |
| ~~`K`, `Z`~~ | Kaldırıldı — `activities` (kazı-activity ve gold_zombie) boş şablon klasörlerine bakıyordu, hiçbir işlevi yoktu, config'ten ve png'den tamamen silindi |

---

## Mimari / Dosyalar

| Dosya | Rolü |
|---|---|
| [main.py](main.py) | Tüm bot mantığı: pencere yönetimi, görüntü eşleştirme, OCR, tıklama otomasyonu, ana döngü (`run_bot`) |
| [parameters/config.json](parameters/config.json) | Tüm davranışı yönlendiren merkezi ayar dosyası — hemen hemen hiçbir sayı/koordinat kod içine gömülü değil |
| [tesseract_bin/](tesseract_bin) | Taşınabilir Tesseract OCR (exe + dll + tur/eng tessdata) — hedef PC'de Tesseract kurulu olmasa da çalışsın diye |
| [png/](png) | Şablon eşleştirme için referans ikon görselleri (`tren.png` dahil) |
| [kutuphane/kisayollar.log](kutuphane) | Her açılışta kısayolların yazıldığı log |
| [LastWarBot.spec](LastWarBot.spec), [build_exe.ps1](build_exe.ps1) | PyInstaller derleme yapılandırması (`contents_directory='.'` ile düz klasör yapısı, `tesseract_bin` dahil) |
| [logs/](logs) | `application.log` (genel çalışma + OCR/sayaç logları) ve `startup.log` (başlangıç/kritik hata) |
| [screenShots/](screenShots) | `T` debug modunda kaydedilen kırmızı çerçeveli ekran görüntüleri |

## Teknik notlar

- **Sabit pencere boyutu**: Tüm koordinatlar 1717×965 referans boyutuna göre kalibre edildi; pencere artık ekran çözünürlüğüne göre orantılanmıyor (eskiden öyleydi, PC'ler arası koordinat kaymasına sebep oluyordu).
- **OCR eşleştirme**: `pytesseract.image_to_data` ile kelime/kutu koordinatları alınıp `difflib.SequenceMatcher` ile bulanık eşleştirme yapılıyor (Türkçe İ/I/ı normalizasyonu dahil).
- **J kısayolu**: Global mouse hook yerine `GetAsyncKeyState` polling kullanıyor — bazı PC'lerde oyunun mouse girdisini özel yakalaması normal hook'u engelliyordu.
- **`bring_game_to_front` kararlılık düzeltmesi**: `pygetwindow`'un `restore()`/`activate()` metotları, işlem gerçekte başarılı olsa bile Windows'un eski/alakasız bir `GetLastError()` koduyla sahte istisna fırlatabiliyordu (botu rastgele çökertiyordu). Artık bu iki çağrı `try/except` ile sarılı; asıl pencere-öne-getirme işini zaten yapan ctypes çağrıları (`ShowWindow`/`BringWindowToTop`/`SetForegroundWindow`) etkilenmiyor.
- **`scan_cases` her case için kendi tarama bölgesini tanımlayabiliyor** (`scan_region` anahtarı, opsiyonel) — kazı/yonca ortak `scan_region`'ı kullanıyor, tren kendi dar bölgesini kullanıyor. Her case ayrıca `enabled: false` ile tamamen devre dışı bırakılabiliyor (tren'de kullanılan mekanizma).
- **Zaman damgaları**: Loglardaki `dd.mm.yyyy` formatı yıl kaldırılıp `dd.mm hh:mi` haline getirildi (dosya adlarındaki `ddmmyyyy` formatına dokunulmadı).
- **`activities` sistemi** (eski K/Z kısayolları) tamamen kaldırıldı — boş şablon klasörlerine bakıp hiçbir şey yapmıyorlardı.
