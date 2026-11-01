"""Arayüz dili: Türkçe ve İngilizce.

Kaynak metinler Türkçedir. `tr("metin {x}", x=1)` Türkçe seçiliyse metni olduğu gibi (biçimlendirerek) verir;
İngilizce seçiliyse `lang_en.EN` sözlüğünden karşılığını alır (yoksa Türkçesini verir; testler hiçbirinin
eksik olmadığını denetler).

Dil seçimi (öncelik sırasıyla):
  1. komut satırı  --lang tr|en
  2. ortam değişkeni  PBO_LANG=tr|en
  3. config.toml  [ui] language = "auto" | "tr" | "en"
  4. sistem dili (auto): Windows kullanıcı yerel ayarı Türkçe ise tr, değilse en

Yalnızca standart kütüphane kullanır (kurulum yardımcısı psutil kurulmadan önce de çalışır).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

SUPPORTED = ("tr", "en")
SETTINGS = ("auto",) + SUPPORTED
ENV_VAR = "PBO_LANG"

_lang = "tr"


def set_language(code: str) -> None:
    global _lang
    if code not in SUPPORTED:
        raise ValueError(f"language must be one of {SUPPORTED}, got {code!r}")
    _lang = code


def get_language() -> str:
    return _lang


def mark(text: str) -> str:
    """Çeviri anahtarı olarak işaretler, ama şimdi çevirmez (modül düzeyi sabitler için; çeviri gösterirken `tr`)."""
    return text


def tr(text: str, **values) -> str:
    if _lang != "tr":
        from .lang_en import EN
        text = EN.get(text, text)
    return text.format(**values) if values else text


def _from_locale_name(name: str) -> str:
    return "tr" if name.strip().lower().replace("_", "-").startswith("tr") else "en"


LANG_TURKISH = 0x1F          # Windows birincil dil kimliği (LANGID & 0x3FF)


def system_language() -> str:
    """Windows'ta: kullanıcının ekran dili Türkçeyse 'tr'; değilse bölgesel ayar (ör. 'tr-TR') Türkçeyse 'tr'.
    Windows dışında LC_ALL/LC_MESSAGES/LANG. Hiçbiri Türkçe değilse veya bulunamazsa 'en'."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            if (kernel32.GetUserDefaultUILanguage() & 0x3FF) == LANG_TURKISH:
                return "tr"
            buf = ctypes.create_unicode_buffer(85)
            if kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                return _from_locale_name(buf.value)
        except Exception:  # noqa: BLE001
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val:
            return _from_locale_name(val)
    return "en"


def resolve(setting: Optional[str]) -> str:
    """'auto' / boş -> sistem dili; 'tr' / 'en' olduğu gibi. Geçersiz değer ValueError verir."""
    s = (setting or "auto").strip().lower()
    if s == "auto":
        return system_language()
    if s not in SUPPORTED:
        raise ValueError(f"language must be one of {SETTINGS}, got {setting!r}")
    return s


def peek_config_language(path: Optional[str]) -> Optional[str]:
    """config.toml'daki `language` değerini sessizce okur (bozuk/eksik dosyada None). Dil, ayarların tamamı
    doğrulanmadan önce, hata mesajlarını bile doğru dilde göstermek için gerekir."""
    if not path:
        return None
    try:
        import tomllib
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(raw.get("language"), str):
        return raw["language"]
    for content in raw.values():
        if isinstance(content, dict) and isinstance(content.get("language"), str):
            return content["language"]
    return None


def cli_language(argv) -> Optional[str]:
    """argv içinde `--lang X` veya `--lang=X` arar (argparse çalışmadan önce, --help metni için)."""
    args = list(argv or [])
    for i, a in enumerate(args):
        if a == "--lang" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def init(argv=None, config_path: Optional[str] = None) -> str:
    """Dili seçer ve ayarlar. Geçersiz bir değer sessizce atlanır (bir alt öncelik denenir); doğrulama
    `Config.validate` ve argparse'ta yapılır."""
    for candidate in (cli_language(argv), os.environ.get(ENV_VAR), peek_config_language(config_path)):
        if candidate:
            try:
                code = resolve(candidate)
            except ValueError:
                continue
            set_language(code)
            return code
    code = system_language()
    set_language(code)
    return code


def default_config_path() -> Optional[str]:
    return "config.toml" if Path("config.toml").exists() else None
