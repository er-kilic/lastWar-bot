# LastWarBot — Proje Özeti

Windows üzerinde çalışan, **"Last War: Survival"** mobil/PC oyununu ekran görüntüsü + görüntü/OCR tanıma ile otomatikleştiren bir masaüstü bot. Python ile yazılmış, PyInstaller ile tek `.exe` haline getirilebiliyor.

## Ne yapıyor?

Bot, oyunun penceresini bulup küçük bir boyuta sabitliyor, ardından sürekli döngüde ekran görüntüsü alıp belirli PNG şablonlarını ve OCR ile metinleri arıyor; eşleşme bulunca önceden tanımlı koordinatlara tıklıyor. Temel olarak şu işleri otomatikleştiriyor:

- **Oyunu başlatma/izleme**: Oyun kapalıysa `LastWarLauncher.exe`'yi başlatır, pencereyi bulur, ekranın belirli bir oranına göre yeniden boyutlandırıp sol üste sabitler, başlangıç tıklamalarını yapar.
- **Bağlantı kopması / restart yönetimi**: Kırmızı "disconnect" popup'ını tespit edip oyunu yeniden başlatıyor (`restart_game_after_disconnect`).
- **Periyodik ESC izleme**: Popup'ları kapatmak için belirli aralıklarla ESC tuşuna basıyor.
- **Kazı (excavation) aktivitesi**: `kazi.png` şablonunu bulup tıklıyor, OCR ile "Hazineyi kaz" gibi metinleri doğruluyor, takımları seçip saldırı yapıyor, saldırı sonrası "paylaş" ekranını bekleyip kapatıyor.
- **Yonca / Şanslı Hediye** aktivitesi: benzer şablon+OCR akışıyla otomatik açılıyor.
- **"Uyarı/Artı" akışı** (`handle_uyari_scan`): Kırmızı uyarı butonunu bulup tıklıyor, OCR ile hedefin "Kıyamet Eliti" ve seviye > 24 olup olmadığını kontrol ediyor, uygunsa yeşil artı butonunu bulup saldırı tetikliyor.
- **Gold Zombie** aktivitesi (config'de var, şu an `enabled: false`).
- **Klavye/mouse kısayolları** (pynput ile global listener):
  - `S`: botu durdur
  - `J`: sonraki tıklamanın koordinatını logla (debug)
  - `O`: metin bölgesini tara ve logla
  - `T`: kırmızı çerçeveli debug ekran görüntüsü aç/kapat
  - `E`: periyodik ESC döngüsünü aç/kapat
  - `R`: Uyarı/Artı taramasını aç/kapat
  - `K`, `Z` gibi harfler: `config.json > activities` içindeki kısayollarla eşleşen aktiviteleri aç/kapat

## Mimari / Dosyalar

| Dosya | Rolü |
|---|---|
| [main.py](main.py) | Tüm bot mantığı (~1200 satır): pencere yönetimi, görüntü eşleştirme (OpenCV template matching), OCR (Tesseract), tıklama otomasyonu, ana döngü (`run_bot`) |
| [parameters/config.json](parameters/config.json) | Tüm davranışı yönlendiren merkezi ayar dosyası: oyun yolu, tarama bölgeleri, güven eşikleri, koordinatlar, kısayollar, aktivite tanımları |
| [tesseract.py](tesseract.py) | Tesseract OCR binary yolunu config'ten veya taşınabilir `tesseract_bin/` klasöründen ayarlayan yardımcı script |
| [imageTransfer.py](imageTransfer.py) | Tek seferlik görsel işleme scripti — `png/yonca.png` gibi ikonları merkezden kırpmak için |
| [png/](png) | Şablon eşleştirme için kullanılan referans ikon görselleri (kazı, yonca, disconnect, uyarı vb.) |
| [LastWarBot.spec](LastWarBot.spec), [main.spec](main.spec), [build_exe.ps1](build_exe.ps1) | PyInstaller ile `.exe` derleme yapılandırması |
| [logs/](logs) | `application.log` (genel çalışma logu) ve `startup.log` (başlangıç/kritik hata logu) |
| [screenShots/](screenShots) | Debug modunda kaydedilen, tarama bölgelerini kırmızı çerçeveyle işaretleyen ekran görüntüleri |

## Teknik yaklaşım

- **Görüntü tanıma**: OpenCV `matchTemplate` (gri tonlama, çoklu ölçek desteği) ile PNG şablon eşleştirme.
- **Renk tespiti**: HSV maskeleme ile kırmızı/mavi/yeşil buton/durum tespiti (disconnect, çıkış, artı butonu, uyarı butonu).
- **OCR**: `pytesseract` (Tesseract OCR, tur+eng dil desteği) — hem düz metin okuma hem `image_to_data` ile kelime/kutu koordinatlarına göre hedef metni bulup tıklama. Bulanık eşleştirme için `difflib.SequenceMatcher` kullanılıyor (Türkçe karakter normalizasyonu da var: İ/I/ı → i).
- **Config-driven tasarım**: Neredeyse tüm koordinatlar, eşikler, bölgeler ve aktivite tanımları kod içinde değil `config.json`'da — davranışı değiştirmek için genelde kod değişmeden sadece config güncelleniyor.
- **Loglama**: `logging` modülüyle iki ayrı log dosyasına (genel + başlangıç) yazılıyor; yakalanmamış istisnalar `sys.excepthook` ile loglanıyor.

## Bağımlılıklar

`requirements.txt`: PyAutoGUI, PyGetWindow, opencv-python, numpy, Pillow, pynput, pytesseract, pyinstaller.

## Dikkat çeken noktalar

- Proje tamamen ekran koordinatlarına ve sabit pencere boyutuna dayalı olduğu için oyun arayüzü değiştiğinde veya farklı bir ekran çözünürlüğünde koordinatlar/bölgeler yeniden ayarlanmalı.
- `build/` ve `dist/` klasörlerinde önceden derlenmiş `.exe` çıktıları mevcut; `.venv/` sanal ortamı da repo içinde duruyor.
- `kutuphane/` klasörü boş görünüyor (muhtemelen taşınabilir Tesseract binary'si için ayrılmış, henüz içerik yok veya git tarafından yok sayılıyor).
