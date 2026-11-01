"""Ayarlar. config.toml içindeki tablolar (paths/search/stress/levels/safety) düzleştirilip
aşağıdaki alanlara eşlenir. Bilinmeyen anahtar hata verir (yazım hatası sessiz geçmesin)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from .i18n import SETTINGS, tr


class ConfigError(Exception):
    pass


@dataclass
class Config:
    # --- ui
    language: str = "auto"            # auto (sistem dili) | tr | en. --lang ve PBO_LANG bunu geçersiz kılar.

    # --- paths
    corecycler_dir: str = ""          # içinde tools/ryzen-smu-cli ve test_programs/y-cruncher olan klasör
    data_dir: str = "data"            # durum, log, rapor burada

    # --- cpu
    generation: str = "auto"          # auto | zen3 | zen4 | zen5  (auto: işlemciden algılanır)
    cores: int = 0                    # 0 = otomatik algıla (fiziksel çekirdek sayısı)
    smt: Optional[bool] = None        # None = otomatik
    core_order: list = field(default_factory=list)   # boş = 0..N-1

    # --- search
    floor: int = 50                   # en negatif CO (mutlak değer). 50 üstü uygulanamaz (ryzen-smu-cli sınırı).
    start_co: int = 20                # ilk test doğrudan bu değerde (daha sığ değerler atlanır). 0 = kapalı
    coarse_step: int = 5
    margin: int = 2
    confirm_backoff: int = 2
    max_crashes_per_core: int = 4
    max_consecutive_crashes: int = 8  # arada tamamlanan hiç test olmadan üst üste bu kadar çökme => dur
    max_unattributed_reboots: int = 3  # test dışında (ör. açılışta) üst üste bu kadar beklenmedik yeniden başlatma => dur
    validate_backoff: int = 2
    allcore_backoff: int = 2
    allcore_max_rounds: int = 4

    # --- stress (y-cruncher)
    mode: str = "24-ZN5 ~ Komari"     # Zen 5 için
    tests: list = field(default_factory=lambda: ["SFTv4", "FFTv4", "N63"])
    seconds_per_test: int = 20
    threads_per_core: int = 1         # SMT açıkken 1: daha yüksek boost, daha sıkı test

    # --- levels (bir "döngü" = tests listesinin bir kez koşması)
    coarse_cycles: int = 1
    fine_cycles: int = 2
    confirm_cycles: int = 5
    validate_cycles: int = 2
    allcore_minutes: int = 10

    # --- düşük yük / boşta testi (lowload komutu)
    lowload_seconds: int = 180        # çekirdek başına süre
    lowload_mode: str = "19-ZN2 ~ Kagari"   # AVX2: AVX-512'den daha hafif, çekirdek daha yüksek boost eder
    lowload_tests: list = field(default_factory=lambda: ["BKT", "BBP", "SNT"])   # hafif testler
    lowload_pulse_on_ms: int = 300    # yük: bu kadar ms çalış...
    lowload_pulse_off_ms: int = 700   # ...bu kadar ms dur (ortalama yük ~%30, sık boşta<->yük geçişi)
    idle_minutes: int = 30            # boşta bekleme testi süresi (0 = atla)

    # --- safety
    isolate_cores: bool = False       # False (önerilen): çekirdekler tur tur, birbirinin değerleriyle test edilir.
                                      # True: test edilen dışındakiler CO 0'da kalır (gerçek kullanımı yansıtmaz!)
    whea_is_failure: bool = True
    cpu_load_check: bool = True
    measure_boost: bool = True
    resume_delay_seconds: int = 60

    # ------------------------------------------------------------------
    def validate(self) -> None:
        if str(self.language).lower() not in SETTINGS:
            raise ConfigError(tr("language 'auto', 'tr' veya 'en' olmalı, '{value}' verildi", value=self.language))
        if not 1 <= self.floor <= 50:
            raise ConfigError(tr("floor 1..50 arasında olmalı (ryzen-smu-cli -50'den derinini uygulamaz)"))
        if not 0 <= self.start_co <= self.floor:
            raise ConfigError(tr("start_co 0..floor arasında olmalı"))
        if self.coarse_step < 1 or self.margin < 0 or self.confirm_backoff < 1:
            raise ConfigError(tr("coarse_step>=1, margin>=0, confirm_backoff>=1 olmalı"))
        if self.threads_per_core not in (1, 2):
            raise ConfigError(tr("threads_per_core 1 veya 2 olmalı"))
        if not self.tests:
            raise ConfigError(tr("tests boş olamaz"))
        for name in ("coarse_cycles", "fine_cycles", "confirm_cycles", "validate_cycles"):
            if getattr(self, name) < 1:
                raise ConfigError(tr("{name} >= 1 olmalı", name=name))
        if self.seconds_per_test < 5:
            raise ConfigError(tr("seconds_per_test >= 5 olmalı"))
        if self.lowload_seconds < 30 or self.idle_minutes < 0:
            raise ConfigError(tr("lowload_seconds >= 30 ve idle_minutes >= 0 olmalı"))
        if self.lowload_pulse_on_ms < 50 or self.lowload_pulse_off_ms < 50 or not self.lowload_tests:
            raise ConfigError(tr("lowload_pulse_*_ms >= 50 ve lowload_tests dolu olmalı"))

    # ------------------------------------------------------------------
    def level_seconds(self, level: str) -> int:
        cycles = {"coarse": self.coarse_cycles, "fine": self.fine_cycles,
                  "confirm": self.confirm_cycles, "validate": self.validate_cycles}[level]
        return cycles * len(self.tests) * self.seconds_per_test

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)


def load_config(path: Optional[str]) -> Config:
    cfg = Config()
    explicit = set()
    if path and Path(path).exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        known = {f.name for f in fields(Config)}
        for table, content in raw.items():
            items = content.items() if isinstance(content, dict) else [(table, content)]
            for key, value in items:
                if key not in known:
                    raise ConfigError(tr("config.toml: bilinmeyen anahtar '{key}'", key=key))
                setattr(cfg, key, value)
                explicit.add(key)
    cfg._explicit = explicit          # ön ayarlar yalnızca burada OLMAYAN anahtarları değiştirir
    cfg.validate()
    return cfg


def quick_preset(cfg: Config) -> Config:
    """Kaba ama hızlı tarama: kısa testler. Sonuç BIOS'a girilmeden önce uzun testle doğrulanmalı."""
    cfg.seconds_per_test = 10
    cfg.coarse_cycles, cfg.fine_cycles, cfg.confirm_cycles = 1, 1, 2
    cfg.validate_cycles, cfg.allcore_minutes = 1, 5
    return cfg
