r"""Zen 3 / Zen 4 / Zen 5 masaüstü işlemci algılama ve ön ayarlar.

Windows'ta CPU kimliği kayıt defterinden okunur (dil bağımsız):
  HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0  ->  Identifier = "AMD64 Family 25 Model 97 Stepping 2"
Aile/model -> nesil eşlemesi (ondalık): Family 25 (0x19) Zen 3/Zen 4, Family 26 (0x1A) Zen 5.

Ön ayar yalnızca config.toml'da AÇIKÇA yazılmamış anahtarlara uygulanır. Kullanıcının yazdığı değer korunur,
yalnızca nesil için imkânsız olanlar (ör. Zen 3'te AVX-512 ikilisi) hata verir ya da sınıra çekilir.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .config import Config, ConfigError
from .hw import ToolError
from .i18n import tr

# floor_max: CoreCycler 'Minimum' değerleri: Ryzen 5000 için -30, Ryzen 7000 ve üstü için -50.
GENERATIONS = {
    "zen3": {"label": "Zen 3 (Ryzen 5000)", "mode": "19-ZN2 ~ Kagari", "floor": 30, "floor_max": 30, "start_co": 10},
    "zen4": {"label": "Zen 4 (Ryzen 7000)", "mode": "22-ZN4 ~ Kizuna", "floor": 50, "floor_max": 50, "start_co": 15},
    "zen5": {"label": "Zen 5 (Ryzen 9000)", "mode": "24-ZN5 ~ Komari", "floor": 50, "floor_max": 50, "start_co": 20},
}
AVX512_MODES = {"17-SKX ~ Kotori", "18-CNL ~ Shinoa", "22-ZN4 ~ Kizuna", "24-ZN5 ~ Komari"}


def parse_identifier(identifier: str) -> Optional[tuple]:
    m = re.search(r"Family\s+(\d+)\s+Model\s+(\d+)", identifier or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def classify(family: int, model: int) -> Optional[str]:
    """Aile/model (ondalık) -> nesil. Sunucu (EPYC) ve mobil Zen 5 (Strix) bilerek dışarıda."""
    if family == 25:
        if 0x20 <= model <= 0x2F or 0x40 <= model <= 0x5F:   # Vermeer (0x21), Rembrandt-R, Cezanne (0x50)
            return "zen3"
        if 0x60 <= model <= 0x7F:                              # Raphael / Dragon Range (0x61), Phoenix
            return "zen4"
    if family == 26 and 0x40 <= model <= 0x4F:                 # Granite Ridge (0x44)
        return "zen5"
    return None


def read_cpu_identity() -> tuple:
    """(identifier, ad). Yalnızca Windows."""
    import winreg
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
    try:
        ident = winreg.QueryValueEx(key, "Identifier")[0]
        name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
    finally:
        winreg.CloseKey(key)
    return str(ident), str(name).strip()


def apply_preset(cfg: Config, gen: str, log: Callable[[str], None] = print) -> None:
    p = GENERATIONS[gen]
    explicit = getattr(cfg, "_explicit", set())
    for key in ("mode", "floor", "start_co"):
        if key not in explicit:
            setattr(cfg, key, p[key])
    if cfg.floor > p["floor_max"]:
        log(tr("UYARI: floor={floor} bu nesil için fazla; {label} en fazla -{max} destekler. floor {max} yapıldı.",
               floor=cfg.floor, label=p["label"], max=p["floor_max"]))
        cfg.floor = p["floor_max"]
    if cfg.start_co > cfg.floor:
        cfg.start_co = cfg.floor
    if gen == "zen3":
        for key in ("mode", "lowload_mode"):
            if getattr(cfg, key) in AVX512_MODES:
                raise ConfigError(tr("{key} = {value!r} AVX-512 kullanır; Zen 3 desteklemez. "
                                     "config.toml'daki bu satırı silin (nesle göre otomatik seçilir).",
                                     key=key, value=getattr(cfg, key)))
    elif cfg.mode in AVX512_MODES and cfg.mode != p["mode"]:
        log(tr("UYARI: mode = {mode!r} bu nesil için önerilen ikili değil ({rec!r}).", mode=cfg.mode, rec=p["mode"]))
    cfg.validate()


def resolve_generation(cfg: Config, log: Callable[[str], None] = print, identity: Optional[tuple] = None) -> str:
    """Nesli belirler (generation = auto ise algılar), ön ayarı uygular. Aynı cfg için bir kez çalışır."""
    done = getattr(cfg, "_gen_resolved", None)
    if done:
        return done
    gen = (cfg.generation or "auto").lower()
    name = ""
    if gen == "auto":
        ident, name = identity or read_cpu_identity()
        if "5800X3D" in name.upper().replace(" ", ""):
            raise ToolError(tr("Ryzen 7 5800X3D'de Curve Optimizer kilitlidir; bu araç bu işlemcide çalışmaz."))
        fm = parse_identifier(ident)
        gen = classify(*fm) if fm else None
        if gen is None:
            raise ToolError(tr("İşlemci tanınmadı ({name!r}; {ident!r}). Desteklenenler: Ryzen 5000/7000/9000 masaüstü. "
                               "Biliyorsanız config.toml dosyasına şunlardan birini yazın: "
                               "generation = \"zen3\" / \"zen4\" / \"zen5\".", name=name, ident=ident))
    elif gen not in GENERATIONS:
        raise ConfigError(tr("generation 'auto', 'zen3', 'zen4' veya 'zen5' olmalı, '{value}' verildi",
                             value=cfg.generation))
    apply_preset(cfg, gen, log)
    log(tr("İşlemci: {name} -> {label}; mode={mode}, floor={floor}, start_co={start}",
           name=name or tr("(config ile seçildi)"), label=GENERATIONS[gen]["label"], mode=cfg.mode,
           floor=cfg.floor, start=cfg.start_co))
    cfg._gen_resolved = gen
    return gen
