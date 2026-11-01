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

from .i18n import tr
from .search import CoreSearch, SearchParams

STATE_VERSION = 1

STAGE_BASELINE = "baseline"   # CO 0'da boost ölçümü (isteğe bağlı)
STAGE_SEARCH = "search"
STAGE_VALIDATE = "validate"   # tüm değerler uygulanmışken çekirdek çekirdek doğrulama
STAGE_ALLCORE = "allcore"     # tüm çekirdek yük testi
STAGE_FINAL = "final"         # son boost ölçümü + rapor
STAGE_LOWLOAD = "lowload"   # düşük yük testi (ayrı çalıştırılır, `lowload` komutu)
STAGE_IDLE = "idle"         # boşta bekleme testi
STAGE_DONE = "done"


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
        self.baseline_mhz: dict = {}
        self.final_mhz: dict = {}
        self.started_at = time.time()
        self.notes: list = []
        self.floor_used: Optional[int] = params.floor     # aramanın taban (en derin) değeri
        self.extend: Optional[dict] = None   # {'cores': [...], 'base': {core: a}, 'floor': int}
        self.lowload: Optional[dict] = None  # düşük yük testi durumu (aşağıya bak)

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
            "baseline_mhz": {str(c): v for c, v in self.baseline_mhz.items()},
            "final_mhz": {str(c): v for c, v in self.final_mhz.items()},
            "started_at": self.started_at, "notes": self.notes, "floor_used": self.floor_used,
            "lowload": ({**self.lowload, "initial": {str(c): a for c, a in self.lowload["initial"].items()}}
                        if self.lowload else None),
            "extend": ({"cores": self.extend["cores"], "floor": self.extend["floor"],
                        "base": {str(c): a for c, a in self.extend["base"].items()}} if self.extend else None),
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
        st.baseline_mhz = {int(c): v for c, v in d.get("baseline_mhz", {}).items()}
        st.final_mhz = {int(c): v for c, v in d.get("final_mhz", {}).items()}
        st.started_at = d.get("started_at", time.time())
        st.notes = list(d.get("notes", []))
        st.floor_used = d.get("floor_used")
        if d.get("lowload"):
            ll = dict(d["lowload"])
            ll["initial"] = {int(c): a for c, a in ll["initial"].items()}
            st.lowload = ll
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


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self, params: SearchParams) -> Optional[RunState]:
        if not self.path.exists():
            return None
        with open(self.path, "r", encoding="utf-8") as f:
            return RunState.from_dict(json.load(f), params)

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
