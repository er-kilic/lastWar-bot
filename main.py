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

APP_LOGGER = logging.getLogger("last_war_bot")
STARTUP_LOGGER = logging.getLogger("last_war_bot_startup")


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
        print(f"Tasinabilir Tesseract kullaniliyor: {PORTABLE_TESSERACT_EXE}")
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
        print("Oyun zaten acik; tekrar baslatilmadi.")
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
    print("Oyun baslatildi.")
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
        APP_LOGGER.warning(
            "Ekran cozunurlugu (%sx%s) hedef pencere boyutundan (%sx%s) "
            "kucuk; oyun penceresi ekrana sigmayabilir.",
            screen_width,
            screen_height,
            width,
            height,
        )
        print(
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
    print(f"Oyun penceresi {width}x{height} boyutuna sol uste tasindi.")


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


def perform_startup_clicks(config):
    startup = config.get("startup_actions", {})
    if not startup.get("enabled", True):
        return

    initial_delay = startup.get("initial_delay_seconds", 1.0)
    time.sleep(initial_delay)

    delay = startup.get("click_delay_seconds", 0.5)
    for coordinate in startup.get("click_coordinates", []):
        pyautogui.click(coordinate[0], coordinate[1])
        print(f"Baslangic tiklamasi: ({coordinate[0]}, {coordinate[1]})")
        time.sleep(delay)

    if startup.get("press_escape_after_clicks", True):
        pyautogui.press("esc")
        print("Baslangic tiklamalarindan sonra ESC basildi.")


def has_red_disconnect_button(screenshot):
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
    height, width = image.shape[:2]
    lower_area = image[int(height * 0.5):, int(width * 0.15):int(width * 0.85)]
    lower_red = np.array([0, 100, 100])
    upper_red = np.array([10, 255, 255])
    red_mask = cv2.inRange(lower_area, lower_red, upper_red)
    return cv2.countNonZero(red_mask) >= 500


def has_blue_exit_button(screenshot):
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
    height, width = image.shape[:2]
    lower_area = image[int(height * 0.5):, int(width * 0.15):int(width * 0.85)]
    lower_blue = np.array([85, 80, 100])
    upper_blue = np.array([115, 255, 255])
    blue_mask = cv2.inRange(lower_area, lower_blue, upper_blue)
    return cv2.countNonZero(blue_mask) >= 500


def monitor_game_state(config, next_escape_at, allow_escape=True):
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
    disconnect_image = screenshot
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
        print(
            "disconnect.png bulundu; cikis tiklamasi yapildi: "
            f"({coordinate[0]}, {coordinate[1]})"
        )
        return "restart", next_escape_at

    if allow_escape and time.monotonic() >= next_escape_at:
        pyautogui.press("esc")
        interval = monitor.get("escape_interval_seconds", 15)
        print(f"Oyun kontrolu icin ESC basildi ({interval} saniye aralikla).")
        next_escape_at = time.monotonic() + interval

    exit_button = find_template_center(
        exit_image,
        PNG_DIR / monitor["exit_template"],
        confidence,
        monitor.get("exit_template_scales"),
    )
    if exit_button:
        pyautogui.press("esc")
        print("oyundanCikNew.png bulundu; ESC basildi.")
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
        print("paylas.png bulundu (surekli tarama); ESC basildi.")

    return None, next_escape_at


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
        print("Disconnect sonrasi oyun zaten acik; yeniden baslatma atlandi.")
        enforce_game_window_size(window, config)
        return window

    wait_seconds = config["game_monitor"].get("restart_delay_seconds", 60)
    print(f"Oyun yeniden baslatilmadan once {wait_seconds} saniye beklenecek.")
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
    perform_startup_clicks(config)
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
    print(
        f"Konsol penceresi ({x}, {y}) konumuna, {width}x{height} "
        "boyutuna tasindi."
    )


def bring_game_to_front(window):
    """Pencereyi Windows masaustunde gorunur ve odakta tutar."""
    window.restore()
    window.activate()

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

    if best_match is None or best_match[0] < confidence:
        return None

    _, maximum_location, template_width, template_height = best_match
    left, top = maximum_location
    return (
        left + template_width // 2,
        top + template_height // 2,
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


def save_scan_screenshot(screenshot, prefix):
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%d%m%Y_%H%M")
    path = SCREENSHOTS_DIR / f"{prefix}_{timestamp}.png"
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), image)
    APP_LOGGER.info("Tarama ekran goruntusu kaydedildi: %s", path)
    return path


def capture_debug_screenshot(window, config, custom_regions=None):
    """Pencere ekran goruntusunu alip belirtilen bolgeleri kirmizi cerceveyle kaydeder."""
    if custom_regions is not None:
        regions = custom_regions
    else:
        regions = [
            ("kazi_arama", config.get("scan_region")),
            ("mesaj_ekrani", config.get("text_scan_region")),
            ("cikis_arama", config.get("game_monitor", {}).get("region")),
        ]
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    for region_name, region in regions:
        if not region:
            continue
        image = np.array(
            pyautogui.screenshot(
                region=(window.left, window.top, window.width, window.height)
            )
        )
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        image_height, image_width = image.shape[:2]
        scale_x = image_width / window.width
        scale_y = image_height / window.height
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
        print(f"{region_name} icin kirmizi cerceveli ekran goruntusu: {path}")


def saldir_click():
    pyautogui.click(856, 746)
    print("Saldirma tiklamasi: (856, 746)")


def saldirma_click():
    saldir_click()


def _takim_saldir(takim_no, coordinate):
    pyautogui.click(coordinate[0], coordinate[1])
    print(f"{takim_no}. takim secildi: ({coordinate[0]}, {coordinate[1]})")
    time.sleep(0.3)
    saldir_click()

def birinci_takim_saldir():
    _takim_saldir(1, (705, 854))

def ikinci_takim_saldir():
    _takim_saldir(2, (804, 860))

def ucuncu_takim_saldir():
    _takim_saldir(3, (905, 867))

def parse_countdown_seconds(raw_text):
    """OCR'dan gelen 'sa:dk:sn' / 'dk:sn' / 'sn' formatlarini saniyeye cevirir."""
    cleaned = re.sub(r"[^0-9:]", "", raw_text)
    parts = [p for p in cleaned.split(":") if p != ""]
    if not parts or not all(p.isdigit() for p in parts):
        return None

    numbers = [int(p) for p in parts]
    if len(numbers) == 3:
        h, m, s = numbers
    elif len(numbers) == 2:
        h, m, s = 0, numbers[0], numbers[1]
    elif len(numbers) == 1:
        h, m, s = 0, 0, numbers[0]
    else:
        return None

    return h * 3600 + m * 60 + s


def wait_for_countdown_then_burst_click(config):
    """Kazi sayacini OCR ile okur; sayac esik degerin altina dusunce
    kisa sureli hizli tiklama baslatir."""
    countdown_config = config.get("countdown_watch", {})
    countdown_region = countdown_config.get(
        "region",
        {"top_left": [671, 276], "bottom_right": [994, 514]},
    )
    click_coordinate = config["post_attack"]["click_coordinate"]
    ocr_config = config.get("ocr", {})

    threshold_seconds = countdown_config.get("threshold_seconds", 10)
    burst_duration_seconds = countdown_config.get("burst_duration_seconds", 20)
    burst_clicks_per_second = countdown_config.get("burst_clicks_per_second", 10)
    poll_interval_seconds = countdown_config.get("poll_interval_seconds", 1.0)
    safety_timeout_seconds = countdown_config.get("safety_timeout_seconds", 120)

    deadline = time.time() + safety_timeout_seconds
    while time.time() < deadline:
        raw_text = get_text_from_region(countdown_region, ocr_config)
        remaining = parse_countdown_seconds(raw_text)

        if remaining is None:
            print(f"Sayac okunamadi, ham metin: '{raw_text}'")
            time.sleep(poll_interval_seconds)
            continue

        print(f"Kazi sayaci: {remaining} saniye kaldi.")

        if remaining <= threshold_seconds:
            print(
                f"Sayac {threshold_seconds} saniyenin altina dustu; "
                f"{burst_duration_seconds} saniye boyunca "
                f"saniyede {burst_clicks_per_second} tiklama basliyor."
            )
            click_interval = 1.0 / burst_clicks_per_second
            burst_deadline = time.time() + burst_duration_seconds
            while time.time() < burst_deadline:
                pyautogui.click(click_coordinate[0], click_coordinate[1])
                time.sleep(click_interval)
            print("Hizli tiklama tamamlandi.")
            return

        time.sleep(poll_interval_seconds)

    print("Sayac suresi icinde esik degere dusmedi.")


def perform_pre_ocr_click(case):
    delay = case.get("pre_ocr_delay_seconds", 0.5)
    time.sleep(delay)
    coordinate = case.get("pre_ocr_click_coordinate", [1075, 243])
    pyautogui.click(coordinate[0], coordinate[1])
    print(
        f"OCR oncesi tiklama ({delay} saniye beklendi): "
        f"({coordinate[0]}, {coordinate[1]})"
    )


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
):
    pause_escape_monitor_temporarily(escape_monitor_enabled, config, case_name)

    center_x, center_y = match
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(
        f"CASE {case_name}: {template_path.name} bulundu "
        f"(bolge ici=({center_x}, {center_y})) {timestamp}"
    )
    action = case.get("action")
    if action == "click_then_escape":
        screen_x = region[0] + center_x
        screen_y = region[1] + center_y
        pyautogui.click(screen_x, screen_y)
        time.sleep(case.get("escape_delay_seconds", 0.5))
        pyautogui.press("esc")
        print(
            f"{template_path.name} tiklandi, "
            f"{case.get('escape_delay_seconds', 0.5)} saniye sonra ESC basildi."
        )
    elif action == "click_coordinate":
        coordinate = case["click_coordinate"]
        if coordinate == [856, 746]:
            saldirma_click()
        else:
            pyautogui.click(coordinate[0], coordinate[1])
        print(
            f"{template_path.name} bulundu; "
            f"({coordinate[0]}, {coordinate[1]}) koordinatina tiklandi."
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
                window, case, config, monitor_state, uyari_scan_enabled
            )
    elif action == "click_then_text_match_escape":
        screen_x = region[0] + center_x
        screen_y = region[1] + center_y
        pyautogui.click(screen_x, screen_y)
        time.sleep(case.get("text_scan_delay_seconds", 1.0))
        perform_pre_ocr_click(case)
        found = scan_text_region(
            case["text_region"],
            case.get("ocr", {}),
            case.get("target_texts"),
        )
        if found:
            click_before_escape = case.get("click_before_escape")
            if click_before_escape:
                time.sleep(click_before_escape["delay_seconds"])
                pre_coordinate = click_before_escape.get("pre_coordinate")
                if pre_coordinate:
                    pyautogui.click(pre_coordinate[0], pre_coordinate[1])
                    print(
                        "OCR hedefinden sonra on tiklama: "
                        f"({pre_coordinate[0]}, {pre_coordinate[1]})"
                    )
                coordinate = click_before_escape["coordinate"]
                pyautogui.click(coordinate[0], coordinate[1])
                print(
                    "OCR hedefinden sonra ESC oncesi tiklama: "
                    f"({coordinate[0]}, {coordinate[1]})"
                )
            time.sleep(case.get("escape_delay_seconds", 0.5))
            escape_press_count = case.get("escape_press_count", 1)
            for _ in range(escape_press_count):
                pyautogui.press("esc")
                time.sleep(case.get("escape_between_presses_seconds", 0.1))
            print(
                f"OCR hedefinden sonra ESC {escape_press_count} kere basildi."
            )
        else:
            pyautogui.press("esc")
            print("OCR hedefi bulunamadi; ESC basildi.")

def pause_toggle_temporarily(toggle_state, duration_seconds, label):
    if not toggle_state or not toggle_state.get("enabled"):
        return

    toggle_state["enabled"] = False
    print(f"{label} {duration_seconds} saniyeligine pasife alindi.")

    def reactivate():
        toggle_state["enabled"] = True
        print(f"{label} tekrar aktif edildi.")

    timer = threading.Timer(duration_seconds, reactivate)
    timer.daemon = True
    timer.start()


def pause_rally_mode_temporarily(uyari_scan_enabled, config):
    duration = config.get("rally_pause_seconds", 130)
    pause_toggle_temporarily(uyari_scan_enabled, duration, "Ralli modu (R)")


def pause_escape_monitor_temporarily(escape_monitor_enabled, config, case_name):
    if case_name == "excavation":
        duration = config.get("escape_pause_seconds_kazi", 130)
    elif case_name == "clover":
        duration = config.get("escape_pause_seconds_yonca", 30)
    else:
        return
    pause_toggle_temporarily(escape_monitor_enabled, duration, "ESC dongusu (E)")


def perform_excavation_attack(window, case, config, monitor_state, uyari_scan_enabled=None):
    pause_rally_mode_temporarily(uyari_scan_enabled, config)
    monitor_state["paused"] = True
    interval = config.get("game_monitor", {}).get("escape_interval_seconds", 15)
    print(f"Kazi saldirisi basladi; {interval} saniyelik ESC izleme duraklatildi.")
    try:
        jump_wait = case.get("map_jump_wait_seconds", 1.0)
        print(f"Harita sicramasi icin {jump_wait} saniye bekleniyor.")
        time.sleep(jump_wait)

        center_x = window.left + window.width // 2
        center_y = window.top + window.height // 2
        pyautogui.click(center_x, center_y)
        print(f"Oyun merkezi tiklandi: ({center_x}, {center_y})")

        delay = case.get("follow_up_click_delay_seconds", 0.5)
        for coordinate in case["follow_up_coordinates"]:
            time.sleep(delay)
            pyautogui.click(coordinate[0], coordinate[1])
            print(f"Takip tiklamasi: ({coordinate[0]}, {coordinate[1]})")

        time.sleep(delay)
        saldir_click()
        wait_for_share_after_attack(config)
    finally:
        monitor_state["paused"] = False
        print("Kazi saldirisi tamamlandi; 15 saniyelik ESC izleme yeniden etkin.")

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
    try:
        text = pytesseract.image_to_string(
            processed,
            lang=ocr_config.get("language", "tur+eng"),
            config=f"--psm {ocr_config.get('page_segmentation_mode', 6)}",
        ).strip()
    except TesseractNotFoundError:
        message = (
            "Tesseract OCR bulunamadi. "
            "config.json icindeki tesseract_cmd yolunu kontrol edin."
        )
        print(message)
        APP_LOGGER.error(message)
        return False
    if text:
        print("Metin taramasi:")
        print(text)
        APP_LOGGER.info("Metin taramasi:\n%s", text)
    else:
        print("Metin taramasi: metin bulunamadi.")

    if not target_texts:
        return False

    try:
        data = pytesseract.image_to_data(
            processed,
            lang=ocr_config.get("language", "tur+eng"),
            config=f"--psm {ocr_config.get('page_segmentation_mode', 6)}",
            output_type=pytesseract.Output.DICT,
        )
    except TesseractNotFoundError:
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
                print(f"{target} hedef bulundu ve merkezine tiklandi.")
                APP_LOGGER.info(
                    "OCR hedefi bulundu ve tiklandi: %s (%s, %s)",
                    target,
                    click_x,
                    click_y,
                )
                return True

    return False

def scan_cases(
    window,
    config,
    monitor_state,
    uyari_scan_enabled=None,
    escape_monitor_enabled=None,
):
    region = get_scan_region(config)
    screenshot = pyautogui.screenshot(region=region)
    cases = config["scan_cases"]

    for case_name, case in cases.items():
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
                )

def click_matching_templates(
    window,
    config,
    debug_capture=False,
    monitor_state=None,
    uyari_scan_enabled=None,
    escape_monitor_enabled=None,
):
    if monitor_state is None:
        monitor_state = {"paused": False}
    confidence = config["bot"]["image_confidence"]
    bring_game_to_front(window)
    screenshot = pyautogui.screenshot(
        region=(window.left, window.top, window.width, window.height)
    )
    if debug_capture:
        capture_debug_screenshot(window, config)
    scan_cases(window, config, monitor_state, uyari_scan_enabled, escape_monitor_enabled)

    for activity_name, activity in config["activities"].items():
        if not activity["enabled"]:
            continue

        for template_path in get_activity_templates(activity):
            center = find_template_center(screenshot, template_path, confidence)
            if center:
                center_x, center_y = center
                pyautogui.click(window.left + center_x, window.top + center_y)
                print(
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
        f"{escape_interval} saniyelik ESC dongusunu ac/kapat"
    )
    lines.append("  R -> Uyari ve Arti taramasini ac/kapat")

    for line in lines:
        print(line)

    KUTUPHANE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with SHORTCUTS_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(f"--- {timestamp} ---\n")
        file.write("\n".join(lines))
        file.write("\n\n")

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
                relative_x = x - window.left
                relative_y = y - window.top
                print(
                    f"Mouse tiklamasi: ekran=({x}, {y}), "
                    f"oyun penceresi ici=({relative_x}, {relative_y})"
                )
                return
            was_pressed = is_pressed
            time.sleep(0.02)
        print(f"J: {timeout_seconds} saniye icinde tiklama algilanmadi.")

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()


def create_input_listeners(window, config, running_state):
    shortcut_map = {
        activity["shortcut"].lower(): activity_name
        for activity_name, activity in config["activities"].items()
    }
    controls = config["controls"]
    text_scan_requested = {"enabled": False}
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
            print(f"{pressed_key.upper()} -> bot durduruluyor...")
            running_state["running"] = False
            return False

        if pressed_key == "r":
            uyari_scan_enabled["enabled"] = not uyari_scan_enabled["enabled"]
            state = "acik" if uyari_scan_enabled["enabled"] else "kapali"
            print(f"R -> Uyari/Arti taramasi: {state}")
            return

        if pressed_key == controls["coordinate_shortcut"].lower():
            print("J -> sonraki mouse tiklamasi bekleniyor.")
            start_click_coordinate_capture(window)
            return

        if pressed_key == controls["text_scan_shortcut"].lower():
            text_scan_requested["enabled"] = True
            print("O -> metin taramasi istendi.")
            return

        if pressed_key == controls["debug_screenshot_shortcut"].lower():
            debug_capture["enabled"] = not debug_capture["enabled"]
            state = "acik" if debug_capture["enabled"] else "kapali"
            print(f"T -> tarama ekran goruntusu: {state}")
            return

        if pressed_key == controls["escape_monitor_shortcut"].lower():
            escape_monitor_enabled["enabled"] = not escape_monitor_enabled["enabled"]
            state = "acik" if escape_monitor_enabled["enabled"] else "kapali"
            print(
                f"{pressed_key.upper()} -> {escape_interval} saniyelik ESC dongusu: {state}"
            )
            return

        activity_name = shortcut_map.get(pressed_key)
        if activity_name is None:
            return

        activity = config["activities"][activity_name]
        activity["enabled"] = not activity["enabled"]
        state = "acik" if activity["enabled"] else "kapali"
        print(f"{pressed_key.upper()} -> {activity_name}: {state}")

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
        debug_capture,
        escape_monitor_enabled,
        uyari_scan_enabled,
    )

def capture_single_debug_region(region_name, region_tuple):
    """(left, top, width, height) formatindaki bolgeyi kirmizi cerceveyle kaydeder."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot = pyautogui.screenshot(region=region_tuple)
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    h, w = image.shape[:2]

    # Bolge etrafina kirmizi cerceve ve etiket ciz
    cv2.rectangle(image, (0, 0), (w - 1, h - 1), (0, 0, 255), 2)
    cv2.putText(
        image,
        region_name,
        (4, 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )

    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    path = SCREENSHOTS_DIR / f"{region_name}_{timestamp}.png"
    cv2.imwrite(str(path), image)
    print(f"{region_name} icin kirmizi cerceveli ekran goruntusu: {path}")

def is_green_present(region_tuple):
    """Belirtilen bolgede yesil arti butonu rengini tespit eder."""
    screenshot = pyautogui.screenshot(region=region_tuple)
    img_hsv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(img_hsv, np.array([35, 70, 70]), np.array([85, 255, 255]))
    return cv2.countNonZero(mask) >= 80


def handle_uyari_scan(window, config, debug_capture=False):
    uyari_coords = {"top_left": [1616, 578], "bottom_right": [1698, 649]}
    arti_coords = {"top_left": [831, 272], "bottom_right": [899, 341]}
    ocr_coords = {"top_left": [918, 305], "bottom_right": [1095, 389]}

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
        # 1. Uyari butonuna tikla
        click_target_x = uyari_region[0] + (uyari_region[2] // 2)
        click_target_y = uyari_region[1] + (uyari_region[3] // 2)
        pyautogui.click(click_target_x, click_target_y)
        print(f"\n[UYARI BULUNDU] Tiklandi -> ({click_target_x}, {click_target_y})")

        # 2. Ekranin acilmasi icin bekle
        time.sleep(1.0)

        # 3. OCR Taramasi ve Kosul Kontrolu
        if debug_capture:
            capture_debug_screenshot(window, config, [("ocr_metin_alani", ocr_coords)])

        raw_ocr_text = get_text_from_region(ocr_coords, config.get("ocr", {}))
        print(f"--- [OCR METNI OKUNDU]:\n{raw_ocr_text}\n-----------------------")

        # Kıyamet Eliti ve Seviye > 25 sarti kontrol edilir
        if not check_elite_level(raw_ocr_text):
            pyautogui.press("esc")
            print("[KOSUL SAGLANMADI] Hedef uygun degil, ESC basildi.")
            return

        # 4. Asama: Sart saglandiysa arti.png / yesil arti ara
        if debug_capture:
            capture_debug_screenshot(window, config, [("arti_alani", arti_coords)])

        arti_region = (831, 272, 899 - 831, 341 - 272)

        if is_green_present(arti_region):
            center_x = arti_region[0] + (arti_region[2] // 2)
            center_y = arti_region[1] + (arti_region[3] // 2)
            pyautogui.click(center_x, center_y)
            print(f"[ARTI BULUNDU] Merkeze tiklandi -> ({center_x}, {center_y})")

            arti_click_delay = config.get("arti_click_delay_seconds", 1.5)
            time.sleep(arti_click_delay)
            saldir_click()
            print("⚔️ [SALDIRI] Saldiri tetiklendi.")
            time.sleep(1.0)
        else:
            pyautogui.press("esc")
            print("[ARTI BULUNAMADI] Slot kapali veya dolu, ESC basildi.")

def check_elite_level(ocr_text):
    """
    Metin icinde Kiyamet Eliti ve seviye 25 ustunu kontrol eder.
    Gelen ornek: 'Svi28\nKıyametEliti'
    """
    if not ocr_text:
        print("[OCR RED] Metin bos okundu.")
        return False

    clean_text = normalize_ocr_text(ocr_text)
    print(f"[DEBUG OCR TEMIZ METIN]: '{clean_text}'")

    # 1. Kiyamet kontrolu (normalize edildiginde kiyamet olmus olmali)
    if "kiyamet" not in clean_text and "kiymet" not in clean_text:
        print(f"[OCR RED] 'kiyamet' kelimesi metinde yok: '{clean_text}'")
        return False

    # 2. Seviye rakamini yakalama (2 haneli sayilari cek)
    numbers = re.findall(r"\d{2}", clean_text)
    if not numbers:
        print(f"[OCR RED] 2 haneli seviye rakami bulunamadi: '{clean_text}'")
        return False

    level = int(numbers[0])
    print(f"[OCR TESPIT] Hedef: Kiyamet Eliti | Seviye: {level}")

    # 3. Seviye 25 ustu kontrolu
    if level > 24:
        print(f"[OCR ONAY] Seviye uygun ({level} > 24). Arti aranacak.")
        return True
    else:
        print(f"[OCR RED] Seviye 25 veya alti (Sv.{level} <= 25).")
        return False

def get_text_from_region(text_region, ocr_config):
    left, top = text_region["top_left"]
    right, bottom = text_region["bottom_right"]
    width = abs(right - left)
    height = abs(bottom - top)

    screenshot = pyautogui.screenshot(
        region=(min(left, right), min(top, bottom), width, height)
    )
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    scale = ocr_config.get("scale", 3)
    enlarged = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    processed = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    
    try:
        return pytesseract.image_to_string(
            processed,
            lang=ocr_config.get("language", "tur+eng"),
            config=f"--psm {ocr_config.get('page_segmentation_mode', 6)}",
        ).strip()
    except Exception:
        return ""

def is_uyari_present(screenshot):
    """Uyari bolgesinde kirmizi hedef butonunun belirdigini dogrular."""
    img_hsv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2HSV)
    mask1 = cv2.inRange(img_hsv, np.array([0, 120, 100]), np.array([10, 255, 255]))
    mask2 = cv2.inRange(img_hsv, np.array([170, 120, 100]), np.array([180, 255, 255]))
    red_mask = mask1 | mask2
    return cv2.countNonZero(red_mask) >= 250

def run_bot(config):
    log_shortcuts(config)
    existing_window = find_game_window(config)
    if existing_window is not None:
        print("Oyun penceresi zaten acik; baslangic tiklamalari atlandi.")
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
        perform_startup_clicks(config)
    else:
        print("Oyun zaten acikti; baslangic tiklamalari atlandi.")

    running_state = {"running": True}
    (
        keyboard_listener,
        text_scan_requested,
        debug_capture,
        escape_monitor_enabled,
        uyari_scan_enabled,
    ) = create_input_listeners(window, config, running_state)

    print("Bot calisiyor. Durdurmak icin S basin.")
    next_escape_at = time.monotonic()
    monitor_state = {"paused": False}
    try:
        while running_state["running"] and keyboard_listener.is_alive():
            if uyari_scan_enabled["enabled"]:
                handle_uyari_scan(window, config, debug_capture["enabled"])
                if not running_state["running"]:
                    break

            monitor_action, next_escape_at = monitor_game_state(
                config,
                next_escape_at,
                allow_escape=(
                    not monitor_state["paused"]
                    and escape_monitor_enabled["enabled"]
                ),
            )
            if not running_state["running"]:
                break

            if monitor_action == "restart":
                window = restart_game_after_disconnect(config)
                next_escape_at = time.monotonic()
                continue

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
            )

            # Döngü aralığını daha duyarlı uyutma ile kontrol et
            sleep_duration = config["bot"]["scan_interval_seconds"]
            step = 0.1
            elapsed = 0.0
            while elapsed < sleep_duration and running_state["running"]:
                time.sleep(step)
                elapsed += step

    finally:
        keyboard_listener.stop()
        print("Bot basariyla sonlandirildi.")

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
        print("\nBot durduruldu.")
    except Exception:
        APP_LOGGER.exception("Uygulama hatasi")
        STARTUP_LOGGER.exception("EXE baslangic/calisma hatasi")
        print("Hata olustu. logs/application.log ve logs/startup.log dosyalarini kontrol edin.")