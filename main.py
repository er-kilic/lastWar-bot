import ctypes
import difflib
import json
import logging
import os
import re
import sys
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
import pyautogui
import pygetwindow
import pytesseract
from pytesseract import TesseractNotFoundError
from pynput import keyboard

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


ROOT = Path(
    sys.executable if getattr(sys, "frozen", False) else __file__
).resolve().parent
PARAMETERS_DIR = ROOT / "parameters"
PNG_DIR = ROOT / "png"
CONFIG_PATH = PARAMETERS_DIR / "config.json"
PORTABLE_TESSERACT_DIR = ROOT / "tesseract_bin"
PORTABLE_TESSERACT_EXE = PORTABLE_TESSERACT_DIR / "tesseract.exe"
SCREENSHOTS_DIR = ROOT / "screenShots"
LOGS_DIR = ROOT / "logs"
APP_LOG_PATH = LOGS_DIR / "application.log"
STARTUP_LOG_PATH = LOGS_DIR / "startup.log"
KUTUPHANE_DIR = ROOT / "kutuphane"
SHORTCUTS_LOG_PATH = KUTUPHANE_DIR / "kisayollar.log"
FOUND_LOG_PATH = LOGS_DIR / "bulunanlar.log"

APP_LOGGER = logging.getLogger("last_war_bot")
STARTUP_LOGGER = logging.getLogger("last_war_bot_startup")


def log(message):
    """Konsola yazdirir ve ayni satiri logs/application.log'a da yazar.
    Ikinci bir PC'de basarisiz olan bir eslesme gibi durumlarda, konsol
    kapandiktan sonra da ne oldugunu gorebilmek icin tum print() cikisi
    burdan geciyor."""
    print(message)
    APP_LOGGER.info(message)


def configure_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    APP_LOGGER.setLevel(logging.INFO)
    app_handler = logging.FileHandler(APP_LOG_PATH, encoding="utf-8")
    app_handler.setFormatter(formatter)
    APP_LOGGER.addHandler(app_handler)

    STARTUP_LOGGER.setLevel(logging.INFO)
    startup_handler = logging.FileHandler(
        STARTUP_LOG_PATH,
        encoding="utf-8",
    )
    startup_handler.setFormatter(formatter)
    STARTUP_LOGGER.addHandler(startup_handler)


def log_uncaught_exception(exception_type, exception, traceback):
    if issubclass(exception_type, KeyboardInterrupt):
        sys.__excepthook__(exception_type, exception, traceback)
        return

    APP_LOGGER.critical(
        "Yakalanmamis hata",
        exc_info=(exception_type, exception, traceback),
    )
    STARTUP_LOGGER.critical(
        "EXE baslangic/calisma hatasi",
        exc_info=(exception_type, exception, traceback),
    )


def configure_tesseract(config):
    if PORTABLE_TESSERACT_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(PORTABLE_TESSERACT_EXE)
        os.environ["TESSDATA_PREFIX"] = str(PORTABLE_TESSERACT_DIR / "tessdata")
        log(f"Tasinabilir Tesseract kullaniliyor: {PORTABLE_TESSERACT_EXE}")
        return

    tesseract_cmd = config.get("ocr", {}).get("tesseract_cmd", "")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = os.path.expanduser(
            tesseract_cmd
        )


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    configure_tesseract(config)
    return config


def is_game_running(executable_name):
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {executable_name}"],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )
    return executable_name.lower() in result.stdout.lower()


def start_game(config):
    executable = Path(config["game"]["executable_path"]).expanduser()
    executable_name = executable.name

    if is_game_running(executable_name):
        log("Oyun zaten acik; tekrar baslatilmadi.")
        return False

    if not executable.exists():
        raise FileNotFoundError(f"Oyun bulunamadi: {executable}")

    # Oyunu bot prosesinden ayir; bot durdurulsa bile oyun acik kalir.
    detached_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
    )
    subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        creationflags=detached_flags,
        close_fds=True,
    )
    log("Oyun baslatildi.")
    return True


def find_game_window(config):
    title_part = config["game"]["window_title_contains"].lower()
    windows = [
        window
        for window in pygetwindow.getAllWindows()
        if window.title and title_part in window.title.lower()
    ]
    return windows[0] if windows else None


def get_target_window_size(config):
    """Tum PC'lerde ayni piksel boyutuna sabitlenmis oyun penceresi boyutu.

    Config.json'daki tum koordinatlar bu sabit boyuta gore kalibre edildi;
    ekran cozunurlugune gore orantilamiyoruz ki koordinatlar PC'den PC'ye
    degismesin.
    """
    game_config = config["game"]
    width = game_config["window_width"]
    height = game_config["window_height"]

    screen_width, screen_height = pyautogui.size()
    if screen_width < width or screen_height < height:
        log(
            f"UYARI: Ekran cozunurlugu ({screen_width}x{screen_height}) "
            f"hedef pencere boyutundan ({width}x{height}) kucuk."
        )

    return width, height


def resize_and_position_game(window, config):
    width, height = get_target_window_size(config)

    window.restore()
    window.moveTo(0, 0)
    window.resizeTo(width, height)
    window.activate()
    bring_game_to_front(window)
    log(f"Oyun penceresi {width}x{height} boyutuna sol uste tasindi.")


def enforce_game_window_size(window, config):
    resize_config = config["game"]
    retries = resize_config.get("resize_retries", 5)
    delay = resize_config.get("resize_retry_delay_seconds", 1.0)
    target_width, target_height = get_target_window_size(config)

    for attempt in range(retries):
        if window.width != target_width or window.height != target_height:
            resize_and_position_game(window, config)
        else:
            window.moveTo(0, 0)
            bring_game_to_front(window)
        if attempt < retries - 1:
            time.sleep(delay)

    window.moveTo(0, 0)
    bring_game_to_front(window)


def perform_startup_clicks(config, window=None):
    startup = config.get("startup_actions", {})
    if not startup.get("enabled", True):
        return

    initial_delay = startup.get("initial_delay_seconds", 1.0)
    time.sleep(initial_delay)

    delay = startup.get("click_delay_seconds", 0.5)
    for coordinate in startup.get("click_coordinates", []):
        pyautogui.click(coordinate[0], coordinate[1])
        log(f"Baslangic tiklamasi: ({coordinate[0]}, {coordinate[1]})")
        time.sleep(delay)

    if startup.get("press_escape_after_clicks", True):
        escape_delay = startup.get("escape_delay_after_clicks_seconds", 1.0)
        time.sleep(escape_delay)
        # ESC bir tus vurusu oldugu icin (tiklamalar gibi imlec konumuna
        # bagli degil) sadece oyun penceresi o an klavye odaginda ise
        # etkili oluyor; odak baska bir yere kaymissa (yukleme ekrani,
        # konsol penceresi vb.) ESC oyuna hic ulasmiyordu. Basmadan once
        # pencereyi tekrar one getirip odagi garantiliyoruz.
        if window is not None:
            bring_game_to_front(window)
        pyautogui.press("esc")
        log(f"Baslangic tiklamalarindan {escape_delay} saniye sonra ESC basildi.")

        post_esc_coordinate = startup.get("post_escape_click_coordinate", [1651, 900])
        pyautogui.click(post_esc_coordinate[0], post_esc_coordinate[1])
        log(
            f"ESC sonrasi ({post_esc_coordinate[0]}, {post_esc_coordinate[1]}) "
            "tiklandi."
        )


def monitor_game_state(config, next_escape_at, allow_escape=True, escape_state=None):
    monitor = config.get("game_monitor", {})
    screenshot = pyautogui.screenshot()
    exit_region = get_region_tuple(monitor["popup_scan_region"])
    def crop_region(region):
        return screenshot.crop(
        (
            region[0],
            region[1],
            region[0] + region[2],
            region[1] + region[3],
        )
        )

    exit_image = crop_region(exit_region)
    disconnect_region = get_region_tuple(monitor["disconnect_scan_region"])
    disconnect_image = crop_region(disconnect_region)
    confidence = monitor.get(
        "popup_image_confidence",
        config["bot"]["image_confidence"],
    )

    disconnect = find_template_center(
        disconnect_image,
        PNG_DIR / monitor["disconnect_template"],
        confidence,
        monitor.get("disconnect_template_scales"),
    )
    if disconnect:
        coordinate = monitor["disconnect_click_coordinate"]
        pyautogui.click(coordinate[0], coordinate[1])
        log(
            "disconnect.png bulundu; cikis tiklamasi yapildi: "
            f"({coordinate[0]}, {coordinate[1]})"
        )
        return "restart", next_escape_at

    bakim_click = find_template_offset_click(
        exit_image,
        PNG_DIR / monitor.get("bakim_template", "bakim.png"),
        confidence,
        monitor.get("bakim_confirm_offset_fraction", [0.714, 0.737]),
        monitor.get("bakim_template_scales", [0.9, 0.95, 1.0, 1.05, 1.1]),
    )
    if bakim_click:
        abs_x = exit_region[0] + bakim_click[0]
        abs_y = exit_region[1] + bakim_click[1]
        pyautogui.click(abs_x, abs_y)
        log(f"bakim.png bulundu; Onayla tiklandi -> ({abs_x}, {abs_y})")

    if allow_escape and time.monotonic() >= next_escape_at:
        interval = monitor.get("escape_interval_seconds", 15)
        is_first_check = escape_state is not None and not escape_state.get("first_done")
        if not is_first_check:
            coordinate = monitor.get("periodic_click_coordinate", [1651, 900])
            click_count = monitor.get("periodic_click_count", 2)
            click_between = monitor.get("periodic_click_between_seconds", 1.0)
            for click_index in range(click_count):
                pyautogui.click(coordinate[0], coordinate[1])
                if click_index < click_count - 1:
                    time.sleep(click_between)
            log(
                f"Oyun kontrolu icin ({coordinate[0]}, {coordinate[1]}) "
                f"{click_count} kez {click_between}sn arayla tiklandi "
                f"({interval} saniye aralikla)."
            )
        else:
            escape_state["first_done"] = True
        next_escape_at = time.monotonic() + interval

    exit_button = find_template_center(
        exit_image,
        PNG_DIR / monitor["exit_template"],
        confidence,
        monitor.get("exit_template_scales"),
    )
    if exit_button:
        pyautogui.press("esc")
        log("oyundanCikNew.png bulundu; ESC basildi.")
        next_escape_at = time.monotonic() + monitor.get(
            "escape_interval_seconds",
            15,
        )

    paylas_region = get_region_tuple(config["text_scan_region"])
    paylas_image = crop_region(paylas_region)
    paylas_template = config.get("post_attack", {}).get("template", "paylas.png")
    paylas_match = find_template_center(
        paylas_image,
        PNG_DIR / paylas_template,
        confidence,
    )
    if paylas_match:
        pyautogui.press("esc")
        log("paylas.png bulundu (surekli tarama); ESC basildi.")

    return None, next_escape_at


def check_disconnect_and_bakim(config):
    """disconnect.png ve bakim.png icin tek atimlik hizli kontrol.
    monitor_game_state ana dongude her turda bu ikisini zaten kontrol
    ediyor, ama kazi saldirisinin bekleme/tiklama dongusu (45sn+75sn
    gibi) ana donguyu tamamen bloke ettigi icin o sirada disconnect
    veya bakim ekrani cikarsa hic fark edilmiyordu. Bu fonksiyon o
    bloke eden dongulerin icinden periyodik olarak cagirilip ayni
    kontrolu yapar. Disconnect bulunup tiklandiysa True doner (cagiran
    taraf saldiriyi kesip oyunu yeniden baslatma sinyali vermeli);
    bakim bulunup Onayla tiklanmis olsa da False doner (bakim,
    disconnect gibi oyunu kapatmiyor, saldiriya devam edilebilir)."""
    monitor = config.get("game_monitor", {})
    screenshot = pyautogui.screenshot()

    def crop(region):
        return screenshot.crop(
            (region[0], region[1], region[0] + region[2], region[1] + region[3])
        )

    confidence = monitor.get(
        "popup_image_confidence",
        config["bot"]["image_confidence"],
    )

    disconnect_region = get_region_tuple(monitor["disconnect_scan_region"])
    disconnect = find_template_center(
        crop(disconnect_region),
        PNG_DIR / monitor["disconnect_template"],
        confidence,
        monitor.get("disconnect_template_scales"),
    )
    if disconnect:
        coordinate = monitor["disconnect_click_coordinate"]
        pyautogui.click(coordinate[0], coordinate[1])
        log(
            "disconnect.png bulundu (kazi beklerken); cikis tiklamasi "
            f"yapildi: ({coordinate[0]}, {coordinate[1]})"
        )
        return True

    exit_region = get_region_tuple(monitor["popup_scan_region"])
    bakim_click = find_template_offset_click(
        crop(exit_region),
        PNG_DIR / monitor.get("bakim_template", "bakim.png"),
        confidence,
        monitor.get("bakim_confirm_offset_fraction", [0.714, 0.737]),
        monitor.get("bakim_template_scales", [0.9, 0.95, 1.0, 1.05, 1.1]),
    )
    if bakim_click:
        abs_x = exit_region[0] + bakim_click[0]
        abs_y = exit_region[1] + bakim_click[1]
        pyautogui.click(abs_x, abs_y)
        log(f"bakim.png bulundu (kazi beklerken); Onayla tiklandi -> ({abs_x}, {abs_y})")

    return False


def restart_game_after_disconnect(config):
    executable = Path(config["game"]["executable_path"]).expanduser()
    time.sleep(1)
    if is_game_running(executable.name):
        window = find_game_window(config)
        if window is None:
            raise RuntimeError(
                "Oyun prosesi acik ancak penceresi bulunamadi; "
                "yeniden baslatma atlandi."
            )
        log("Disconnect sonrasi oyun zaten acik; yeniden baslatma atlandi.")
        enforce_game_window_size(window, config)
        return window

    wait_seconds = config["game_monitor"].get("restart_delay_seconds", 60)
    log(f"Oyun yeniden baslatilmadan once {wait_seconds} saniye beklenecek.")
    time.sleep(wait_seconds)
    start_game(config)
    timeout = config["game"]["window_wait_seconds"]
    deadline = time.time() + timeout
    window = None
    while time.time() < deadline:
        window = find_game_window(config)
        if window:
            break
        time.sleep(1)
    if window is None:
        raise RuntimeError("Oyun yeniden baslatildi ancak pencere bulunamadi.")
    enforce_game_window_size(window, config)
    perform_startup_clicks(config, window)
    return window


def position_console_window(config):
    """Botun kendi konsol penceresini, coklu monitor de dahil, sanal ekranin
    en sag kenarina (ya da config'te belirtilen konuma) tasir."""
    console_config = config.get("console_window", {})
    if not console_config.get("enabled", True):
        return

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if not hwnd:
        return

    user32 = ctypes.windll.user32
    SM_XVIRTUALSCREEN = 76
    SM_CXVIRTUALSCREEN = 78
    virtual_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    virtual_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    virtual_right = virtual_left + virtual_width

    width = console_config.get("width", 350)
    height = console_config.get("height", 900)
    x = console_config.get("x", virtual_right - width)
    y = console_config.get("y", 0)

    user32.MoveWindow(hwnd, x, y, width, height, True)
    log(
        f"Konsol penceresi ({x}, {y}) konumuna, {width}x{height} "
        "boyutuna tasindi."
    )


def bring_game_to_front(window):
    """Pencereyi Windows masaustunde gorunur ve odakta tutar."""
    # pygetwindow'un restore()/activate() metotlari, islem aslinda basarili
    # olsa bile Windows'un eski/alakasiz bir GetLastError degeri yuzunden
    # sahte PyGetWindowException firlatabiliyor (bkz. loglardaki tekrarlayan
    # cokmeler). Asagidaki ctypes cagrilari zaten pencereyi guvenilir sekilde
    # one getiriyor, o yuzden bu sahte hatalari yutuyoruz.
    try:
        window.restore()
    except Exception:
        pass
    try:
        window.activate()
    except Exception:
        pass

    # PyGetWindow, Windows penceresinin HWND degerini bu alanda tutar.
    hwnd = getattr(window, "_hWnd", None)
    if hwnd:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

def find_template_center(
    screenshot,
    template_path,
    confidence,
    template_scales=None,
    debug_label=None,
):
    screenshot_gray = cv2.cvtColor(
        np.array(screenshot),
        cv2.COLOR_RGB2GRAY,
    )
    original_template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if original_template is None:
        raise RuntimeError(f"PNG okunamadi: {template_path}")

    screenshot_height, screenshot_width = screenshot_gray.shape[:2]
    scales = template_scales or [1.0]
    best_match = None
    for scale in scales:
        template = cv2.resize(
            original_template,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_LINEAR,
        )
        template_height, template_width = template.shape[:2]
        if template_width > screenshot_width or template_height > screenshot_height:
            continue

        result = cv2.matchTemplate(
            screenshot_gray,
            template,
            cv2.TM_CCOEFF_NORMED,
        )
        _, maximum_value, _, maximum_location = cv2.minMaxLoc(result)
        if best_match is None or maximum_value > best_match[0]:
            best_match = (
                maximum_value,
                maximum_location,
                template_width,
                template_height,
            )

    if debug_label:
        log(f"[SABLON SKORU] {debug_label}: en iyi skor={best_match[0] if best_match else None}, esik={confidence}")

    if best_match is None or best_match[0] < confidence:
        return None

    _, maximum_location, template_width, template_height = best_match
    left, top = maximum_location
    return (
        left + template_width // 2,
        top + template_height // 2,
    )

def find_template_offset_click(
    screenshot,
    template_path,
    confidence,
    offset_fraction,
    template_scales=None,
    debug_label=None,
):
    """find_template_center gibi sablonu arar, ama merkez yerine sablonun
    icindeki SABIT bir noktayi (orn. bir onay butonunun konumunu) dondurur.
    offset_fraction (x_frac, y_frac) sablonun kendi genislik/yuksekligine
    orantili (0-1 arasi) bir konum; boylece template_scales listesindeki
    hangi olcek eslesirse eslessin dogru noktaya isaret eder."""
    screenshot_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    original_template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if original_template is None:
        raise RuntimeError(f"PNG okunamadi: {template_path}")

    screenshot_height, screenshot_width = screenshot_gray.shape[:2]
    scales = template_scales or [1.0]
    best_match = None
    for scale in scales:
        template = cv2.resize(original_template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        template_height, template_width = template.shape[:2]
        if template_width > screenshot_width or template_height > screenshot_height:
            continue
        result = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
        _, maximum_value, _, maximum_location = cv2.minMaxLoc(result)
        if best_match is None or maximum_value > best_match[0]:
            best_match = (maximum_value, maximum_location, template_width, template_height)

    if debug_label:
        log(f"[SABLON SKORU] {debug_label}: en iyi skor={best_match[0] if best_match else None}, esik={confidence}")

    if best_match is None or best_match[0] < confidence:
        return None

    _, maximum_location, template_width, template_height = best_match
    left, top = maximum_location
    x_frac, y_frac = offset_fraction
    return (
        left + round(template_width * x_frac),
        top + round(template_height * y_frac),
    )

def get_activity_templates(activity):
    template_paths = []
    for pattern in activity["template_patterns"]:
        template_paths.extend(PNG_DIR.glob(pattern))
    return sorted(set(template_paths))


def get_scan_region(config):
    top_left = config["scan_region"]["top_left"]
    bottom_right = config["scan_region"]["bottom_right"]
    return get_region_tuple(
        {
            "top_left": top_left,
            "bottom_right": bottom_right,
        }
    )


def get_region_tuple(region):
    top_left = region["top_left"]
    bottom_right = region["bottom_right"]
    left = min(top_left[0], bottom_right[0])
    top = min(top_left[1], bottom_right[1])
    width = abs(bottom_right[0] - top_left[0])
    height = abs(bottom_right[1] - top_left[1])
    if width == 0 or height == 0:
        raise ValueError("Tarama bolgesi sifir genislik veya yukseklikte.")
    return left, top, width, height


def capture_debug_screenshot(window, config, custom_regions=None):
    """Pencere ekran goruntusunu alip belirtilen bolgeleri kirmizi cerceveyle kaydeder."""
    if custom_regions is not None:
        regions = custom_regions
    else:
        regions = [
            ("kazi_arama", config.get("scan_region")),
            ("mesaj_ekrani", config.get("text_scan_region")),
            ("cikis_arama", config.get("game_monitor", {}).get("region")),
            (
                "disconnect_arama",
                config.get("game_monitor", {}).get("disconnect_scan_region"),
            ),
            (
                "tren_arama",
                config.get("scan_cases", {}).get("tren", {}).get("scan_region"),
            ),
            (
                "hastane_yardim_asker_arama",
                {"top_left": [75, 723], "bottom_right": [145, 785]},
            ),
        ]
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Bolgeler ayni pencereyi tariyor (kimi zaman birebir ayni koordinatlari
    # bile paylasiyorlar - orn. cikis_arama/disconnect_arama). Her bolge icin
    # ayri ayri pyautogui.screenshot cagirmak yerine TEK bir pencere
    # goruntusu alip hepsini ondan kirpiyoruz; hem daha hizli, hem de
    # bolgeler arasinda animasyon/parlama kaynakli zamanlama farkini onluyor.
    base_image = cv2.cvtColor(
        np.array(
            pyautogui.screenshot(
                region=(window.left, window.top, window.width, window.height)
            )
        ),
        cv2.COLOR_RGB2BGR,
    )
    image_height, image_width = base_image.shape[:2]
    scale_x = image_width / window.width
    scale_y = image_height / window.height

    for region_name, region in regions:
        if not region:
            continue
        image = base_image.copy()
        top_left = region["top_left"]
        bottom_right = region["bottom_right"]
        left = round((min(top_left[0], bottom_right[0]) - window.left) * scale_x)
        top = round((min(top_left[1], bottom_right[1]) - window.top) * scale_y)
        right = round((max(top_left[0], bottom_right[0]) - window.left) * scale_x)
        bottom = round((max(top_left[1], bottom_right[1]) - window.top) * scale_y)
        left = max(0, min(left, image_width - 1))
        top = max(0, min(top, image_height - 1))
        right = max(0, min(right, image_width - 1))
        bottom = max(0, min(bottom, image_height - 1))
        if right <= left or bottom <= top:
            continue

        cv2.rectangle(image, (left, top), (right, bottom), (0, 0, 255), 2)
        cv2.putText(
            image,
            region_name,
            (left + 4, max(top + 18, 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
        path = SCREENSHOTS_DIR / f"{region_name}_{timestamp}.png"
        cv2.imwrite(str(path), image)
        log(f"{region_name} icin kirmizi cerceveli ekran goruntusu: {path}")


def saldir_click():
    pyautogui.click(856, 746)
    log("Saldirma tiklamasi: (856, 746)")


def saldirma_click():
    saldir_click()


def burst_click_until_paylas(config, coordinate, duration, click_interval):
    """Verilen konuma, verilen sure boyunca hizli tiklar; paylas.png ekrana
    gelirse hemen durur ve ESC basar. wait_then_burst_click (sabit sureli)
    ve wait_for_sayac_then_burst_click (sayac bazli) tarafindan paylasilan
    ortak tiklama dongusu."""
    post_attack = config["post_attack"]
    paylas_template = PNG_DIR / post_attack.get("template", "paylas.png")
    paylas_region = get_region_tuple(config["text_scan_region"])
    paylas_confidence = config["bot"]["image_confidence"]
    paylas_check_every = post_attack.get("paylas_check_every_clicks", 10)

    log(
        f"{duration} saniye boyunca ({coordinate[0]}, {coordinate[1]}) "
        f"konumuna {click_interval} saniyede bir tiklanacak "
        f"(paylas.png cikarsa erken durulacak)."
    )

    deadline = time.time() + duration
    click_count = 0
    while time.time() < deadline:
        pyautogui.click(coordinate[0], coordinate[1])
        click_count += 1

        if click_count % paylas_check_every == 0:
            screenshot = pyautogui.screenshot(region=paylas_region)
            if find_template_center(screenshot, paylas_template, paylas_confidence):
                pyautogui.press("esc")
                log("paylas.png bulundu; hizli tiklama erken durduruldu ve ESC basildi.")
                return

        time.sleep(click_interval)

    log(f"{duration} saniyelik hizli tiklama tamamlandi.")


def is_kazi_night_hours():
    """Saat 23:00-08:00 arasi gece, 08:00-23:00 arasi gunduz sayilir."""
    hour = datetime.now().hour
    return hour >= 23 or hour < 8


def get_kazi_initial_wait_seconds(config):
    """Gece/gunduz icin farkli bekleme sureleri kullanilir (gece daha
    uzun, 45sn; gunduz daha kisa, 30sn - varsayilanlar)."""
    post_attack = config["post_attack"]
    if is_kazi_night_hours():
        return post_attack.get("initial_wait_seconds_night", 45)
    return post_attack.get("initial_wait_seconds_day", 30)


def get_kazi_click_duration_seconds(config):
    """Gece/gunduz icin farkli hizli tiklama sureleri kullanilir (gece
    daha uzun, 300sn; gunduz kisa, 150sn - varsayilanlar)."""
    post_attack = config["post_attack"]
    if is_kazi_night_hours():
        return post_attack.get("duration_seconds_night", 300)
    return post_attack.get("duration_seconds_day", post_attack.get("duration_seconds", 150))


def wait_then_burst_click(config):
    """Saldiridan sonra sabit bir sure sessizce bekler, sonra sabit bir
    sure boyunca hizli tiklar. Sayac OCR'una bagli degil (guvenilmez
    ciktigi icin kaldirildi), ama paylas.png ekrana gelirse tiklamayi
    hemen durdurup ESC basar; aksi halde bu sirada ana dongu (ve onun
    surekli paylas.png taramasi) bloke oldugu icin ekran gelse de kimse
    fark etmiyordu."""
    post_attack = config["post_attack"]

    initial_wait = get_kazi_initial_wait_seconds(config)
    log(f"Saldiri sonrasi {initial_wait} saniye sessizce bekleniyor.")
    time.sleep(initial_wait)

    duration = get_kazi_click_duration_seconds(config)
    click_interval = post_attack.get("click_interval_seconds", 0.1)
    coordinate = post_attack["click_coordinate"]
    burst_click_until_paylas(config, coordinate, duration, click_interval)


def parse_sayac_seconds(sayac_text):
    """'00:00:39' / '00:39' / '39' gibi OCR ciktilarini toplam saniyeye
    cevirir. Son 3 rakam grubunu (SS, MM, HH) alir; eksik olanlari 0 sayar.
    Ayristirilamazsa (bos/gurultu) None doner.

    OCR bazen saat basamagindaki "0"i "9" gibi okuyup ("00:00:48" ->
    "90:00:48") anlamsiz derecede buyuk bir toplam uretiyor; bu da esik
    kontrolunun (<=15sn) hicbir zaman gerceklesmeyip tarama dongusunun
    guvenlik suresi (max_poll_seconds) dolana kadar surmesine yol
    aciyordu. Bu sayacin gercek gosterebilecegi en yuksek saat degeri
    (6) asilirsa, saat basamaginin gurultu oldugunu kabul edip 0 sayiyoruz.

    Saniye alani gercek sayacta hep 2 haneli gosterildigi icin ("04",
    "40" gibi); OCR bir haneyi kacirip tek hane okursa ("4"), bunu
    onlar hanesi sayip sonuna 0 ekliyoruz (4 -> 40), "04" gibi
    yorumlamiyoruz - gozlemlenen gercek OCR hatasi bu yondeydi.

    OCR bazen saniye kismini hic okuyamayip ':' dan sonrasini bos
    birakiyor (orn. "03: :"). Bu durumda son (saniye) grubu gercekte
    hangi degeri temsil ettigi belirsiz oldugu icin onu tahmin etmek
    yerine guvenli/esik-disi sabit bir deger (60 sn) donuyoruz - boylece
    boyle bir okuma yanlislikla "esige indi" sanilip erken tetiklemeye
    yol acmiyor. Bu kural sadece EN AZ 2 iki nokta ust uste varsa
    (gercek bir HH:MM:SS/MM:SS formati denendigine isaret eder)
    calisiyor - tek basina, gecerli bir ciplak sayinin (orn. "27")
    sonuna OCR gurultusuyle eklenmis TEK bir ":" bu kurali tetiklemez,
    aksi halde gecerli bir okuma (27 -> 27 sn) yanlislikla 60'a
    cevriliyordu (gercek gozlemlenen hata)."""
    text = sayac_text or ""
    if text.count(":") >= 2:
        last_segment = text.rsplit(":", 1)[-1]
        if not re.search(r"\d", last_segment):
            return 60
    digit_groups = re.findall(r"\d+", text)
    if not digit_groups:
        return None
    groups = digit_groups[-3:]
    while len(groups) < 3:
        groups.insert(0, "0")
    hours_str, minutes_str, seconds_str = groups[-3], groups[-2], groups[-1]
    hours, minutes, seconds = int(hours_str), int(minutes_str), int(seconds_str)
    if hours > 6:
        hours = 0
    if len(seconds_str) == 1:
        seconds *= 10
    return hours * 3600 + minutes * 60 + seconds


def scroll_zoom(window, ticks):
    """Harita zoom'unu pencere merkezinde fare tekerlegi ile ticks kadar
    cevirir (pozitif=yakinlas, negatif=uzaklas). Oyunda maksimum zoom'a
    6 tekerlek tikiyla ulasiliyor; sayac metnini daha buyuk/net okumak
    icin bu fonksiyonla once yakinlasip, okuma bitince ayni miktarda
    geri uzaklasiyoruz (aksi halde diger tum tiklama koordinatlari
    normal zoom seviyesine gore kalibre oldugu icin bozulur)."""
    center_x = window.left + window.width // 2
    center_y = window.top + window.height // 2
    pyautogui.moveTo(center_x, center_y)
    direction = 1 if ticks >= 0 else -1
    for _ in range(abs(ticks)):
        pyautogui.scroll(direction)
        time.sleep(0.1)


def run_sayac_zoom_ocr_test(window, config):
    """Q kisayolu: kazi sayacinin zoom yapip OCR ile okunup saniyeye
    cevrilmesi ve esige inince tiklama baslatilmasi kismini, gercek bir
    kazi saldirisi tetiklemeden tek basina test etmek icin. wait_for_
    sayac_then_burst_click ile ayni OCR/esik/dogrulama mantigini kullanir,
    ama L modundan bagimsiz kendi test bolgesini (q_test_sayac_coords)
    okur ve esige inince post_attack.click_coordinate yerine ekranin
    ortasina tiklar. Klavye dinleyicisini bloke etmemek icin ayri bir
    thread'de calistirilir."""
    sayac_coords = config.get(
        "q_test_sayac_coords", {"top_left": [860, 266], "bottom_right": [948, 302]}
    )
    poll_interval = config.get("kazi_sayac_poll_interval_seconds", 1.0)
    max_poll_seconds = config.get("kazi_sayac_max_poll_seconds", 120)
    threshold_seconds = 20
    required_confirmations = 5

    log(
        f"Q -> sayac zoom/OCR testi basladi (esik: {threshold_seconds} sn, "
        f"{required_confirmations} kez ust uste dogrulanacak, "
        f"en fazla {max_poll_seconds} sn beklenecek)."
    )

    zoom_ticks = config.get("kazi_sayac_zoom_ticks", 6)
    log(f"Q testi: harita {zoom_ticks} tik yakinlastiriliyor.")
    scroll_zoom(window, zoom_ticks)
    time.sleep(config.get("kazi_sayac_zoom_settle_seconds", 0.3))

    poll_deadline = time.time() + max_poll_seconds
    consecutive_low_readings = 0
    reached_threshold = False
    while time.time() < poll_deadline:
        sayac_text = read_sayac_text(sayac_coords, config.get("ocr", {}), True)
        total_seconds = parse_sayac_seconds(sayac_text)
        if total_seconds is None:
            log(f"Kazi sayaci okunamadi: '{sayac_text}'")
        else:
            log(f"Kazi sayaci okundu: '{sayac_text}' -> {total_seconds} sn")
            if total_seconds <= threshold_seconds:
                consecutive_low_readings += 1
                log(
                    f"Esik altinda dogrulama {consecutive_low_readings}/"
                    f"{required_confirmations}."
                )
                if consecutive_low_readings >= required_confirmations:
                    reached_threshold = True
                    break
            else:
                if consecutive_low_readings:
                    log("Esik ustunde okuma geldi; dogrulama sayaci sifirlandi.")
                consecutive_low_readings = 0
        time.sleep(poll_interval)

    if not reached_threshold:
        log(
            f"Q testi: sayac {max_poll_seconds} sn icinde esige inmedi; "
            "guvenlik icin tiklamaya baslaniyor."
        )

    center_x = window.left + window.width // 2
    center_y = window.top + window.height // 2
    duration = config.get("kazi_sayac_click_duration_seconds", 40)
    click_interval = config.get("post_attack", {}).get("click_interval_seconds", 0.1)
    log(
        f"Q testi: ekran ortasina ({center_x}, {center_y}) {duration} "
        "saniye boyunca tiklaniyor."
    )
    deadline = time.time() + duration
    while time.time() < deadline:
        pyautogui.click(center_x, center_y)
        time.sleep(click_interval)
    log("Q testi: tiklama tamamlandi.")

    log(f"Q testi: harita {zoom_ticks} tik eski haline uzaklastiriliyor.")
    scroll_zoom(window, -zoom_ticks)
    time.sleep(config.get("kazi_sayac_zoom_settle_seconds", 0.3))
    log("Q testi bitti.")


def wait_for_sayac_then_burst_click(config, window, debug_capture=False):
    """L acikken kazi sonrasi bekleme: sayac_coords bolgesindeki geri
    sayimi OCR ile izler, deger esik (varsayilan 30) saniyeye ust uste
    N kez (varsayilan 5) indiginde burst-click'e gecer. Tek bir dusuk
    okumayla hemen tetiklemek yerine ust uste dogrulama istenmesinin
    nedeni, OCR'in ara sira "03: :" gibi saniye kismi eksik/bozuk
    ciktilar uretip yanlislikla cok erken tetiklemesini onlemek (bu
    tur bozuk ciktilar parse_sayac_seconds tarafindan zaten esik-disi
    60 sn'ye cevriliyor, ama yine de ek bir guvenlik katmani olarak
    dogrulama sayisi tutuluyor). Esik ustunde gelen bir okuma dogrulama
    sayacini sifirlar; okunamayan (bos) okumalar sayaci etkilemez.
    Sayac beklenen surede esige inmezse (guvenlik onlemi) yine de
    tiklamaya baslar, sonsuza dek beklemez."""
    post_attack = config["post_attack"]
    sayac_coords = config.get(
        "kazi_sayac_coords", {"top_left": [811, 334], "bottom_right": [894, 378]}
    )
    poll_interval = config.get("kazi_sayac_poll_interval_seconds", 1.0)
    max_poll_seconds = config.get("kazi_sayac_max_poll_seconds", 120)
    threshold_seconds = config.get("kazi_sayac_threshold_seconds", 30)
    required_confirmations = config.get("kazi_sayac_confirmations_required", 5)

    log(
        f"Kazi sayaci izleniyor (esik: {threshold_seconds} sn, "
        f"{required_confirmations} kez ust uste dogrulanacak, "
        f"en fazla {max_poll_seconds} sn beklenecek)."
    )

    zoom_ticks = config.get("kazi_sayac_zoom_ticks", 6)
    log(f"Sayac okumasi icin harita {zoom_ticks} tik yakinlastiriliyor.")
    scroll_zoom(window, zoom_ticks)
    time.sleep(config.get("kazi_sayac_zoom_settle_seconds", 0.3))

    empty_readings_limit = config.get("kazi_sayac_empty_readings_limit", 10)

    poll_deadline = time.time() + max_poll_seconds
    consecutive_low_readings = 0
    consecutive_empty_readings = 0
    reached_threshold = False
    empty_limit_exceeded = False
    while time.time() < poll_deadline:
        sayac_text = read_sayac_text(sayac_coords, config.get("ocr", {}), debug_capture)
        total_seconds = parse_sayac_seconds(sayac_text)
        if total_seconds is None:
            log(f"Kazi sayaci okunamadi: '{sayac_text}'")
            consecutive_empty_readings += 1
            if consecutive_empty_readings >= empty_readings_limit:
                empty_limit_exceeded = True
                break
        else:
            consecutive_empty_readings = 0
            log(f"Kazi sayaci okundu: '{sayac_text}' -> {total_seconds} sn")
            if total_seconds <= threshold_seconds:
                consecutive_low_readings += 1
                log(
                    f"Esik altinda dogrulama {consecutive_low_readings}/"
                    f"{required_confirmations}."
                )
                if consecutive_low_readings >= required_confirmations:
                    reached_threshold = True
                    break
            else:
                if consecutive_low_readings:
                    log("Esik ustunde okuma geldi; dogrulama sayaci sifirlandi.")
                consecutive_low_readings = 0
        time.sleep(poll_interval)

    if empty_limit_exceeded:
        log(
            f"Kazi sayaci ust uste {empty_readings_limit} kez bos okundu; "
            "guvenlik icin uzun tiklamaya baslaniyor."
        )
    elif not reached_threshold:
        log(
            f"Kazi sayaci {max_poll_seconds} sn icinde esige inmedi; "
            "guvenlik icin tiklamaya baslaniyor."
        )

    log(f"Sayac okumasi bitti; harita {zoom_ticks} tik eski haline uzaklastiriliyor.")
    scroll_zoom(window, -zoom_ticks)
    time.sleep(config.get("kazi_sayac_zoom_settle_seconds", 0.3))

    if empty_limit_exceeded:
        duration = config.get("kazi_sayac_empty_click_duration_seconds", 180)
    else:
        duration = config.get("kazi_sayac_click_duration_seconds", 40)
    click_interval = post_attack.get("click_interval_seconds", 0.1)
    coordinate = post_attack["click_coordinate"]
    return burst_click_until_paylas(config, coordinate, duration, click_interval)


def perform_pre_ocr_click(case):
    delay = case.get("pre_ocr_delay_seconds", 0.5)
    time.sleep(delay)
    coordinate = case.get("pre_ocr_click_coordinate", [1075, 243])
    pyautogui.click(coordinate[0], coordinate[1])
    log(
        f"OCR oncesi tiklama ({delay} saniye beklendi): "
        f"({coordinate[0]}, {coordinate[1]})"
    )


CASE_LABELS = {"excavation": "kazi", "clover": "yonca"}
FOUND_PHRASES = {
    "excavation": "Kazı buldum!",
    "clover": "Yonca buldum!",
    "tren": "Tren buldum!",
}


def log_found_target(case_name):
    """kazi.png/yonca.png/tren.png bulundugunda, ayri bir dosyaya
    (logs/bulunanlar.log) kisa ve okunakli bir satir ekler. Tarih gun-
    saat:dakika (dd-hh24:mi) formatinda tutuluyor. hastane/yardim_asker
    gibi cok sik tetiklenen case'ler bu dosyaya yazilmiyor - o dosya
    sadece nadir/degerli bulgular icin, sik tekrar eden bulgularla
    kirlenmemesi icin."""
    if case_name not in FOUND_PHRASES:
        return
    phrase = FOUND_PHRASES.get(case_name, f"{CASE_LABELS.get(case_name, case_name).capitalize()} buldum!")
    timestamp = datetime.now().strftime("%d-%H:%M")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with FOUND_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"{timestamp} {phrase}\n")


def run_scan_case(
    case_name,
    template_path,
    match,
    region,
    case,
    window,
    config,
    monitor_state,
    uyari_scan_enabled=None,
    escape_monitor_enabled=None,
    kazi_sayac_mode_enabled=None,
    debug_capture=False,
):
    pause_escape_monitor_temporarily(escape_monitor_enabled, config, case_name)
    rally_was_paused = pause_rally_mode_temporarily(uyari_scan_enabled, config, case_name)
    pause_hastane_mode_temporarily(config, case_name)

    # hastane/yardim_asker cok sik tetiklendigi ve calistigi dogrulandigi
    # icin bu ikisinin tespit/tiklama loglari kapatildi (application.log'u
    # kirletmesin diye); diger case'ler (kazi/yonca/tren) hala loglaniyor.
    quiet = case_name in ("hastane", "yardim_asker")

    try:
        center_x, center_y = match
        timestamp = datetime.now().strftime("%d.%m %H:%M")
        if not quiet:
            log(
                f"CASE {case_name}: {template_path.name} bulundu "
                f"(bolge ici=({center_x}, {center_y})) {timestamp}"
            )

        case_label = CASE_LABELS.get(case_name, case_name)
        found_timestamp = datetime.now().strftime("%d%m%Y_%H:%M")
        found_message = f"{case_label} -> bulundu_{found_timestamp}"
        if not quiet:
            log(found_message)
        log_found_target(case_name)
        action = case.get("action")
        if action == "tren_sequence":
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            log(
                f"{template_path.name} bulundu; ortasina tiklandi: "
                f"({screen_x}, {screen_y})"
            )
            perform_tren_sequence(case, escape_monitor_enabled)
        elif action == "click_then_escape":
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            time.sleep(case.get("escape_delay_seconds", 0.5))
            pyautogui.press("esc")
            log(
                f"{template_path.name} tiklandi, "
                f"{case.get('escape_delay_seconds', 0.5)} saniye sonra ESC basildi."
            )
        elif action == "click_coordinate":
            coordinate = case["click_coordinate"]
            if coordinate == [856, 746]:
                saldirma_click()
            else:
                pyautogui.click(coordinate[0], coordinate[1])
            log(
                f"{template_path.name} bulundu; "
                f"({coordinate[0]}, {coordinate[1]}) koordinatina tiklandi."
            )
        elif action == "click_only":
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            if not quiet:
                log(
                    f"{template_path.name} bulundu; tiklandi: "
                    f"({screen_x}, {screen_y})"
                )
        elif action == "click_then_click_coordinate":
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            if not quiet:
                log(
                    f"{template_path.name} bulundu; tiklandi: "
                    f"({screen_x}, {screen_y})"
                )
            delay = case.get("follow_up_delay_seconds", 1.0)
            time.sleep(delay)
            coordinate = case["follow_up_click_coordinate"]
            pyautogui.click(coordinate[0], coordinate[1])
            if not quiet:
                log(
                    f"{delay} saniye sonra ek tiklama: "
                    f"({coordinate[0]}, {coordinate[1]})"
                )
        elif action in {"click_then_text_scan", "click_then_text_match"}:
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            time.sleep(case.get("text_scan_delay_seconds", 0.5))
            perform_pre_ocr_click(case)
            found = scan_text_region(
                case["text_region"],
                case.get("ocr", {}),
                case.get("target_texts"),
            )
            if found and case.get("follow_up_action") == "excavation_attack":
                perform_excavation_attack(
                    window, case, config, monitor_state,
                    kazi_sayac_mode_enabled, debug_capture,
                )
        elif action == "click_then_text_match_escape":
            screen_x = region[0] + center_x
            screen_y = region[1] + center_y
            pyautogui.click(screen_x, screen_y)
            time.sleep(case.get("text_scan_delay_seconds", 1.0))
            found = scan_text_region(
                case["text_region"],
                case.get("ocr", {}),
                case.get("target_texts"),
            )
            if found:
                post_match_coordinate = case.get("post_match_click_coordinate")
                if post_match_coordinate:
                    time.sleep(case.get("post_match_click_delay_seconds", 1.0))
                    pyautogui.click(post_match_coordinate[0], post_match_coordinate[1])
                    log(
                        "OCR hedefinden sonra ek tiklama: "
                        f"({post_match_coordinate[0]}, {post_match_coordinate[1]})"
                    )

                escape_press_count = case.get("escape_press_count", 1)
                for _ in range(escape_press_count):
                    pyautogui.press("esc")
                    time.sleep(case.get("escape_between_presses_seconds", 0.1))
                log(
                    f"OCR hedefinden sonra ESC {escape_press_count} kere basildi."
                )
            else:
                pyautogui.press("esc")
                log("OCR hedefi bulunamadi; ESC basildi.")
    finally:
        if rally_was_paused and uyari_scan_enabled is not None:
            uyari_scan_enabled["enabled"] = True
            log(
                f"{CASE_LABELS.get(case_name, case_name)} isleminin son adiminda "
                "ralli modu (R) tekrar aktif edildi."
            )

def pause_toggle_temporarily(toggle_state, duration_seconds, label):
    if not toggle_state or not toggle_state.get("enabled"):
        return False

    toggle_state["enabled"] = False
    log(f"{label} {duration_seconds} saniyeligine pasife alindi.")

    def reactivate():
        toggle_state["enabled"] = True
        log(f"{label} tekrar aktif edildi.")

    timer = threading.Timer(duration_seconds, reactivate)
    timer.daemon = True
    timer.start()
    return True


def pause_rally_mode_temporarily(uyari_scan_enabled, config, case_name):
    if case_name in ("excavation", "clover"):
        duration = config.get("rally_pause_seconds", 120)
    elif case_name == "tren":
        duration = config.get("rally_pause_seconds_tren", 30)
    else:
        return False
    return pause_toggle_temporarily(uyari_scan_enabled, duration, "Ralli modu (R)")


def pause_hastane_mode_temporarily(config, case_name):
    """Kazi veya yonca bulundugunda, A modu (hastane + yardim_asker
    taramasi) o an acik ise 5 dakikaligina pasife alir, sure dolunca
    otomatik tekrar aktif eder. A modu zaten kapaliysa hicbir sey
    yapmaz. hastane/yardim_asker'in enabled bayraklarini dogrudan
    config uzerinde degistiriyor (A tusunun kendisi de ayni sekilde
    calisiyor), ayri bir toggle_state nesnesi gerektirmiyor."""
    if case_name not in ("excavation", "clover"):
        return

    hastane_case = config.get("scan_cases", {}).get("hastane")
    yardim_asker_case = config.get("scan_cases", {}).get("yardim_asker")
    if not (hastane_case and hastane_case.get("enabled")):
        return

    duration = config.get("hastane_pause_seconds", 300)
    if hastane_case is not None:
        hastane_case["enabled"] = False
    if yardim_asker_case is not None:
        yardim_asker_case["enabled"] = False
    log(f"A modu (Hastane/Yardim/Asker) {duration} saniyeligine pasife alindi.")

    def reactivate():
        if hastane_case is not None:
            hastane_case["enabled"] = True
        if yardim_asker_case is not None:
            yardim_asker_case["enabled"] = True
        log("A modu (Hastane/Yardim/Asker) tekrar aktif edildi.")

    timer = threading.Timer(duration, reactivate)
    timer.daemon = True
    timer.start()


def pause_escape_monitor_temporarily(escape_monitor_enabled, config, case_name):
    if case_name == "excavation":
        duration = config.get("escape_pause_seconds_kazi", 130)
    elif case_name == "clover":
        duration = config.get("escape_pause_seconds_yonca", 30)
    else:
        return
    pause_toggle_temporarily(escape_monitor_enabled, duration, "Periyodik tiklama dongusu (E)")


def perform_tren_sequence(case, escape_monitor_enabled):
    was_enabled = bool(escape_monitor_enabled and escape_monitor_enabled.get("enabled"))
    if escape_monitor_enabled is not None:
        escape_monitor_enabled["enabled"] = False
        log("Tren bulundu; 300 saniyelik periyodik tiklama dongusu durduruldu.")

    try:
        pre_confirm_delay = case.get("pre_confirm_delay_seconds", 0)
        if pre_confirm_delay:
            time.sleep(pre_confirm_delay)

        for index, step in enumerate(case.get("confirm_clicks", []), start=1):
            coordinate = step["coordinate"]
            pyautogui.click(coordinate[0], coordinate[1])
            log(f"Tren onay tiklamasi {index}: ({coordinate[0]}, {coordinate[1]})")
            time.sleep(step.get("wait_after_seconds", 1))

        escape_press_count = case.get("escape_press_count", 1)
        escape_between = case.get("escape_between_presses_seconds", 0.5)
        for _ in range(escape_press_count):
            pyautogui.press("esc")
            time.sleep(escape_between)
        log(f"Tren akisi sonunda ESC {escape_press_count} kere basildi.")
    finally:
        if escape_monitor_enabled is not None:
            escape_monitor_enabled["enabled"] = was_enabled
            log("300 saniyelik periyodik tiklama dongusu tekrar baslatildi.")


def perform_excavation_attack(
    window, case, config, monitor_state, kazi_sayac_mode_enabled=None, debug_capture=False
):
    monitor_state["paused"] = True
    interval = config.get("game_monitor", {}).get("escape_interval_seconds", 15)
    log(f"Kazi saldirisi basladi; {interval} saniyelik ESC izleme duraklatildi.")
    try:
        jump_wait = case.get("map_jump_wait_seconds", 1.0)
        log(f"Harita sicramasi icin {jump_wait} saniye bekleniyor.")
        time.sleep(jump_wait)

        center_x = window.left + window.width // 2
        center_y = window.top + window.height // 2
        pyautogui.click(center_x, center_y)
        log(f"Oyun merkezi tiklandi: ({center_x}, {center_y})")

        delay = case.get("follow_up_click_delay_seconds", 0.5)
        for coordinate in case["follow_up_coordinates"]:
            time.sleep(delay)
            pyautogui.click(coordinate[0], coordinate[1])
            log(f"Takip tiklamasi: ({coordinate[0]}, {coordinate[1]})")

        pre_saldir_delay = case.get("pre_saldir_delay_seconds", delay)
        time.sleep(pre_saldir_delay)
        saldir_click()
        # L acikken sayac-bazli bekleme, kapaliyken (varsayilan) eskisi gibi
        # sabit sureli bekleme kullanilir - normal kazi akisi degismiyor.
        if kazi_sayac_mode_enabled is not None and kazi_sayac_mode_enabled.get("enabled"):
            wait_for_sayac_then_burst_click(config, window, debug_capture)
        else:
            wait_then_burst_click(config)
    finally:
        monitor_state["paused"] = False
        log(f"Kazi saldirisi tamamlandi; {interval} saniyelik ESC izleme yeniden etkin.")

def normalize_ocr_text(value):
    # Buyuk I ve İ harflerini standart kucuk i ve ı'ya cevir
    val = value.replace("İ", "i").replace("I", "ı").lower()
    # Tum ı harflerini i yap ki string kontrolleri garantiye alinsin
    val = val.replace("ı", "i")
    return re.sub(r"[^0-9a-zçgöşü]+", " ", val).strip()

def scan_text_region(text_region, ocr_config, target_texts=None):
    left, top = text_region["top_left"]
    right, bottom = text_region["bottom_right"]
    width = abs(right - left)
    height = abs(bottom - top)
    if width == 0 or height == 0:
        raise ValueError("Metin tarama bolgesi sifir genislik veya yukseklikte.")

    screenshot = pyautogui.screenshot(
        region=(min(left, right), min(top, bottom), width, height)
    )
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    scale = ocr_config.get("scale", 3)
    enlarged = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )
    processed = cv2.threshold(
        enlarged,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )[1]
    # Eskiden text_to_string ve image_to_data ayri ayri (iki kez) OCR
    # calistiriyordu. Bu, ekran goruntusu alinip gercek tiklama arasindaki
    # sureyi ikiye katliyordu; oyun ekraninda bu arada (orn. ittifak
    # sohbetine biri mesaj yazinca) satirlar kayarsa, tiklama artik eski
    # (kaymadan onceki) konuma gidiyordu. Tek OCR gecisiyle bu pencereyi
    # kisaltiyoruz; log metnini de ayni sonuctan turetiyoruz.
    try:
        data = pytesseract.image_to_data(
            processed,
            lang=ocr_config.get("language", "tur+eng"),
            config=f"--psm {ocr_config.get('page_segmentation_mode', 6)}",
            output_type=pytesseract.Output.DICT,
        )
    except TesseractNotFoundError:
        message = (
            "Tesseract OCR bulunamadi. "
            "config.json icindeki tesseract_cmd yolunu kontrol edin."
        )
        log(message)
        return False

    text = " ".join(word for word in data["text"] if word.strip())
    if text:
        log("Metin taramasi:")
        log(text)
    else:
        log("Metin taramasi: metin bulunamadi.")

    if not target_texts:
        return False

    lines = {}
    for index, raw_word in enumerate(data["text"]):
        word = normalize_ocr_text(raw_word)
        if not word:
            continue
        line_key = (
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )
        lines.setdefault(line_key, []).append(
            {
                "word": word,
                "left": data["left"][index],
                "top": data["top"][index],
                "width": data["width"][index],
                "height": data["height"][index],
            }
        )

    for target in target_texts:
        target_words = normalize_ocr_text(target).split()
        for words in lines.values():
            for start in range(len(words) - len(target_words) + 1):
                candidate = words[start:start + len(target_words)]
                candidate_text = " ".join(item["word"] for item in candidate)
                target_text = " ".join(target_words)
                similarity = difflib.SequenceMatcher(
                    None,
                    candidate_text,
                    target_text,
                ).ratio()
                threshold = ocr_config.get("target_match_threshold", 0.75)
                if (
                    candidate_text != target_text
                    and similarity < threshold
                ):
                    continue

                left_edge = min(item["left"] for item in candidate)
                top_edge = min(item["top"] for item in candidate)
                right_edge = max(
                    item["left"] + item["width"] for item in candidate
                )
                bottom_edge = max(
                    item["top"] + item["height"] for item in candidate
                )
                click_x = min(left, right) + (left_edge + right_edge) // (2 * scale)
                click_y = min(top, bottom) + (top_edge + bottom_edge) // (2 * scale)
                pyautogui.click(click_x, click_y)
                log(f"{target} hedef bulundu ve merkezine tiklandi: ({click_x}, {click_y})")
                return True

    return False

def get_best_template_match(screenshot, template_path, template_scales=None):
    """get_best_template_score gibi ama en iyi eslesmenin konum ve
    boyutunu da dondurur: (skor, sol, ust, genislik, yukseklik); hicbir
    olcek sigmazsa None."""
    screenshot_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    original_template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    if original_template is None:
        raise RuntimeError(f"PNG okunamadi: {template_path}")

    screenshot_height, screenshot_width = screenshot_gray.shape[:2]
    scales = template_scales or [1.0]
    best = None
    for scale in scales:
        template = cv2.resize(
            original_template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
        )
        template_height, template_width = template.shape[:2]
        if template_width > screenshot_width or template_height > screenshot_height:
            continue
        result = cv2.matchTemplate(screenshot_gray, template, cv2.TM_CCOEFF_NORMED)
        _, maximum_value, _, maximum_location = cv2.minMaxLoc(result)
        if best is None or maximum_value > best[0]:
            best = (maximum_value, maximum_location[0], maximum_location[1], template_width, template_height)
    return best


def average_center_color(image, fraction=0.5):
    """PIL Image, gri veya renkli bir ndarray'in TAM ORTASINDAKI (fraction
    kadar) bolgesinin ortalama renk vektorunu dondurur. Tum goruntunun
    ortalamasini almak, rozetin kenarlarindaki arka plan/gecis piksellerini
    de karistirip asil ayirt edici rengi (hastane.png'nin mavisi ile
    hastaneFake.png'nin yesili arasindaki fark) zayiflatiyordu - olcum:
    tam goruntu ortalamasinda fark ~29 birimken, merkezin yarisinda ~144
    birime cikiyor. fraction, oransal oldugu icin ekran kirpintisi ile
    sablonun kendi boyutu farkli olsa da (olcekleme sonucu) ayni sekilde
    calisir."""
    array = np.array(image, dtype=np.float64)
    if array.ndim == 3 and array.shape[2] == 4:
        array = array[:, :, :3]
    height, width = array.shape[:2]
    margin_h = int(height * (1 - fraction) / 2)
    margin_w = int(width * (1 - fraction) / 2)
    cropped = array[margin_h:height - margin_h, margin_w:width - margin_w]
    if cropped.ndim == 2:
        return np.array([cropped.mean()] * 3)
    return cropped.reshape(-1, cropped.shape[-1]).mean(axis=0)




def is_excluded_by_fake_template(screenshot, case, template_name, confidence):
    """case["exclude_templates_for"] icinde template_name'e karsilik gelen
    'sahte' sablonlar tanimlanmissa (orn. hastane.png ile gorsel olarak
    cok benzeyen hastaneFake.png). hastane.png (mavi daire) ve
    hastaneFake.png (yesil kare) griye cevrildiginde OCR/sablon
    eslestirme icin kullanilan gri-tonlama skorlari birbirine cok
    yakin cikiyor (ikisi de "acik renk hac isareti + koyu arka plan"
    seklinde), bu yuzden skor karsilastirmasi bile hastane.png'yi
    yanlislikla kazandirabiliyordu. Renk bilgisi (mavi vs yesil) ise
    ikisini kesin ayirt ediyor: gercek eslesmenin bulundugu bolgenin
    RENKLI ortalamasini (rozetin merkezine odaklanarak, kenar/arka plan
    piksellerini disarida tutarak), hem asil hem sahte sablonun kendi
    renkli ortalamasiyla karsilastirip HANGISINE renk olarak daha
    yakinsa onu gercek kabul ediyoruz."""
    exclude_map = case.get("exclude_templates_for", {})
    exclude_templates = exclude_map.get(template_name)
    if not exclude_templates:
        return False

    template_scales = case.get("template_scales")
    real_match = get_best_template_match(screenshot, PNG_DIR / template_name, template_scales)
    if real_match is None:
        return False

    _, left, top, width, height = real_match
    screen_crop = np.array(screenshot)[top:top + height, left:left + width]
    screen_color = average_center_color(screen_crop)

    real_template_color = average_center_color(
        cv2.cvtColor(cv2.imread(str(PNG_DIR / template_name), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    )
    real_distance = np.linalg.norm(screen_color - real_template_color)

    for fake_template_name in exclude_templates:
        fake_template_path = PNG_DIR / fake_template_name
        if not fake_template_path.exists():
            APP_LOGGER.warning("Tarama PNG bulunamadi: %s", fake_template_path)
            continue
        fake_template_color = average_center_color(
            cv2.cvtColor(cv2.imread(str(fake_template_path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        )
        fake_distance = np.linalg.norm(screen_color - fake_template_color)
        if fake_distance < real_distance:
            return True
    return False


def scan_cases(
    window,
    config,
    monitor_state,
    uyari_scan_enabled=None,
    escape_monitor_enabled=None,
    kazi_sayac_mode_enabled=None,
    debug_capture=False,
):
    default_region = get_scan_region(config)
    cases = config["scan_cases"]

    for case_name, case in cases.items():
        if not case.get("enabled", True):
            continue

        region = (
            get_region_tuple(case["scan_region"])
            if "scan_region" in case
            else default_region
        )
        screenshot = pyautogui.screenshot(region=region)
        confidence = case.get(
            "image_confidence",
            config["bot"]["image_confidence"],
        )
        for template_name in case["templates"]:
            template_path = PNG_DIR / template_name
            if not template_path.exists():
                APP_LOGGER.warning("Tarama PNG bulunamadi: %s", template_path)
                continue

            center = find_template_center(
                screenshot,
                template_path,
                confidence,
                case.get("template_scales"),
            )
            if center and is_excluded_by_fake_template(
                screenshot, case, template_name, confidence
            ):
                continue
            if center:
                run_scan_case(
                    case_name,
                    template_path,
                    center,
                    region,
                    case,
                    window,
                    config,
                    monitor_state,
                    uyari_scan_enabled,
                    escape_monitor_enabled,
                    kazi_sayac_mode_enabled,
                    debug_capture,
                )

def is_screenshot_blank(image, std_threshold=5.0):
    """Ekran goruntusunun neredeyse tek renk (orn. monitor kapaliyken
    Windows'un dondurdugu siyah kare) olup olmadigini kontrol eder.
    Piksel degerlerinin standart sapmasi cok dusukse (gercek oyun
    ekranindaki cesitlilik yoksa) True doner."""
    array = np.array(image, dtype=np.float64)
    return array.std() < std_threshold


def click_matching_templates(
    window,
    config,
    debug_capture=False,
    monitor_state=None,
    uyari_scan_enabled=None,
    escape_monitor_enabled=None,
    kazi_sayac_mode_enabled=None,
):
    if monitor_state is None:
        monitor_state = {"paused": False}
    confidence = config["bot"]["image_confidence"]
    bring_game_to_front(window)
    screenshot = pyautogui.screenshot(
        region=(window.left, window.top, window.width, window.height)
    )

    if is_screenshot_blank(screenshot):
        if not monitor_state.get("blank_screen_warned"):
            log(
                "[UYARI] Ekran goruntusu neredeyse tek renk (siyah/donmus) - "
                "monitor kapali olabilir; taramalar sonuc vermeyebilir."
            )
            monitor_state["blank_screen_warned"] = True
    elif monitor_state.get("blank_screen_warned"):
        log("Ekran goruntusu tekrar normal gorunuyor.")
        monitor_state["blank_screen_warned"] = False

    if debug_capture:
        capture_debug_screenshot(window, config)
    scan_cases(
        window, config, monitor_state, uyari_scan_enabled, escape_monitor_enabled,
        kazi_sayac_mode_enabled, debug_capture,
    )

    for activity_name, activity in config["activities"].items():
        if not activity["enabled"]:
            continue

        for template_path in get_activity_templates(activity):
            center = find_template_center(screenshot, template_path, confidence)
            if center:
                center_x, center_y = center
                pyautogui.click(window.left + center_x, window.top + center_y)
                log(
                    f"{activity_name} bulundu ve tiklandi: "
                    f"{template_path.name}"
                )

def log_shortcuts(config):
    escape_interval = config.get("game_monitor", {}).get("escape_interval_seconds", 15)

    lines = ["Kisayollar:"]
    for activity in config["activities"].values():
        lines.append(f"  {activity['shortcut'].upper()} -> {activity['description']}")

    lines.append(f"  {config['controls']['stop_shortcut'].upper()} -> botu durdur")
    lines.append(
        f"  {config['controls']['coordinate_shortcut'].upper()} -> "
        "sonraki mouse tiklamasinin pikselini logla"
    )
    lines.append(
        f"  {config['controls']['text_scan_shortcut'].upper()} -> "
        "metin bolgesini tara ve logla"
    )
    lines.append(
        f"  {config['controls']['debug_screenshot_shortcut'].upper()} -> "
        "kirmizi alanli tarama ekran goruntusunu ac/kapat"
    )
    lines.append(
        f"  {config['controls']['escape_monitor_shortcut'].upper()} -> "
        f"{escape_interval} saniyelik periyodik tiklama dongusunu ac/kapat"
    )
    lines.append("  R -> Uyari ve Arti taramasini ac/kapat")
    lines.append("  P -> Tren taramasini ac/kapat")
    lines.append("  A -> Hastane/Yardim/Asker taramasini ac/kapat (varsayilan kapali)")
    lines.append(
        "  Q -> Sayac zoom/OCR testini baslat (gercek kazi saldirisi olmadan; "
        "esik 20sn, 5 dogrulama, sonra ekran ortasina tiklar)"
    )
    lines.append("  U -> Sv.NN/Zombi Patronu OCR gri alan taramasini kaydet (paylas.png arama bolgesinin de ekran goruntusunu alir)")
    lines.append(
        "  L -> Kazi sayac modunu ac/kapat (acikken kazi sonundaki 60sn "
        "bekle+240sn tikla yerine, sayac 30sn altina ust uste 5 kez "
        "dogrulandiginda 40sn boyunca saniyede 10 tiklama yapilir; "
        "L kapaliyken kazi normal sureciyle calisir)"
    )

    for line in lines:
        log(line)
    # Not: kutuphane/kisayollar.log artik her bot baslangicinda otomatik
    # guncellenmiyor (surekli tekrarlanan bloklar birikiyordu). O dosya
    # sadece koda yeni bir kisayol eklendiginde elle guncellenen statik
    # bir referans.

def start_click_coordinate_capture(window, timeout_seconds=15):
    """J kisayolu icin: global mouse hook'una guvenmeden (oyun raw-input
    yakaladiginda hook tiklamayi hic gormeyebiliyor), sol tik durumunu
    dogrudan GetAsyncKeyState ile yoklayarak bir sonraki tiklamayi loglar."""
    VK_LBUTTON = 0x01

    def poll():
        user32 = ctypes.windll.user32
        was_pressed = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            is_pressed = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if is_pressed and not was_pressed:
                x, y = pyautogui.position()
                try:
                    relative_x = x - window.left
                    relative_y = y - window.top
                    log(
                        f"Mouse tiklamasi: ekran=({x}, {y}), "
                        f"oyun penceresi ici=({relative_x}, {relative_y})"
                    )
                except Exception:
                    log(
                        f"Mouse tiklamasi: ekran=({x}, {y}) "
                        "(oyun penceresi ici konum hesaplanamadi; "
                        "pencere bu sirada yeniden baslamis olabilir)."
                    )
                return
            was_pressed = is_pressed
            time.sleep(0.02)
        log(f"J: {timeout_seconds} saniye icinde tiklama algilanmadi.")

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()


def create_input_listeners(window, config, running_state, monitor_state):
    shortcut_map = {
        activity["shortcut"].lower(): activity_name
        for activity_name, activity in config["activities"].items()
    }
    controls = config["controls"]
    text_scan_requested = {"enabled": False}
    ocr_debug_requested = {"enabled": False}
    kazi_sayac_mode_enabled = {"enabled": False}
    debug_capture = {"enabled": False}
    escape_monitor_enabled = {
        "enabled": config.get("game_monitor", {}).get("escape_enabled", False)
    }
    uyari_scan_enabled = {"enabled": False}
    escape_interval = config.get("game_monitor", {}).get("escape_interval_seconds", 15)

    def on_press(key):
        try:
            pressed_key = key.char.lower()
        except AttributeError:
            return

        if pressed_key == controls["stop_shortcut"].lower():
            log(f"{pressed_key.upper()} -> bot durduruluyor...")
            running_state["running"] = False
            return False

        if pressed_key == "r":
            uyari_scan_enabled["enabled"] = not uyari_scan_enabled["enabled"]
            state = "acik" if uyari_scan_enabled["enabled"] else "kapali"
            log(f"R -> Uyari/Arti taramasi: {state}")
            return

        if pressed_key == "p":
            tren_case = config.get("scan_cases", {}).get("tren")
            if tren_case is not None:
                tren_case["enabled"] = not tren_case.get("enabled", False)
                state = "acik" if tren_case["enabled"] else "kapali"
                log(f"P -> Tren taramasi: {state}")
            return

        if pressed_key == "a":
            hastane_case = config.get("scan_cases", {}).get("hastane")
            yardim_asker_case = config.get("scan_cases", {}).get("yardim_asker")
            current = hastane_case.get("enabled", False) if hastane_case else False
            new_state = not current
            if hastane_case is not None:
                hastane_case["enabled"] = new_state
            if yardim_asker_case is not None:
                yardim_asker_case["enabled"] = new_state
            state = "acik" if new_state else "kapali"
            log(f"A -> Hastane/Yardim/Asker taramasi: {state}")
            return

        if pressed_key == "q":
            log("Q -> Sayac zoom/OCR testi baslatildi.")
            threading.Thread(
                target=run_sayac_zoom_ocr_test,
                args=(window, config),
                daemon=True,
            ).start()
            return

        if pressed_key == controls["coordinate_shortcut"].lower():
            log("J -> sonraki mouse tiklamasi bekleniyor.")
            start_click_coordinate_capture(window)
            return

        if pressed_key == controls["text_scan_shortcut"].lower():
            text_scan_requested["enabled"] = True
            log("O -> metin taramasi istendi.")
            return

        if pressed_key == "u":
            ocr_debug_requested["enabled"] = True
            log("U -> OCR gri alan taramasi istendi.")
            return

        if pressed_key == "l":
            kazi_sayac_mode_enabled["enabled"] = not kazi_sayac_mode_enabled["enabled"]
            state = "acik" if kazi_sayac_mode_enabled["enabled"] else "kapali"
            log(
                f"L -> Kazi sayac modu: {state} (acikken kazi normal surecinin "
                "sonundaki 60sn bekle+240sn tikla yerine, sayac 30sn altina "
                "ust uste 5 kez dogrulandiginda 40sn boyunca saniyede 10 "
                "tiklama yapilir; L kapaliyken kazi normal sureciyle calisir)."
            )
            return

        if pressed_key == controls["debug_screenshot_shortcut"].lower():
            debug_capture["enabled"] = not debug_capture["enabled"]
            state = "acik" if debug_capture["enabled"] else "kapali"
            log(f"T -> tarama ekran goruntusu: {state}")
            return

        if pressed_key == controls["escape_monitor_shortcut"].lower():
            escape_monitor_enabled["enabled"] = not escape_monitor_enabled["enabled"]
            state = "acik" if escape_monitor_enabled["enabled"] else "kapali"
            log(
                f"{pressed_key.upper()} -> {escape_interval} saniyelik periyodik tiklama dongusu: {state}"
            )
            return

        activity_name = shortcut_map.get(pressed_key)
        if activity_name is None:
            return

        activity = config["activities"][activity_name]
        activity["enabled"] = not activity["enabled"]
        state = "acik" if activity["enabled"] else "kapali"
        log(f"{pressed_key.upper()} -> {activity_name}: {state}")

    def on_release(key):
        return True

    keyboard_listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
    )
    keyboard_listener.start()
    return (
        keyboard_listener,
        text_scan_requested,
        ocr_debug_requested,
        kazi_sayac_mode_enabled,
        debug_capture,
        escape_monitor_enabled,
        uyari_scan_enabled,
    )


def check_ralli_screen_timeout(config, uyari_state):
    """Ralli ekraninin ne zamandir surekli acik oldugunu, cagrilar arasi
    kalici sekilde (uyari_state) izler. Handle_uyari_scan'in kendi
    akisindan bagimsiz olarak HER turda calisir; boylece ekran farkli bir
    sebeple (tikanma, saldiri/ESC'nin isini gormemesi) takilirsa bile
    5 saniye sonra zorla kapatilir."""
    ralli_region = (602, 38, 818 - 602, 96 - 38)
    ralli_confidence = config.get("ralli_confidence", 0.7)
    ralli_scales = [0.9, 0.95, 1.0, 1.05]
    ralli_timeout = config.get("ralli_timeout_seconds", 5)

    screenshot_ralli = pyautogui.screenshot(region=ralli_region)
    ralli_present = find_template_center(
        screenshot_ralli,
        PNG_DIR / "ralli2.png",
        ralli_confidence,
        ralli_scales,
    ) is not None

    if not ralli_present:
        uyari_state["ralli_found_at"] = None
        return

    if uyari_state.get("ralli_found_at") is None:
        uyari_state["ralli_found_at"] = time.time()
        return

    if time.time() - uyari_state["ralli_found_at"] > ralli_timeout:
        pyautogui.press("esc")
        log(
            f"[GUVENLIK] Ralli ekrani {ralli_timeout} saniyeden "
            "uzun suredir acik; ESC basildi."
        )
        uyari_state["ralli_found_at"] = None


def handle_uyari_scan(window, config, debug_capture=False, uyari_state=None):
    if uyari_state is None:
        uyari_state = {}

    check_ralli_screen_timeout(config, uyari_state)

    uyari_coords = {"top_left": [1616, 578], "bottom_right": [1698, 649]}
    ralli_coords = {"top_left": [602, 38], "bottom_right": [818, 96]}

    # Ralli ekraninda birden fazla hedef satiri gorunebiliyor (bkz. ekran
    # goruntusu: "Kiyamet Eliti" + "Zombi Patronu" aynı ekranda). 1. satir
    # kosullari (isim/seviye/arti) saglamazsa 2. satira geciyoruz; her
    # satirin kendi olcumlenmis koordinatlari var (satir yukseklikleri
    # birbirinden farkli oldugu icin sabit bir offset yerine gercek
    # degerler kullaniliyor).
    uyari_rows = config.get("uyari_rows", [
        {
            "ocr_coords": {"top_left": [935, 320], "bottom_right": [1101, 360]},
            "arti_coords": {"top_left": [831, 272], "bottom_right": [899, 341]},
        },
        {
            "ocr_coords": {"top_left": [929, 555], "bottom_right": [1101, 594]},
            "arti_coords": {"top_left": [836, 514], "bottom_right": [892, 566]},
        },
    ])

    if debug_capture:
        capture_debug_screenshot(window, config, [("uyari_alani", uyari_coords)])

    uyari_region = (1616, 578, 1698 - 1616, 649 - 578)
    screenshot_uyari = pyautogui.screenshot(region=uyari_region)

    has_target = is_uyari_present(screenshot_uyari)
    if not has_target:
        uyari_match = find_template_center(
            screenshot_uyari,
            PNG_DIR / "uyari.png",
            confidence=0.65,
            template_scales=[0.8, 0.9, 1.0, 1.1],
        )
        has_target = uyari_match is not None

    if has_target:
        number_present = is_uyari_number_present(screenshot_uyari)
        if not number_present:
            has_target = False

    if has_target:
        # 1. Uyari butonuna tikla
        click_target_x = uyari_region[0] + (uyari_region[2] // 2)
        click_target_y = uyari_region[1] + (uyari_region[3] // 2)
        pyautogui.click(click_target_x, click_target_y)
        log(f"\n[UYARI BULUNDU] Tiklandi -> ({click_target_x}, {click_target_y})")

        # 2. Ekranin acilmasi icin bekle
        time.sleep(1.0)

        # 3. ralli.png ile ekranin gercekten acildigini dogrula (acilana kadar
        # birkac kere dene; boylece sabit bir bekleme suresi tahmin etmek
        # yerine ekran hazir olana kadar OCR'a gecilmez)
        if debug_capture:
            capture_debug_screenshot(window, config, [("ralli_alani", ralli_coords)])

        ralli_region = (602, 38, 818 - 602, 96 - 38)
        ralli_confidence = config.get("ralli_confidence", 0.7)
        ralli_scales = [0.9, 0.95, 1.0, 1.05]
        ralli_found = False
        for _ in range(6):
            screenshot_ralli = pyautogui.screenshot(region=ralli_region)
            ralli_match = find_template_center(
                screenshot_ralli,
                PNG_DIR / "ralli2.png",
                ralli_confidence,
                ralli_scales,
            )
            if ralli_match:
                ralli_found = True
                break
            time.sleep(0.5)

        if not ralli_found:
            pyautogui.press("esc")
            log("[RALLI BULUNAMADI] Ekran acilmadi, ESC basildi.")
            return

        log("[RALLI BULUNDU] Ekran acildi.")

        # 4. OCR + Arti kontrolunu satir satir dene; bir satir kosullari
        # saglamazsa (isim/seviye tutmuyor veya arti.png bulunamiyor)
        # sonraki satira gec.
        max_zombi_patronu_level = config.get("max_zombi_patronu_level", 56)
        arti_confidence = config.get("arti_confidence", 0.7)
        target_found = False

        for row_index, row in enumerate(uyari_rows, start=1):
            row_ocr_coords = row["ocr_coords"]
            row_arti_coords = row["arti_coords"]

            if debug_capture:
                capture_debug_screenshot(
                    window, config, [(f"ocr_metin_alani_satir{row_index}", row_ocr_coords)]
                )

            raw_ocr_text, level_text = get_text_from_region(
                row_ocr_coords, config.get("ocr", {}), debug_capture, f"satir{row_index}"
            )
            log(f"--- [SATIR {row_index}] OCR METNI OKUNDU:\n{raw_ocr_text}\n-----------------------")
            log(f"--- [SATIR {row_index}] OCR SEVIYE SATIRI OKUNDU: '{level_text}'")

            if not check_elite_level(raw_ocr_text, level_text, max_zombi_patronu_level):
                log(f"[SATIR {row_index}] Kosul saglanmadi, sonraki satira geciliyor.")
                continue

            if debug_capture:
                capture_debug_screenshot(
                    window, config, [(f"arti_alani_satir{row_index}", row_arti_coords)]
                )

            arti_region = get_region_tuple(row_arti_coords)
            screenshot_arti = pyautogui.screenshot(region=arti_region)

            arti_match = find_template_center(
                screenshot_arti,
                PNG_DIR / "arti.png",
                arti_confidence,
                template_scales=[0.9, 0.95, 1.0, 1.05, 1.1],
                debug_label=f"arti.png (satir {row_index})",
            )

            if not arti_match:
                log(f"[SATIR {row_index}] Arti bulunamadi, sonraki satira geciliyor.")
                continue

            center_x = arti_region[0] + arti_match[0]
            center_y = arti_region[1] + arti_match[1]
            pyautogui.click(center_x, center_y)
            log(f"[SATIR {row_index}] ARTI BULUNDU] Merkeze tiklandi -> ({center_x}, {center_y})")

            arti_click_delay = config.get("arti_click_delay_seconds", 1.0)
            time.sleep(arti_click_delay)
            saldir_click()
            log(f"⚔️ [SATIR {row_index}] SALDIRI tetiklendi.")
            time.sleep(0.5)
            pyautogui.press("esc")
            log(f"[SATIR {row_index}] Saldiridan 0.5sn sonra ESC basildi.")
            target_found = True
            break

        if not target_found:
            pyautogui.press("esc")
            log("[KOSUL SAGLANMADI] Hicbir satir uygun degil, ESC basildi.")

def check_elite_level(ocr_text, level_text="", max_level=61):
    """
    Metin icinde Zombi Patronu ve seviyenin max_level altinda oldugunu kontrol eder.
    Gelen ornek: 'Sv.45\nZombi Patronu' (OCR bazen 'ZombilPatronu' olarak okuyor).
    """
    if not ocr_text:
        log("[OCR RED] Metin bos okundu.")
        return False

    clean_text = normalize_ocr_text(ocr_text)
    log(f"[DEBUG OCR TEMIZ METIN]: '{clean_text}'")

    # 1. Zombi Patronu kontrolu: katı alt-dize eslesmesi ("zombi" VE "patronu"
    # ayri ayri metinde olmali) tek harflik OCR hatalarinda bile (orn.
    # "zombiRatrant", "zomiPatronu") tamamen basarisiz oluyordu - oysa bu
    # okumalar gercekte hep "Zombi Patronu" idi, gercek DIGER hedef isimlerine
    # (orn. "Kiyamet Eliti") olan benzerligi ise cok dusuk (~0.15-0.25) kaliyor.
    # Bu yuzden katı substring yerine butun ada (bosluksuz) bulanik benzerlik
    # kullaniyoruz; gercek yanlis okumalar hep >=0.75 benzerlik verirken,
    # gercekten farkli bir hedef adi ~0.25'i gecmiyor - 0.65 esigi guvenli bir ara deger.
    target_name = "zombipatronu"
    compact_text = clean_text.replace(" ", "")
    similarity = difflib.SequenceMatcher(None, compact_text, target_name).ratio()
    if similarity < 0.65:
        log(f"[OCR RED] 'zombi patronu' metinde yok (bsenzerlik={similarity:.2f}): '{clean_text}'")
        return False

    # 2. Seviye kontrolu: OCR iyilestirmesiyle (satir bazli kirpma + gurultu
    # temizligi + rakam whitelist) seviye artik guvenilir okunabildigi icin
    # tekrar aktif; seviye okunamazsa guvenli tarafta kalinip hedef reddedilir.
    # "v" harfi (Sv. onekindeki) OCR'da hep dogru okunuyor; gercek seviye
    # rakamlari ondan hemen sonra geliyor. Kenar gurultusu genelde rakam
    # dizisinin SONUNA fazladan bir hane ekliyor (orn. "45" -> "451"), o
    # yuzden v'den sonraki dizinin son 2 hanesi degil ILK 2 hanesini aliyoruz.
    v_match = re.search(r"v\.?\s*(\d+)", level_text, re.IGNORECASE)
    if v_match:
        parsed_level = int(v_match.group(1)[:2])
    else:
        digit_runs = re.findall(r"\d+", level_text)
        if not digit_runs:
            log("[OCR RED] Seviye rakami okunamadi, hedef reddedildi.")
            return False
        parsed_level = int(digit_runs[-1][-2:])

    # OCR bu fontta bazen "0"i "9" gibi okuyor (sayac saat basamaginda da
    # ayni hata gorulmustu); seviyenin son hanesi 9 ise gercekte 0 oldugunu
    # varsayip duzeltiyoruz (orn. "69" -> 60, "59" -> 50).
    if parsed_level % 10 == 9:
        corrected_level = parsed_level - 9
        log(
            f"[OCR DUZELTME] Seviye {parsed_level} -> {corrected_level} "
            "(son hane 9, muhtemelen 0 yanlis okunmus)."
        )
        parsed_level = corrected_level

    log(f"[DEBUG OCR SEVIYE] Okunan seviye: {parsed_level}")

    if parsed_level <= 0:
        log("[OCR RED] Seviye 0 okundu (guvenilmez/tanimlanamadi), hedef reddedildi.")
        return False

    if parsed_level >= max_level:
        log(f"[OCR RED] Seviye {parsed_level} >= {max_level}, hedef uygun degil.")
        return False

    log(f"[OCR ONAY] 'zombi patronu' bulundu ve seviye {parsed_level} < {max_level}, hedef uygun.")
    return True

def find_text_bands(otsu_image, high=35, low=15, gap_needed=4):
    """Karakter grafigi/rozet kaynakli seyrek gurultunun ustunde, gercek metin
    satirlarinin yogun-siyah-piksel bantlarini bulur. Gurultu satirlari dusuk
    yogunlukta (~<low), gercek metin satirlari ise yuksek yogunlukta (~>high)
    siyah piksel iceriyor. Sirayla (satir1, satir2, ...) bant listesi dondurur."""
    dark = otsu_image < 127
    row_counts = dark.sum(axis=1)
    n = len(row_counts)
    bands = []
    i = 0
    while i < n:
        if row_counts[i] > high:
            start = i
            end = i
            below_run = 0
            j = i
            while j < n:
                if row_counts[j] < low:
                    below_run += 1
                    if below_run >= gap_needed:
                        end = j - below_run
                        break
                else:
                    below_run = 0
                    end = j
                j += 1
            bands.append((max(0, start - 3), min(n, end + 4)))
            i = end + gap_needed
        else:
            i += 1
    return bands

def extract_level_line(otsu_image):
    """"Sv.NN" satirini (ilk metin bandi) kirpar."""
    bands = find_text_bands(otsu_image)
    if not bands:
        return otsu_image[0:40, :]
    start, end = bands[0]
    return otsu_image[start:end, :]

def extract_name_line(otsu_image):
    """"Zombi Patronu" isim satirini ("Sv.NN"in altindaki ikinci metin
    bandini) kirpar."""
    bands = find_text_bands(otsu_image)
    if len(bands) < 2:
        return otsu_image[40:110, :]
    start, end = bands[1]
    return otsu_image[start:end, :]

def despeckle_relative(line_image, min_ratio=0.1):
    """Ana metin blobunun (harfler govde olarak birlesik) alanina gore kucuk
    kalan bagli bilesenleri (kenar gurultusu) siler; sabit bir piksel alani
    yerine oranli esik kullanarak farkli rakam sayisina (1 veya 2 haneli
    seviye) uyum saglar."""
    inv = 255 - line_image
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    if n <= 1:
        return line_image
    max_area = stats[1:, cv2.CC_STAT_AREA].max()
    despeckled_inv = inv.copy()
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < max_area * min_ratio:
            despeckled_inv[labels == i] = 0
    return 255 - despeckled_inv

def crop_to_ink(image, margin=4):
    """Goruntudeki siyah (esiklenmis) piksellerin gercek sinir kutusuna
    kirpar. Bos satirlarin/sutunlarin birakilmasi psm 7'nin (tek satir)
    metni bulamamasina yol aciyordu; sikica kirpmak bunu duzeltiyor."""
    dark = image < 127
    if not dark.any():
        return image
    rows = np.where(dark.any(axis=1))[0]
    cols = np.where(dark.any(axis=0))[0]
    top = max(0, rows.min() - margin)
    bottom = min(image.shape[0], rows.max() + 1 + margin)
    left = max(0, cols.min() - margin)
    right = min(image.shape[1], cols.max() + 1 + margin)
    return image[top:bottom, left:right]

def read_sayac_text(region, ocr_config=None, debug_capture=False):
    """Kazi/uyari sayacini (orn. "00:00:39" veya artik zoom'lu goruntude
    "51" gibi ciplak saniye rakami) OCR ile okur.

    Bu bolge, sayacin kendi siyah rozetinin yaninda genis bir renkli/
    desenli oyuncu/bina avatarini da iceriyor (zoom + genisletilmis
    bolge sonrasi dogrulandi - ekran goruntusunde "02:43" gibi gayet
    net bir rakam varken OCR tamamen bos donuyordu). Gri+Otsu esiklemesi
    (ve daha once denenen doygunluk-temizleme+Otsu) bu genis renkli
    alanin histogramindan etkilenip esigi yanlis noktaya kaydiriyor,
    kucuk beyaz rakamlari kaybediyordu. Bunun yerine dogrudan HEDEF
    RENK ozelligini (rakamlar parlak/beyaz VE dusuk doygunlukta,
    avatar ise koyu/orta parlaklikta VE yuksek doygunlukta) maskeleyip
    sadece bu pikselleri beyaz, geri kalan her seyi siyah yapiyoruz -
    Otsu'nun global histogramina bagli olmadigi icin avatarin ne kadar
    yer kapladigi onemli degil."""
    ocr_config = ocr_config or {}
    left, top = region["top_left"]
    right, bottom = region["bottom_right"]
    width = abs(right - left)
    height = abs(bottom - top)

    screenshot = pyautogui.screenshot(
        region=(min(left, right), min(top, bottom), width, height)
    )
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    if debug_capture:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
        raw_path = SCREENSHOTS_DIR / f"sayac_ham_{timestamp}.png"
        cv2.imwrite(str(raw_path), image)
        log(f"Sayac icin ham (islenmemis) renkli goruntu kaydedildi: {raw_path}")

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2].astype(np.int16)
    saturation = hsv[:, :, 1].astype(np.int16)
    text_mask = (value > 170) & (saturation < 70)
    binary = np.where(text_mask, 255, 0).astype(np.uint8)

    scale = ocr_config.get("sayac_scale", 6)
    enlarged = cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    processed = cv2.threshold(enlarged, 127, 255, cv2.THRESH_BINARY)[1]

    try:
        return pytesseract.image_to_string(
            processed,
            lang=ocr_config.get("language", "tur+eng"),
            config="--psm 6 -c tessedit_char_whitelist=0123456789:",
        ).strip()
    except Exception:
        return ""

def read_level_text(processed_image, language="tur+eng"):
    """Get_text_from_region'in urettigi olceklenmis+esiklenmis goruntuden
    sadece "Sv.NN" satirini ayiklayip, rakam/karakter whitelist'i ile ayri
    bir OCR gecisi yapar. Butun-blok OCR'i isim eslesmesi (zombi/patronu)
    icin yeterli olsa da, karakter grafiginin biraktigi kenar gurultusu
    seviyeyi bozdugu icin bu satira ozel, daha siki bir temizlik gerekiyor."""
    line = extract_level_line(processed_image)
    despeckled = despeckle_relative(line)
    tight = crop_to_ink(despeckled)
    padded = cv2.copyMakeBorder(tight, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        return pytesseract.image_to_string(
            padded,
            lang=language,
            config="--psm 6 -c tessedit_char_whitelist=Sv.0123456789",
        ).strip()
    except Exception:
        return ""

def read_name_text(processed_image, language="tur+eng"):
    """Get_text_from_region'in urettigi olceklenmis+esiklenmis goruntudeki
    "Zombi Patronu" isim satirini ayri bir OCR gecisiyle okur. Butun-blok
    OCR'i (varsayilan psm 6, tum bolge) bu isim icin cok gurultulu sonuc
    veriyordu ("are Ni i" gibi); satiri tek basina kirpip gurultuyu temiz-
    leyip, harf whitelist'i uygulayip, olceklendirmeyi geriye (0.75x) cekmek
    (asiri buyutulmus ic-bosluklu font, kucultulunce OCR icin daha normal
    gorunuyor) 'ZombiPatronu' seklinde dogru sonuc verdi."""
    line = extract_name_line(processed_image)
    despeckled = despeckle_relative(line, min_ratio=0.05)
    resized = cv2.resize(despeckled, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_CUBIC)
    _, resized = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
    padded = cv2.copyMakeBorder(resized, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
    try:
        return pytesseract.image_to_string(
            padded,
            lang=language,
            config="--psm 7 -c tessedit_char_whitelist=ZOMBIPATRONUzombipatronu",
        ).strip()
    except Exception:
        return ""

def get_text_from_region(text_region, ocr_config, debug_capture=False, debug_label=""):
    left, top = text_region["top_left"]
    right, bottom = text_region["bottom_right"]
    width = abs(right - left)
    height = abs(bottom - top)

    screenshot = pyautogui.screenshot(
        region=(min(left, right), min(top, bottom), width, height)
    )
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # Hedef karti üzerindeki renkli karakter/rozet grafikleri bazen taranan
    # metnin (özellikle "Sv.NN" satirinin) üzerine biniyor ve gri tonlama +
    # Otsu esiklemesi bu renkli gurultuyu metinle karistirip OCR'i bozuyor.
    # Metin/arka plan burada dusuk doygunlukta (beyaz/siyah/lavanta), grafik
    # ise yuksek doygunlukta; doygun pikselleri tahmini arka plan rengiyle
    # degistirerek bu gurultuyu OCR'dan once ayikliyoruz.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturated = hsv[:, :, 1] > 45
    if saturated.any() and not saturated.all():
        bg_color = np.median(image[~saturated].reshape(-1, 3), axis=0)
        image[saturated] = bg_color

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = ocr_config.get("scale", 3)
    enlarged = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    processed = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    if debug_capture:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        # Mikrosaniye dahil ediliyor; ayni saniye icinde birden fazla satir
        # (orn. satir1+satir2) taranirsa dosya adlari cakisip biri digerinin
        # uzerine yazmasin diye.
        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S_%f")
        suffix = f"_{debug_label}" if debug_label else ""
        path = SCREENSHOTS_DIR / f"ocr_gri_taranan{suffix}_{timestamp}.png"
        cv2.imwrite(str(path), processed)
        log(f"OCR'a gonderilen gri/esiklenmis goruntu kaydedildi: {path}")

    language = ocr_config.get("language", "tur+eng")
    level_text = read_level_text(processed, language)
    name_text = read_name_text(processed, language)

    return name_text, level_text

def is_uyari_present(screenshot):
    """Uyari bolgesinde kirmizi hedef butonunun belirdigini dogrular."""
    img_hsv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
    mask1 = cv2.inRange(img_hsv, np.array([0, 120, 100]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(img_hsv, np.array([170, 120, 100]), np.array([180, 255, 255]))
    red_mask = mask1 | mask2
    return cv2.countNonZero(red_mask) >= 250

def is_uyari_number_present(screenshot):
    """Uyari ikonunun sag-ust kosesindeki sayi rozetinde (1, 2, 3, ...) bir
    rakam olup olmadigini kontrol eder. Rozette rakam yoksa tiklama
    yapilmamasi icin has_target'i iptal etmek amaciyla kullanilir.

    Basit parlaklik/beyaz-piksel sayimi gercek oyun ekranlarinda yanilti
    oldu: rozet yokken de arka plandaki bina/gokyuzu pikselleri veya
    nisangahin ince kirmizi halka kenari bu bolgeye sizip esigi asabiliyordu.
    Rozetin kendine ozgu doygun kirmizi-pembe rengini arayip, bu rengin
    (halka kenari gibi ince bir cizgi degil) DOLU bir blok olusturup
    olusturmadigina (fill_ratio = alan / sinir-kutusu-alani) bakiyoruz;
    gercek rozet ~0.6-0.8 fill_ratio verirken, sizan ince kenar ~0.2 civarinda
    kaliyor."""
    img = np.array(screenshot)
    h, w = img.shape[:2]
    x0, x1 = int(w * 0.55), w
    y0, y1 = 0, int(h * 0.4)
    badge = img[y0:y1, x0:x1].astype(int)

    r, g, b = badge[:, :, 0], badge[:, :, 1], badge[:, :, 2]
    pin_mask = ((r > 200) & (g < 80) & (b < 100) & (b > 20)).astype(np.uint8) * 255

    n, _, stats, _ = cv2.connectedComponentsWithStats(pin_mask, connectivity=8)
    for i in range(1, n):
        bw, bh, area = stats[i, 2], stats[i, 3], stats[i, 4]
        if area < 60:
            continue
        if area / (bw * bh) >= 0.45:
            return True
    return False

def run_bot(config):
    log_shortcuts(config)
    existing_window = find_game_window(config)
    if existing_window is not None:
        log("Oyun penceresi zaten acik; baslangic tiklamalari atlandi.")
        game_started = False
        window = existing_window
    else:
        game_started = start_game(config)
        window = None

    timeout = config["game"]["window_wait_seconds"]
    deadline = time.time() + timeout

    if window is None:
        while time.time() < deadline:
            window = find_game_window(config)
            if window:
                break
            time.sleep(1)

    if window is None:
        raise RuntimeError("Oyun penceresi bulunamadi.")

    enforce_game_window_size(window, config)
    if game_started:
        perform_startup_clicks(config, window)
    else:
        log("Oyun zaten acikti; baslangic tiklamalari atlandi.")

    running_state = {"running": True}
    monitor_state = {"paused": False}
    uyari_state = {"ralli_found_at": None}
    escape_state = {"first_done": False}
    (
        keyboard_listener,
        text_scan_requested,
        ocr_debug_requested,
        kazi_sayac_mode_enabled,
        debug_capture,
        escape_monitor_enabled,
        uyari_scan_enabled,
    ) = create_input_listeners(window, config, running_state, monitor_state)

    log("Bot calisiyor. Durdurmak icin S basin.")
    next_escape_at = time.monotonic()
    window_check_interval = config["game"].get("window_check_interval_seconds", 300)
    next_window_check_at = time.monotonic() + window_check_interval
    try:
        while running_state["running"] and keyboard_listener.is_alive():
            try:
                if uyari_scan_enabled["enabled"]:
                    handle_uyari_scan(window, config, debug_capture["enabled"], uyari_state)

                    if not running_state["running"]:
                        break

                if time.monotonic() >= next_window_check_at:
                    next_window_check_at = time.monotonic() + window_check_interval
                    if find_game_window(config) is None:
                        log("Oyun penceresi bulunamadi; oyun yeniden baslatiliyor.")
                        window = restart_game_after_disconnect(config)
                        next_escape_at = time.monotonic()
                        continue

                monitor_action, next_escape_at = monitor_game_state(
                    config,
                    next_escape_at,
                    allow_escape=(
                        not monitor_state["paused"]
                        and escape_monitor_enabled["enabled"]
                    ),
                    escape_state=escape_state,
                )
                if not running_state["running"]:
                    break

                if monitor_action == "restart":
                    window = restart_game_after_disconnect(config)
                    next_escape_at = time.monotonic()
                    continue

                if ocr_debug_requested["enabled"]:
                    ocr_debug_requested["enabled"] = False
                    # Sv.NN/Zombi Patronu OCR'inin gordugu gri/esiklenmis
                    # goruntuyu, handle_uyari_scan disinda manuel test icin
                    # kaydeder. Koordinatlar handle_uyari_scan'in uyari_rows
                    # varsayilaniyla ayni (uzun suredir hardcoded literal
                    # kullanma konvansiyonuna uygun); artik her iki satiri
                    # da tarar.
                    ocr_debug_rows = [
                        {"top_left": [935, 320], "bottom_right": [1101, 360]},
                        {"top_left": [929, 555], "bottom_right": [1101, 594]},
                    ]
                    for row_index, row_coords in enumerate(ocr_debug_rows, start=1):
                        raw_ocr_text, level_text = get_text_from_region(
                            row_coords, config.get("ocr", {}), True, f"U_satir{row_index}"
                        )
                        log(f"--- [U: SATIR {row_index}] OCR METNI OKUNDU:\n{raw_ocr_text}\n-----------------------")
                        log(f"--- [U: SATIR {row_index}] OCR SEVIYE SATIRI OKUNDU: '{level_text}'")

                    capture_debug_screenshot(
                        window, config, [("paylas_arama", config["text_scan_region"])]
                    )

                if text_scan_requested["enabled"]:
                    text_scan_requested["enabled"] = False
                    if debug_capture["enabled"]:
                        capture_debug_screenshot(window, config)
                    perform_pre_ocr_click(config)
                    scan_text_region(
                        config["text_scan_region"],
                        config.get("ocr", {}),
                    )

                click_matching_templates(
                    window,
                    config,
                    debug_capture["enabled"],
                    monitor_state,
                    uyari_scan_enabled,
                    escape_monitor_enabled,
                    kazi_sayac_mode_enabled,
                )
            except pygetwindow.PyGetWindowException:
                # Oyun penceresi (X'e basma, crash, gorev yoneticisinden
                # sonlandirma vb. herhangi bir sekilde) kapandiginda pencere
                # isleci gecersiz kalip her window.left/top/width/height
                # erisiminde bu hatayi firlatiyordu ve botu tamamen
                # cokertiyordu; periyodik pencere kontrolu (300sn) bu
                # cokmeden ONCE calismiyordu. Simdi hatayi hemen yakalayip
                # yeniden baslatma prosedurunu tetikliyoruz.
                log("Oyun penceresi kapandi/gecersiz oldu; oyun yeniden baslatiliyor.")
                window = restart_game_after_disconnect(config)
                next_escape_at = time.monotonic()
                continue

            # Döngü aralığını daha duyarlı uyutma ile kontrol et
            sleep_duration = config["bot"]["scan_interval_seconds"]
            step = 0.1
            elapsed = 0.0
            while elapsed < sleep_duration and running_state["running"]:
                time.sleep(step)
                elapsed += step

    finally:
        keyboard_listener.stop()
        log("Bot basariyla sonlandirildi.")

if __name__ == "__main__":
    configure_logging()
    sys.excepthook = log_uncaught_exception
    STARTUP_LOGGER.info("Uygulama baslatildi.")
    try:
        startup_config = load_config()
        position_console_window(startup_config)
        run_bot(startup_config)
    except KeyboardInterrupt:
        APP_LOGGER.info("Bot kullanici tarafindan durduruldu.")
        log("\nBot durduruldu.")
    except Exception:
        APP_LOGGER.exception("Uygulama hatasi")
        STARTUP_LOGGER.exception("EXE baslangic/calisma hatasi")
        log("Hata olustu. logs/application.log ve logs/startup.log dosyalarini kontrol edin.")