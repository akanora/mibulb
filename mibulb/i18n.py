"""Translations.

The app's text is written in English. When another language is active,
install_tk() makes Tkinter translate text as it is put on screen (labels,
buttons, menus, dialogs, window titles), so the rest of the code doesn't
need to wrap every string. Messages with changing parts are matched against
TEMPLATES, e.g. "Downloading Mi Bulb {version}… {percent}%".

To add a language: add it to LANGUAGES and give it an exact-text table and
a template table like TURKISH and TURKISH_TEMPLATES.
"""

from __future__ import annotations

import locale
import re
import sys

LANGUAGES = {"en": "English", "tr": "Türkçe"}

_language = "en"

# ---- Turkish -------------------------------------------------------------------

TURKISH = {
    # Main window
    "Light": "Işık",
    "Power": "Güç",
    "On": "Açık",
    "Off": "Kapalı",
    "Brightness": "Parlaklık",
    "White temperature": "Beyaz sıcaklığı",
    "White": "Beyaz",
    "Warm": "Sıcak",
    "Neutral": "Nötr",
    "Daylight": "Gün ışığı",
    "Colour": "Renk",
    "Pick…": "Seç…",
    "Pick a colour": "Bir renk seçin",
    "Screen sync": "Ekran senkronu",
    "Stop sync": "Senkronu durdur",
    "Scenes": "Sahneler",
    "+ Save current": "+ Mevcudu kaydet",
    "Click to apply · right-click to update, rename or delete":
        "Uygulamak için tıklayın · güncellemek, yeniden adlandırmak ya da silmek için sağ tıklayın",
    "No scenes yet": "Henüz sahne yok",
    "All lights": "Tüm ışıklar",
    "Not configured – open settings (⚙) to add your bulb.": "Ayarlanmadı – ampulünüzü eklemek için ayarları (⚙) açın.",
    "Add your bulb first (⚙).": "Önce ampulünüzü ekleyin (⚙).",
    "Timer cancelled.": "Zamanlayıcı iptal edildi.",
    "Screen sync is on  ·  click to stop": "Ekran senkronu açık  ·  durdurmak için tıklayın",
    "Screen sync stopped.": "Ekran senkronu durduruldu.",
    "colour": "renk",
    "white": "beyaz",
    # Scenes
    "Save scene": "Sahneyi kaydet",
    "Name for this scene:": "Bu sahnenin adı:",
    "Apply": "Uygula",
    "Update to current light": "Şu anki ışıkla güncelle",
    "Rename…": "Yeniden adlandır…",
    "Set shortcut…": "Kısayol ata…",
    "Delete": "Sil",
    "Rename scene": "Sahneyi yeniden adlandır",
    "New name:": "Yeni ad:",
    "Delete scene": "Sahneyi sil",
    "Scene (deleted)": "Sahne (silinmiş)",
    "Reading": "Okuma",
    "Relax": "Dinlenme",
    "Movie": "Film",
    "Gaming": "Oyun",
    "Night light": "Gece lambası",
    # Effects
    "Effects": "Efektler",
    "Music sync": "Müzik senkronu",
    "Stop music sync": "Müzik senkronunu durdur",
    "Music sync is on  ·  click to stop": "Müzik senkronu açık  ·  durdurmak için tıklayın",
    "Music sync stopped.": "Müzik senkronu durduruldu.",
    "Music sync on/off": "Müzik senkronu aç/kapat",
    "Music sync needs the PyAudioWPatch package": "Müzik senkronu için PyAudioWPatch paketi gerekli",
    "Screen to follow": "Takip edilecek ekran",
    "Export settings…": "Ayarları dışa aktar…",
    "Import settings…": "Ayarları içe aktar…",
    "Export settings": "Ayarları dışa aktar",
    "Import settings": "Ayarları içe aktar",
    "The exported file includes your bulbs' tokens in readable form, so it works on another PC. "
    "Keep it somewhere private.":
        "Dışa aktarılan dosya, başka bir bilgisayarda da çalışması için ampullerinizin anahtarlarını okunabilir "
        "biçimde içerir. Onu güvenli bir yerde saklayın.",
    "Settings imported.": "Ayarlar içe aktarıldı.",
    "Local API (Stream Deck, scripts, Home Assistant)": "Yerel API (Stream Deck, betikler, Home Assistant)",
    "Let other apps control Mi Bulb through a web address with a key":
        "Diğer uygulamaların Mi Bulb'u anahtarlı bir web adresiyle kontrol etmesine izin ver",
    "Also from other devices on my network (Windows may ask about the firewall)":
        "Ağımdaki diğer cihazlardan da (Windows güvenlik duvarını sorabilir)",
    "Copy": "Kopyala",
    "New key": "Yeni anahtar",
    "Replace toggle with on, off, status, brightness?value=40, scene?name=Relax and more (see the README). "
    "Keep the key private.":
        "toggle yerine on, off, status, brightness?value=40, scene?name=Relax ve daha fazlasını kullanın "
        "(README'ye bakın). Anahtarı gizli tutun.",
    "Effects ▾": "Efektler ▾",
    "Stop effect": "Efekti durdur",
    "Candle": "Mum ışığı",
    "Breathing": "Nefes",
    "Rainbow": "Gökkuşağı",
    "Party": "Parti",
    "Romance": "Romantik",
    "Ocean": "Okyanus",
    "Police": "Polis",
    "Alarm": "Alarm",
    # Timer menu and tray
    "Schedules…": "Zamanlamalar…",
    "Cancel timer": "Zamanlayıcıyı iptal et",
    "Quick panel": "Hızlı panel",
    "Toggle": "Aç/Kapat",
    "Turn on": "Aç",
    "Turn off": "Kapat",
    "Sleep timer": "Uyku zamanlayıcısı",
    "Open window": "Pencereyi aç",
    "Settings…": "Ayarlar…",
    "Quit": "Çıkış",
    "Open Mi Bulb": "Mi Bulb'u aç",
    "⏾ Sleep 30 min": "⏾ 30 dk uyku",
    # Sign-in
    "Sign in with Xiaomi": "Xiaomi ile giriş yap",
    "Open the Xiaomi Home app on your phone, tap the scan icon (top right of the home screen) and scan this code.":
        "Telefonunuzda Xiaomi Home uygulamasını açın, ana ekranın sağ üstündeki tarama simgesine dokunun "
        "ve bu kodu okutun.",
    "Loading…": "Yükleniyor…",
    "Contacting Xiaomi…": "Xiaomi'ye bağlanılıyor…",
    "Your password is never entered here. Only your bulbs' IPs and tokens are saved.":
        "Şifreniz buraya hiç girilmez. Yalnızca ampullerinizin IP adresleri ve anahtarları (token) kaydedilir.",
    "Cancel": "İptal",
    "Open in browser": "Tarayıcıda aç",
    "Install Pillow to show the QR code,\nor use 'Open in browser'.":
        "QR kodu göstermek için Pillow'u kurun\nya da 'Tarayıcıda aç'ı kullanın.",
    "Waiting for you to scan the code…": "Kodu okutmanız bekleniyor…",
    "Signed in. Reading your devices from every region…": "Giriş yapıldı. Cihazlarınız tüm bölgelerden okunuyor…",
    "Sign-in cancelled": "Giriş iptal edildi",
    "The QR code expired. Try again.": "QR kodunun süresi doldu. Tekrar deneyin.",
    "Xiaomi did not return a service token": "Xiaomi bir hizmet anahtarı döndürmedi",
    # Settings window
    "Mi Bulb settings": "Mi Bulb ayarları",
    "Bulbs": "Ampuller",
    "App": "Uygulama",
    "Shortcuts": "Kısayollar",
    "Automation": "Otomasyon",
    "Close": "Kapat",
    "Save": "Kaydet",
    "Save bulb": "Ampulü kaydet",
    "App options are saved as you change them.": "Uygulama seçenekleri değiştirdiğiniz anda kaydedilir.",
    # Bulbs tab
    "Your bulbs": "Ampulleriniz",
    "New": "Yeni",
    "Remove": "Kaldır",
    "Remove bulb": "Ampulü kaldır",
    "Find bulbs automatically": "Ampulleri otomatik bul",
    "Sign in by scanning a QR code with the Xiaomi Home app. Your bulbs and their tokens are filled in for you.":
        "Xiaomi Home uygulamasıyla bir QR kodu okutarak giriş yapın. Ampulleriniz ve anahtarları sizin için "
        "doldurulur.",
    "No devices yet": "Henüz cihaz yok",
    "No devices found on this account": "Bu hesapta cihaz bulunamadı",
    "Add all lights from my account": "Hesabımdaki tüm ışıkları ekle",
    "Bulb details (or enter them yourself)": "Ampul bilgileri (ya da kendiniz girin)",
    "Name": "Ad",
    "IP address": "IP adresi",
    "Token": "Anahtar (token)",
    "Show token": "Anahtarı göster",
    "Scan network": "Ağı tara",
    "Scanning…": "Taranıyor…",
    "No miIO devices found": "miIO cihazı bulunamadı",
    "  No bulbs yet: sign in with Xiaomi below": "  Henüz ampul yok: aşağıdan Xiaomi ile giriş yapın",
    "Fill in the details below, or sign in with Xiaomi, then click Save bulb.":
        "Aşağıdaki bilgileri doldurun ya da Xiaomi ile giriş yapın, sonra Ampulü kaydet'e tıklayın.",
    "Bulb settings": "Ampul ayarları",
    "Enter the bulb's IP address and its 32-character token.": "Ampulün IP adresini ve 32 karakterlik anahtarını girin.",
    # App tab
    "Startup": "Başlangıç",
    "Start Mi Bulb in the tray when I sign in to Windows": "Windows'ta oturum açtığımda Mi Bulb'u tepside başlat",
    "Start with Windows": "Windows ile başlat",
    "Tray icon": "Tepsi simgesi",
    "Left-click opens the quick panel": "Sol tık hızlı paneli açar",
    "Left-click toggles the light": "Sol tık ışığı açar/kapatır",
    "Also follow how bright the screen is": "Ekranın parlaklığını da takip et",
    "Works with windowed and borderless games. Exclusive fullscreen games may not be captured; "
    "the light then keeps its last colour.":
        "Pencereli ve kenarlıksız oyunlarla çalışır. Özel tam ekran oyunlar yakalanamayabilir; o zaman ışık "
        "son rengini korur.",
    "Updates": "Güncellemeler",
    "Install new versions automatically (checked when Mi Bulb starts)":
        "Yeni sürümleri otomatik kur (Mi Bulb açılırken kontrol edilir)",
    "Check now": "Şimdi kontrol et",
    "Checking…": "Kontrol ediliyor…",
    "Couldn't reach GitHub.": "GitHub'a ulaşılamadı.",
    "You have the latest version.": "En son sürümü kullanıyorsunuz.",
    "Your data": "Verileriniz",
    "Open folder": "Klasörü aç",
    "Forget all bulbs": "Tüm ampulleri unut",
    "Remove every bulb's name, IP address and token from this PC?\n\n"
    "You can add them again any time with 'Sign in with Xiaomi'.":
        "Tüm ampullerin adı, IP adresi ve anahtarı bu bilgisayardan silinsin mi?\n\n"
        "Onları istediğiniz zaman 'Xiaomi ile giriş yap' ile yeniden ekleyebilirsiniz.",
    "Language": "Dil",
    "Automatic (Windows language)": "Otomatik (Windows dili)",
    "Restart Mi Bulb to use the new language.": "Yeni dili kullanmak için Mi Bulb'u yeniden başlatın.",
    "Restart now": "Şimdi yeniden başlat",
    # Shortcuts tab
    "Use keyboard shortcuts (they work in any app)": "Klavye kısayollarını kullan (her uygulamada çalışır)",
    "Click a shortcut, then press the keys you want. Esc cancels, Backspace clears it.\n"
    "On some keyboard layouts Ctrl+Alt+<key> also types a special character (AltGr). "
    "If a character stops working, pick a different shortcut.":
        "Bir kısayola tıklayın, sonra istediğiniz tuşlara basın. Esc iptal eder, Backspace temizler.\n"
        "Bazı klavye düzenlerinde Ctrl+Alt+<tuş> özel bir karakter de yazar (AltGr). Bir karakter çalışmaz "
        "hale gelirse başka bir kısayol seçin.",
    "Reset to defaults": "Varsayılanlara dön",
    "Not set": "Atanmadı",
    "Press keys…": "Tuşlara basın…",
    "Esc to cancel": "İptal için Esc",
    "Toggle light": "Işığı aç/kapat",
    "Brighter (+10%)": "Daha parlak (+%10)",
    "Dimmer (-10%)": "Daha loş (-%10)",
    "Warm white": "Sıcak beyaz",
    "Neutral white": "Nötr beyaz",
    "Show Mi Bulb window": "Mi Bulb penceresini göster",
    "Sleep timer (30 min)": "Uyku zamanlayıcısı (30 dk)",
    "Screen sync on/off": "Ekran senkronu aç/kapat",
    "That key can't be used in a shortcut.": "Bu tuş kısayolda kullanılamaz.",
    "Use Ctrl, Alt or Win together with the key, so normal typing isn't blocked.":
        "Normal yazmayı engellememek için tuşla birlikte Ctrl, Alt ya da Win kullanın.",
    "Already used by Windows or another app.": "Windows ya da başka bir uygulama tarafından kullanılıyor.",
    # Automation tab and schedules
    "Follow the PC": "Bilgisayarı takip et",
    "Turn the light off when I lock the PC or it goes to sleep":
        "Bilgisayarı kilitlediğimde ya da uyku moduna geçtiğinde ışığı kapat",
    "Turn it back on when I return (only if Mi Bulb turned it off)": "Döndüğümde tekrar aç (yalnızca Mi Bulb kapattıysa)",
    "Schedule": "Zamanlama",
    "+ Add schedule": "+ Zamanlama ekle",
    "Schedules run while Mi Bulb is running (it can stay in the tray). "
    "A sunrise starts at the set time and reaches full brightness at the end.":
        "Zamanlamalar Mi Bulb çalışırken uygulanır (tepside durabilir). Gün doğumu ayarlanan saatte başlar "
        "ve sonunda tam parlaklığa ulaşır.",
    "No schedules yet.": "Henüz zamanlama yok.",
    "Edit": "Düzenle",
    "Time": "Saat",
    "Days": "Günler",
    "Do this": "Yapılacak",
    "Every day": "Her gün",
    "Weekdays": "Hafta içi",
    "Weekends": "Hafta sonu",
    "Never": "Hiçbir zaman",
    "Pick at least one day.": "En az bir gün seçin.",
    "Time must be between 00:00 and 23:59": "Saat 00:00 ile 23:59 arasında olmalı",
    "Evening warmth": "Akşam sıcaklığı",
    "Make white light warmer in the evening": "Akşamları beyaz ışığı daha sıcak yap",
    "From": "Başlangıç",
    "to": "bitiş",
    "ending at": "en sıcak",
    "Sunset": "Gün batımı",
    "Your location (for sunset)": "Konumunuz (gün batımı için)",
    "Latitude and longitude, e.g. 41.01, 28.98 for Istanbul. Only used to work out sunset, on this PC. "
    "Without it, Sunset means 20:00.":
        "Enlem ve boylam, ör. İstanbul için 41.01, 28.98. Yalnızca gün batımını hesaplamak için bu bilgisayarda "
        "kullanılır. Girilmezse Gün batımı 20:00 demektir.",
    "No sunset today at this location.": "Bu konumda bugün gün batımı yok.",
    "Which light": "Hangi ışık",
    "The lights picked in the window": "Pencerede seçili ışıklar",
    "Removed bulb": "Kaldırılmış ampul",
    "Mon": "Pzt",
    "Tue": "Sal",
    "Wed": "Çar",
    "Thu": "Per",
    "Fri": "Cum",
    "Sat": "Cmt",
    "Sun": "Paz",
    # Errors from the bulb, the cloud and updates
    "Token must be 32 hexadecimal characters": "Anahtar 32 onaltılık (hex) karakter olmalı",
    "Checksum mismatch - is the token correct?": "Sağlama toplamı uyuşmuyor – anahtar doğru mu?",
    "No bulbs": "Ampul yok",
    "Colour must look like #RRGGBB": "Renk #RRGGBB biçiminde olmalı",
    "The release has no checksum for the installer, so it won't be installed.":
        "Bu sürümde kurulum dosyası için sağlama değeri yok, bu yüzden kurulmayacak.",
    "This release has no installer to download.": "Bu sürümde indirilecek kurulum dosyası yok.",
    "The downloaded installer didn't match its published checksum, so it was deleted.":
        "İndirilen kurulum dosyası yayımlanan sağlama değeriyle eşleşmedi, bu yüzden silindi.",
}

# Messages with changing parts. {count}, {percent} and {minutes} only match numbers.
TURKISH_TEMPLATES = {
    "Connected to {target} · {mode} mode": "Bağlı: {target} · {mode} modu",
    "Connected to {target}": "Bağlı: {target}",
    # Pieces put together in the window: translate each part
    "{name} ▾": "{name} ▾",
    "{name} – Mi Bulb": "{name} – Mi Bulb",
    "{time}   {days}   →   {action}": "{time}   {days}   →   {action}",
    "{count} lights": "{count} ışık",
    "{name}: on": "{name}: açık",
    "{name}: off": "{name}: kapalı",
    "Found {name} at its new address {ip}.": "{name} yeni adresinde bulundu: {ip}.",
    "Sunrise wake-up ({minutes} min)": "Gün doğumu uyandırma ({minutes} dk)",
    "Scene: {name}": "Sahne: {name}",
    "Sunset today: {time}": "Bugün gün batımı: {time}",
    "{time}   {days}   →   {action}   ({target})": "{time}   {days}   →   {action}   ({target})",
    "Effect: {name}": "Efekt: {name}",
    "Main screen ({size})": "Ana ekran ({size})",
    "Saved to {path}": "Kaydedildi: {path}",
    "The local API couldn't start on port {port}: {error}": "Yerel API {port} portunda başlatılamadı: {error}",
    "Replace your current settings with the ones in {file}? It has {count} bulb(s) and {scenes} scene(s).":
        "Mevcut ayarlarınız {file} içindekilerle değiştirilsin mi? Dosyada {count} ampul ve {scenes} sahne var.",
    "Screen {number} ({size})": "Ekran {number} ({size})",
    "Couldn't listen to the PC's sound: {error}": "Bilgisayarın sesi dinlenemedi: {error}",
    "Effect: {name}  ·  click to stop": "Efekt: {name}  ·  durdurmak için tıklayın",
    "This bulb doesn't support {feature}": "Bu ampul şunu desteklemiyor: {feature}",
    "Remove {name} from Mi Bulb?": "{name} Mi Bulb'dan kaldırılsın mı?",
    "Settings and your bulb's token are stored in\n{folder}": "Ayarlar ve ampulünüzün anahtarı şurada saklanır:\n{folder}",
    "Could not change the setting: {error}": "Ayar değiştirilemedi: {error}",
    "{text} is already used for {label}.": "{text} zaten şunun için kullanılıyor: {label}.",
    "Installing version {version}…": "{version} sürümü kuruluyor…",
    "Version {version} is available. Click to download.": "{version} sürümü çıktı. İndirmek için tıklayın.",
    "Add all {count} lights from my account": "Hesabımdaki {count} ışığın hepsini ekle",
    "Added {count} new light(s). Pick one or All lights from the name at the top of the main window.":
        "{count} yeni ışık eklendi. Ana pencerenin üstündeki addan birini ya da Tüm ışıklar'ı seçin.",
    "{ip}  (device id {did})": "{ip}  (cihaz kimliği {did})",
    "Saved {name}.": "{name} kaydedildi.",
    "Saved scene \"{name}\". Give it a shortcut in settings.":
        "\"{name}\" sahnesi kaydedildi. Ayarlardan ona bir kısayol verebilirsiniz.",
    "Updated scene \"{name}\".": "\"{name}\" sahnesi güncellendi.",
    "Delete the scene \"{name}\"?": "\"{name}\" sahnesi silinsin mi?",
    "Mi Bulb {version} is available. Click to download.": "Mi Bulb {version} çıktı. İndirmek için tıklayın.",
    "Downloading Mi Bulb {version}… {percent}%": "Mi Bulb {version} indiriliyor… %{percent}",
    "Downloading Mi Bulb {version}…": "Mi Bulb {version} indiriliyor…",
    "Update failed: {error}": "Güncelleme başarısız: {error}",
    "Installing Mi Bulb {version}. It will reopen by itself.": "Mi Bulb {version} kuruluyor. Kendiliğinden yeniden açılacak.",
    "Update to {version} was cancelled. Use Settings → App → Check now to retry.":
        "{version} güncellemesi iptal edildi. Tekrar denemek için: Ayarlar → Uygulama → Şimdi kontrol et.",
    "Off in {minutes} min": "{minutes} dk sonra kapat",
    "Sleep timer: off in {minutes} min": "Uyku zamanlayıcısı: {minutes} dk sonra kapat",
    "Sunrise now ({minutes} min)": "Şimdi gün doğumu ({minutes} dk)",
    "Sleep timer: off at {time}": "Uyku zamanlayıcısı: kapanış {time}",
    "Sunrise: full brightness at {time}": "Gün doğumu: tam parlaklık {time}",
    "{label}  ·  click to cancel": "{label}  ·  iptal için tıklayın",
    "No response from {ip} (is it on and on the same network?)": "{ip} yanıt vermiyor (açık mı ve aynı ağda mı?)",
    "Network error talking to {ip}: {error}": "{ip} ile iletişimde ağ hatası: {error}",
    "Device error: {error}": "Cihaz hatası: {error}",
    "{names} didn't respond ({error})": "{names} yanıt vermedi ({error})",
    "Could not reach Xiaomi's login server: {error}": "Xiaomi giriş sunucusuna ulaşılamadı: {error}",
    "Could not download the QR code: {error}": "QR kodu indirilemedi: {error}",
    "Lost connection to Xiaomi while waiting: {error}": "Beklerken Xiaomi bağlantısı koptu: {error}",
    "Could not finish signing in: {error}": "Giriş tamamlanamadı: {error}",
    "Could not read devices: {error}": "Cihazlar okunamadı: {error}",
    "Download failed: {error}": "İndirme başarısız: {error}",
    "On your keyboard this also types {char}": "Klavyenizde bu kısayol {char} karakterini de yazar",
}

_TABLES = {"tr": (TURKISH, TURKISH_TEMPLATES)}
_NUMBER_FIELDS = {"count", "percent", "minutes"}
_compiled: dict[str, list[tuple[re.Pattern, str]]] = {}


def _compile(templates: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    compiled = []
    for english, translated in templates.items():
        parts = re.split(r"\{(\w+)\}", english)
        pattern = ""
        for i, part in enumerate(parts):
            if i % 2:
                pattern += rf"(?P<{part}>\d+)" if part in _NUMBER_FIELDS else rf"(?P<{part}>.+?)"
            else:
                pattern += re.escape(part)
        literal_length = sum(len(p) for p in parts[::2])
        compiled.append((literal_length, re.compile(f"^{pattern}$", re.DOTALL), translated))
    # Most specific (longest fixed text) first, so "Connected to X · Y mode" wins over "Connected to X".
    compiled.sort(key=lambda item: -item[0])
    return [(regex, translated) for _length, regex, translated in compiled]


def detect_language() -> str:
    """The Windows display language if we have a translation for it, else English."""
    try:
        if sys.platform == "win32":
            import ctypes

            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x1F:  # LANG_TURKISH
                return "tr"
            return "en"
        name = (locale.getlocale()[0] or "").lower()
        return "tr" if name.startswith(("tr", "turkish")) else "en"
    except Exception:
        return "en"


def resolve(setting: str) -> str:
    return setting if setting in LANGUAGES else detect_language()


def set_language(code: str) -> None:
    global _language
    _language = code if code in LANGUAGES else "en"


def current() -> str:
    return _language


def t(text: str, _depth: int = 0) -> str:
    """Translate English text into the current language (unknown text is returned unchanged)."""
    if _language == "en" or not isinstance(text, str) or not text:
        return text
    exact, templates = _TABLES[_language]
    if text in exact:
        return exact[text]
    if _depth > 2:
        return text
    if _language not in _compiled:
        _compiled[_language] = _compile(templates)
    for regex, translated in _compiled[_language]:
        match = regex.match(text)
        if match:
            values = {key: t(value, _depth + 1) for key, value in match.groupdict().items()}
            return translated.format(**values)
    return text


_installed = False


def install_tk() -> None:
    """Translate text as Tkinter puts it on screen. Safe to call more than once."""
    global _installed
    if _installed:
        return
    import tkinter

    # These are Tkinter internals. If a future Python changes them, show English
    # rather than fail to start.
    original_options = getattr(tkinter.Misc, "_options", None)
    original_title = getattr(tkinter.Wm, "wm_title", None)
    if not callable(original_options) or not callable(original_title) or not hasattr(tkinter, "_cnfmerge"):
        _installed = True
        set_language("en")
        return

    def _options(self, cnf, kw=None):
        merged = tkinter._cnfmerge((cnf, kw)) if kw else tkinter._cnfmerge(cnf)
        if _language != "en" and merged:
            merged = dict(merged)
            for key in ("text", "label", "title", "message"):
                if isinstance(merged.get(key), str):
                    merged[key] = t(merged[key])
            values = merged.get("values")
            if isinstance(values, (list, tuple)):
                merged["values"] = [t(v) if isinstance(v, str) else v for v in values]
        return original_options(self, merged)

    def wm_title(self, string=None):
        return original_title(self, t(string) if isinstance(string, str) else string)

    tkinter.Misc._options = _options
    tkinter.Wm.wm_title = tkinter.Wm.title = wm_title
    _installed = True
