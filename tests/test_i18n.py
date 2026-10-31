import tkinter as tk
import unittest

from mibulb import i18n


class TranslateTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_english_passes_through(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("Brightness"), "Brightness")

    def test_exact_and_unknown(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.t("Brightness"), "Parlaklık")
        self.assertEqual(i18n.t("Desk lamp"), "Desk lamp")  # names and other data stay as they are
        self.assertEqual(i18n.t(""), "")

    def test_templates(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.t("Downloading Mi Bulb 0.9.0… 45%"), "Mi Bulb 0.9.0 indiriliyor… %45")
        self.assertEqual(i18n.t("Connected to 192.168.1.5 · colour mode"), "Bağlı: 192.168.1.5 · renk modu")
        self.assertEqual(i18n.t("All lights ▾"), "Tüm ışıklar ▾")

    def test_parts_are_translated_too(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.t("07:00   Weekdays   →   Sunrise wake-up (15 min)"),
                         "07:00   Hafta içi   →   Gün doğumu uyandırma (15 dk)")
        self.assertEqual(i18n.t("Desk didn't respond (No response from 1.2.3.4 (is it on and on the same network?))"),
                         "Desk yanıt vermedi (1.2.3.4 yanıt vermiyor (açık mı ve aynı ağda mı?))")

    def test_number_fields_only_match_numbers(self):
        i18n.set_language("tr")
        self.assertEqual(i18n.t("3 lights"), "3 ışık")
        self.assertEqual(i18n.t("All lights"), "Tüm ışıklar")
        self.assertEqual(i18n.t("many lights"), "many lights")

    def test_every_template_placeholder_is_used(self):
        import re

        for english, turkish in i18n.TURKISH_TEMPLATES.items():
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", english)), sorted(re.findall(r"\{(\w+)\}", turkish)),
                             english)

    def test_language_setting(self):
        self.assertEqual(i18n.resolve("tr"), "tr")
        self.assertEqual(i18n.resolve("en"), "en")
        self.assertIn(i18n.resolve("auto"), i18n.LANGUAGES)


class TkInternalsTest(unittest.TestCase):
    def test_hooks_exist_on_this_python(self):
        # If this fails on a new Python, install_tk() falls back to English; update the hooks.
        self.assertTrue(callable(getattr(tk.Misc, "_options", None)))
        self.assertTrue(callable(getattr(tk.Wm, "wm_title", None)))
        self.assertTrue(hasattr(tk, "_cnfmerge"))


class TkTest(unittest.TestCase):
    def test_widgets_are_translated(self):
        i18n.install_tk()
        i18n.set_language("tr")
        try:
            root = tk.Tk()
            root.withdraw()
            label = tk.Label(root, text="Brightness")
            self.assertEqual(label.cget("text"), "Parlaklık")
            label.configure(text="Connected to 2 lights")
            self.assertEqual(label.cget("text"), "Bağlı: 2 ışık")
            menu = tk.Menu(root, tearoff=0)
            menu.add_command(label="Quit")
            self.assertEqual(menu.entrycget(0, "label"), "Çıkış")
            root.title("Mi Bulb settings")
            self.assertEqual(root.title(), "Mi Bulb ayarları")
            root.destroy()
        finally:
            i18n.set_language("en")


if __name__ == "__main__":
    unittest.main()
