from pathlib import Path
import cv2
import numpy as np

PNG_DIR = Path("png")

def auto_crop_icon(image_path):
    img = cv2.imread(str(image_path))
    if img is None:
        return

    # Sarı balonu ve dış zemini ayırmak için HSV renk uzayı
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Sarı balon rengi aralığı (balonun kendisini tespit edip maskeler)
    lower_yellow = np.array([15, 80, 80])
    upper_yellow = np.array([35, 255, 255])
    yellow_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    # İkonlar sarıdan farklıdır (Megafon mor/kırmızı, NEW kırmızı/beyaz, Kepçe turuncu/siyah, Yonca parlak altın)
    # Merkezdeki %70'lik alana odaklan
    h, w = img.shape[:2]
    center_y, center_x = h // 2, w // 2
    r_y, r_x = int(h * 0.28), int(w * 0.28)

    # Doğrudan merkezdeki sembolü al
    cropped = img[center_y - r_y : center_y + r_y, center_x - r_x : center_x + r_x]
    
    cv2.imwrite(str(image_path), cropped)
    print(f"Tam merkezden temiz kırpıldı: {image_path.name} -> {cropped.shape[1]}x{cropped.shape[0]} px")

# Sadece sorun yaratanları kırp (yoncayı olduğu gibi bırakabilirsin)
targets = ["yonca.png"]

for name in targets:
    p = PNG_DIR / name
    if p.exists():
        auto_crop_icon(p)