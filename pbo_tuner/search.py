"""Çekirdek başına Curve Optimizer (CO) arama mantığı.

Saf mantık: donanıma, dosyaya, zamana dokunmaz. Bu yüzden simülasyonla test edilebilir.

Terimler
--------
a  = "agresiflik" = -CO. a=0 stok (CO 0), a=20 CO -20 demektir.
stable   : bu seviyede (ve daha düşüğünde) testi GEÇTİĞİ bilinen en yüksek a
unstable : testi KALDIĞI bilinen en düşük a (henüz yoksa None)

Aşamalar
--------
descent : 0'dan başlayıp coarse_step'lik adımlarla iner, ilk hatada durur.
          (start > 0 ise ilk adım doğrudan `start` değerine atlar.)
bisect  : [stable, unstable] aralığını ikili aramayla 1'e kadar daraltır.
confirm : aday = stable - margin. Uzun testle doğrular; kalırsa confirm_backoff kadar
          geri çekilip tekrar dener. 0'a ulaşırsa nihai değer 0 (stok) olur.
done    : final belli.

Bir test hata verirse VEYA sistem çökerse (crashed=True) aynı şekilde "kaldı" sayılır.
Her adım ya aralığı daraltır ya adayı küçültür; bu yüzden algoritma her zaman sonlanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

LEVEL_COARSE = "coarse"
LEVEL_FINE = "fine"
LEVEL_CONFIRM = "confirm"

PHASE_DESCENT = "descent"
PHASE_BISECT = "bisect"
PHASE_CONFIRM = "confirm"
PHASE_DONE = "done"


@dataclass
class SearchParams:
    floor: int = 40            # izin verilen en yüksek a (CO -floor). Bunun ötesine inilmez.
    coarse_step: int = 5
    margin: int = 2            # bisect sonrası güvenlik payı
    confirm_backoff: int = 2
    max_crashes: int = 4       # bu kadar çökmeden sonra keşfi bırakıp muhafazakâr değere geç
    start: int = 0             # >0: ilk iniş adımı doğrudan bu değere atlar (bilinen güvenli bölgeyi atla)


@dataclass
class Test:
    a: int
    level: str

    @property
    def co(self) -> int:
        return -self.a


@dataclass
class CoreSearch:
    params: SearchParams = field(default_factory=SearchParams)
    phase: str = PHASE_DESCENT
    stable: int = 0
    unstable: Optional[int] = None
    candidate: Optional[int] = None
    final: Optional[int] = None
    crashes: int = 0
    note: str = ""
    history: list = field(default_factory=list)

    # ------------------------------------------------------------------ sorgu
    def next_test(self) -> Optional[Test]:
        p = self.params
        if self.phase == PHASE_DONE:
            return None
        if self.phase == PHASE_DESCENT:
            step = p.start if (self.stable == 0 and p.start > 0) else p.coarse_step
            return Test(min(self.stable + step, p.floor), LEVEL_COARSE)
        if self.phase == PHASE_BISECT:
            assert self.unstable is not None
            return Test((self.stable + self.unstable) // 2, LEVEL_FINE)
        if self.phase == PHASE_CONFIRM:
            assert self.candidate is not None
            return Test(self.candidate, LEVEL_CONFIRM)
        raise RuntimeError(f"bilinmeyen faz: {self.phase}")

    # ------------------------------------------------------------------ kayıt
    def record(self, test: Test, passed: bool, reason: str = "", crashed: bool = False) -> None:
        """Bir testin sonucunu işle. `test`, next_test()'in döndürdüğü olmalı."""
        p = self.params
        self.history.append({"co": test.co, "level": test.level, "passed": bool(passed),
                             "crashed": bool(crashed), "reason": reason})
        if crashed:
            self.crashes += 1

        if self.phase == PHASE_DESCENT:
            if passed:
                self.stable = test.a
                if self.stable >= p.floor:
                    # Tabana kadar hiç hata yok: sınır bulunamadı, tabanı doğrula.
                    self._to_confirm(self.stable, "floor reached without error")
            else:
                self.unstable = test.a
                self.phase = PHASE_BISECT
                self._maybe_close_bisect()

        elif self.phase == PHASE_BISECT:
            if passed:
                self.stable = test.a
            else:
                self.unstable = test.a
            self._maybe_close_bisect()

        elif self.phase == PHASE_CONFIRM:
            if passed:
                self.final = test.a
                self.phase = PHASE_DONE
            else:
                self.unstable = test.a if self.unstable is None else min(self.unstable, test.a)
                nxt = test.a - p.confirm_backoff
                if nxt <= 0:
                    self.final = 0
                    self.phase = PHASE_DONE
                    self.note = "no stable negative offset found"
                else:
                    self.candidate = nxt

        # Çok fazla çökme: keşfi bırak, bilinen en iyi değerden muhafazakâr adaya geç.
        if self.crashes >= p.max_crashes and self.phase in (PHASE_DESCENT, PHASE_BISECT):
            self._to_confirm(max(0, self.stable - p.margin), "crash limit reached, conservative value")

    # ------------------------------------------------------------------ iç
    def _maybe_close_bisect(self) -> None:
        if self.unstable is not None and self.unstable - self.stable <= 1:
            self._to_confirm(max(0, self.stable - self.params.margin), "")

    def _to_confirm(self, candidate: int, note: str) -> None:
        if note:
            self.note = note
        if candidate <= 0:
            self.final = 0
            self.phase = PHASE_DONE
            if not self.note:
                self.note = "no stable negative offset found"
            return
        self.candidate = candidate
        self.phase = PHASE_CONFIRM

    # ------------------------------------------------------------------ serileştirme
    def to_dict(self) -> dict:
        return {
            "phase": self.phase, "stable": self.stable, "unstable": self.unstable,
            "candidate": self.candidate, "final": self.final, "crashes": self.crashes,
            "note": self.note, "history": self.history,
        }

    @classmethod
    def from_dict(cls, d: dict, params: SearchParams) -> "CoreSearch":
        cs = cls(params=params)
        cs.phase = d["phase"]
        cs.stable = d["stable"]
        cs.unstable = d["unstable"]
        cs.candidate = d["candidate"]
        cs.final = d["final"]
        cs.crashes = d["crashes"]
        cs.note = d.get("note", "")
        cs.history = list(d.get("history", []))
        return cs

    @property
    def done(self) -> bool:
        return self.phase == PHASE_DONE
