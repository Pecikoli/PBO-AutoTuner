"""Kalıcı durum. Çökme/yeniden başlatma sonrası kaldığı yerden devam etmenin temeli.

Önemli kural: bir test başlamadan ÖNCE `pending` diske yazılır (fsync). Sistem çökerse
`pending` dosyada kalır; bir sonraki açılışta bu seviye "kaldı" sayılır.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .hw import ToolError
from .i18n import tr
from .search import CoreSearch, SearchParams

STATE_VERSION = 1

STAGE_BASELINE = "baseline"   # CO 0'da boost ölçümü (isteğe bağlı)
STAGE_SEARCH = "search"
STAGE_VALIDATE = "validate"   # tüm değerler uygulanmışken çekirdek çekirdek doğrulama
STAGE_ALLCORE = "allcore"     # tüm çekirdek yük testi
STAGE_TRIM = "trim"           # araç sınırına dayanan çekirdeklerde MHz'e göre en sığ eşdeğer CO seçimi
STAGE_FINAL = "final"         # son boost ölçümü + rapor
STAGE_LOWLOAD = "lowload"   # düşük yük testi (ayrı çalıştırılır, `lowload` komutu)
STAGE_IDLE = "idle"         # boşta bekleme testi
STAGE_DONE = "done"

# `--quick`in test sürelerini kısalttığı aşamalar (kırpma, düşük yük ve boşta testi kendi sürelerini kullanır)
QUICK_STAGES = (STAGE_BASELINE, STAGE_SEARCH, STAGE_VALIDATE, STAGE_ALLCORE)


class RunState:
    def __init__(self, n_cores: int, params: SearchParams):
        self.n_cores = n_cores
        self.params = params
        self.stage = STAGE_BASELINE
        self.boot_time: float = 0.0
        self.pending: Optional[dict] = None
        self.consecutive_crashes = 0
        self.unattributed_reboots = 0
        self.clean_exit = True
        self.total_crashes = 0
        self.crash_log: list = []
        self.halted = False
        self.searches = {c: CoreSearch(params=params) for c in range(n_cores)}
        self.final: dict = {}            # core -> a (doğrulama sonrası)
        self.validated: list = []        # doğrulanmış çekirdekler
        self.allcore_rounds = 0
        self.allcore_targeted = 0        # WHEA'daki APIC ID ile çekirdek gösterilerek yapılan (hedefli) geri çekme turları
        # Tüm çekirdek testinde HERKESE uygulanan toplam geri çekme (genel turlar). Bir çekirdeğin sınırı bulunduğunu
        # göstermez: o çekirdek hata vermedi, test genel olarak kaldı.
        self.allcore_blanket = 0
        self.baseline_mhz: dict = {}
        self.final_mhz: dict = {}
        self.started_at = time.time()
        self.notes: list = []
        self.floor_used: Optional[int] = params.floor     # aramanın taban (en derin) değeri
        self.quick = False                   # `run --quick` ile mi başlatıldı? (devam ederken aynı kısa testler kullanılır)
        self.extend: Optional[dict] = None   # {'cores': [...], 'base': {core: a}, 'floor': int}
        self.lowload: Optional[dict] = None  # düşük yük testi durumu (aşağıya bak)
        # Tüm çekirdek testi geri çekilmelere rağmen geçmedi mi? None: test yapılmadı/gerekmedi (eski durum dosyaları)
        self.allcore_ok: Optional[bool] = None
        # MHz'e göre kırpma: {'cores': [...], 'from': {c: a}, 'measured': {c: {a: mhz}}, 'chosen': {c: a},
        #                     'skipped': {c: neden_kodu}}
        self.trim: Optional[dict] = None

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION, "n_cores": self.n_cores, "stage": self.stage,
            "boot_time": self.boot_time, "pending": self.pending,
            "consecutive_crashes": self.consecutive_crashes, "total_crashes": self.total_crashes,
            "unattributed_reboots": self.unattributed_reboots, "clean_exit": self.clean_exit,
            "crash_log": self.crash_log, "halted": self.halted,
            "searches": {str(c): s.to_dict() for c, s in self.searches.items()},
            "final": {str(c): a for c, a in self.final.items()},
            "validated": self.validated, "allcore_rounds": self.allcore_rounds,
            "allcore_targeted": self.allcore_targeted,
            "allcore_blanket": self.allcore_blanket,
            "baseline_mhz": {str(c): v for c, v in self.baseline_mhz.items()},
            "final_mhz": {str(c): v for c, v in self.final_mhz.items()},
            "started_at": self.started_at, "notes": self.notes, "floor_used": self.floor_used,
            "quick": self.quick,
            "lowload": ({**self.lowload, "initial": {str(c): a for c, a in self.lowload["initial"].items()}}
                        if self.lowload else None),
            "extend": ({"cores": self.extend["cores"], "floor": self.extend["floor"],
                        "base": {str(c): a for c, a in self.extend["base"].items()}} if self.extend else None),
            "allcore_ok": self.allcore_ok,
            "trim": _trim_to_json(self.trim),
        }

    @classmethod
    def from_dict(cls, d: dict, params: SearchParams) -> "RunState":
        if d.get("version") != STATE_VERSION:
            raise ValueError(tr("durum dosyası sürümü uyumsuz: {version}", version=d.get("version")))
        st = cls(d["n_cores"], params)
        st.stage = d["stage"]
        st.boot_time = d["boot_time"]
        st.pending = d["pending"]
        st.consecutive_crashes = d["consecutive_crashes"]
        st.total_crashes = d.get("total_crashes", 0)
        st.unattributed_reboots = d.get("unattributed_reboots", 0)
        st.clean_exit = d.get("clean_exit", True)
        st.crash_log = list(d["crash_log"])
        st.halted = d["halted"]
        st.searches = {int(c): CoreSearch.from_dict(s, params) for c, s in d["searches"].items()}
        st.final = {int(c): a for c, a in d["final"].items()}
        st.validated = list(d["validated"])
        st.allcore_rounds = d["allcore_rounds"]
        st.allcore_targeted = d.get("allcore_targeted", 0)
        # eski durum dosyaları: her genel tur varsayılan 2 geri çekmişti
        st.allcore_blanket = d.get("allcore_blanket", st.allcore_rounds * 2)
        st.baseline_mhz = {int(c): v for c, v in d.get("baseline_mhz", {}).items()}
        st.final_mhz = {int(c): v for c, v in d.get("final_mhz", {}).items()}
        st.started_at = d.get("started_at", time.time())
        st.notes = list(d.get("notes", []))
        st.floor_used = d.get("floor_used")
        st.quick = bool(d.get("quick", False))
        if d.get("lowload"):
            ll = dict(d["lowload"])
            ll["initial"] = {int(c): a for c, a in ll["initial"].items()}
            st.lowload = ll
        st.allcore_ok = d.get("allcore_ok")
        st.trim = _trim_from_json(d.get("trim"))
        if d.get("extend"):
            e = d["extend"]
            st.extend = {"cores": list(e["cores"]), "floor": e["floor"],
                         "base": {int(c): a for c, a in e["base"].items()}}
            # Uzatılan çekirdeklerin arama tabanı, config'teki değil uzatma tabanıdır (devam ederken de geçerli)
            for c in st.extend["cores"]:
                st.searches[c].params = replace(params, floor=e["floor"])
        return st

    def note(self, text: str) -> None:
        self.notes.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}")
        self.notes = self.notes[-200:]

    def search_floor(self, core: int) -> int:
        """Bu çekirdeğin aramasında kullanılan taban. Durum dosyasındaki kayıt (`floor_used`) esas alınır: `report`,
        `status`, `share` ve `lowload` hazırlığı nesil ön ayarını uygulamadan yükler; oradaki config tabanı (varsayılan 50)
        Zen 3'te (taban 30) aramanın gerçek tabanı değildir. Eski durum dosyalarında kayıt yoksa config'teki kullanılır."""
        if self.extend and core in self.extend["cores"]:
            return self.extend["floor"]
        return self.floor_used or self.searches[core].params.floor

    def capped_cores(self) -> list:
        """Aramada araç sınırına (floor) kadar HİÇ hata vermeden inen çekirdekler: gerçek sınırları bilinmiyor.
        Onayda ya da sonraki doğrulamada bir hata görüp geri çekilenler (sınırı bulunmuş) buraya girmez.
        `final == floor` yalnızca floor'da onay testi GEÇİLDİYSE mümkündür; bu yüzden not metnine bakılmaz (eski
        durum dosyalarında not Türkçe/farklı olabilir, ör. uzatma sonrası 'CLI sınırı: en fazla -50')."""
        out = []
        for c, cs in sorted(self.searches.items()):
            if cs.final is None or cs.final != self.search_floor(c):
                continue
            was_trimmed = bool(self.trim and c in self.trim["from"])
            # Yalnızca tüm çekirdek testinin herkese uyguladığı geri çekme (allcore_blanket) bu çekirdeğin sınırını
            # göstermez; bundan fazla geri çekilmişse (doğrulama/düşük yük/boşta) bir hata görülmüştür.
            if was_trimmed or self.final.get(c, cs.final) >= cs.final - self.allcore_blanket:
                out.append(c)
        return out


def _trim_to_json(t: Optional[dict]) -> Optional[dict]:
    if not t:
        return None
    return {"cores": list(t["cores"]),
            "from": {str(c): a for c, a in t["from"].items()},
            "measured": {str(c): {str(a): m for a, m in lv.items()} for c, lv in t["measured"].items()},
            "chosen": {str(c): a for c, a in t["chosen"].items()},
            "skipped": {str(c): why for c, why in t["skipped"].items()}}


def _trim_from_json(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return None
    return {"cores": [int(c) for c in d["cores"]],
            "from": {int(c): a for c, a in d["from"].items()},
            "measured": {int(c): {int(a): m for a, m in lv.items()} for c, lv in d["measured"].items()},
            "chosen": {int(c): a for c, a in d["chosen"].items()},
            "skipped": {int(c): why for c, why in d["skipped"].items()}}


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self, params: SearchParams) -> Optional[RunState]:
        if not self.path.exists():
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return RunState.from_dict(json.load(f), params)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
            # Bozuk/yarım JSON (ValueError), eksik alan (KeyError), başka sürüm: ham hata izi yerine ne yapılacağını söyle
            raise ToolError(tr("Durum dosyası okunamadı: {path} ({err}). Dosya bozuk ya da başka bir sürüme ait olabilir. "
                               "`run --fresh` eski dosyayı .bak olarak saklayıp sıfırdan başlar.",
                               path=self.path, err=f"{type(e).__name__}: {e}")) from e

    def save(self, state: RunState) -> None:
        """Atomik yaz: geçici dosya + fsync + replace. Yarım dosya kalmaz."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = json.dumps(state.to_dict(), indent=1)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def delete(self) -> None:
        if self.path.exists():
            self.path.unlink()
