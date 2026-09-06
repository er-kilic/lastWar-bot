import json
import os
from pathlib import Path
import pytesseract

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# config.json dosyasını yükle
config = {}
if CONFIG_PATH.exists():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

LOCAL_TESSERACT = BASE_DIR / "tesseract_bin" / "tesseract.exe"

# Tesseract yolunu belirle
if LOCAL_TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(LOCAL_TESSERACT)
    os.environ["TESSDATA_PREFIX"] = str(BASE_DIR / "tesseract_bin" / "tessdata")
else:
    pytesseract.pytesseract.tesseract_cmd = config.get("ocr", {}).get(
        "tesseract_cmd", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

print(f"Kullanılan Tesseract yolu: {pytesseract.pytesseract.tesseract_cmd}")