"""Sahte işlemci. Donanım olmadan algoritmayı, çökme/devam akışını ve raporu denemek için.

Model: her çekirdeğin gizli bir 'limit' değeri var (a = -CO cinsinden).
  a <= limit - band : her zaman geçer
  limit - band < a <= limit : aralıklı hata (uzun test daha olası yakalar)
  a > limit : hata verir; crash_prob olasılıkla sistem çöker (yeniden başlatma simüle edilir)
Tüm-çekirdek testinde etkin limit allcore_penalty kadar düşer.
"""

from __future__ import annotations

import random
from typing import Optional

from .config import Config
from .hw import Hardware, StressResult, ToolError
from .i18n import tr
from .state import StateStore
from .tuner import Halted, Tuner


class SimulatedCrash(BaseException):
    """Gerçek çökmeyi temsil eder: temizlik kodu çalışmaz (hard_crash=True)."""
    hard_crash = True


class SimCPU:
    def __init__(self, limits: list, seed: int = 0, crash_prob: float = 0.5, band: int = 3,
                 flaky_p_per_min: float = 0.15, allcore_penalty: int = 2, smt: bool = True,
                 spurious_crash_prob: float = 0.0, coupling: float = 0.0, cli_max: int = 50,
                 lowload_limits: Optional[list] = None, idle_fail_a: Optional[int] = None,
                 idle_crash_prob: float = 1.0):
        self.limits = list(limits)
        self.lowload_limits = list(lowload_limits) if lowload_limits is not None else list(limits)
        self.idle_fail_a, self.idle_crash_prob = idle_fail_a, idle_crash_prob
        self.n = len(limits)
        self.rng = random.Random(seed)
        self.crash_prob, self.band, self.flaky, self.penalty = crash_prob, band, flaky_p_per_min, allcore_penalty
        self.smt = smt
        self.spurious = spurious_crash_prob
        self.cli_max = cli_max        # CLI'nin kabul ettiği en derin değer; ötesi ToolError
        self.coupling = coupling      # diğer çekirdeklerin ortalama derinliği başına limit kaybı
        self.offsets = [0] * self.n
        self.boot = 1_000_000.0
        self.clock = 0.0
        self.log = []            # (kind, core, a, seconds, outcome)
        self.crashes = 0
        self.max_a_applied_with_pass = [0] * self.n

    # donanım olaylarını tetikler
    def reboot(self) -> None:
        self.offsets = [0] * self.n          # BIOS değerlerine (burada 0) dönülür
        self.boot += 600 + self.rng.random() * 60
        self.clock += 90

    # -- Hardware parçaları
    @property
    def smu(self):
        sim = self

        class Smu:
            def get_offsets(self):
                return list(sim.offsets)

            def set_offsets(self, values):
                assert len(values) == sim.n, values
                if any(abs(v) > sim.cli_max for v in values):
                    raise ToolError(tr("sim: CLI {max} üstünü kabul etmiyor: {values}", max=sim.cli_max, values=values))
                sim.offsets = list(values)

        return Smu()

    @property
    def stress(self):
        sim = self

        class Stress:
            def run(self, cpus, seconds, label, profile="heavy"):
                sim.clock += seconds
                if profile == "idle":
                    if sim.idle_fail_a is not None and max(-o for o in sim.offsets) > sim.idle_fail_a:
                        if sim.rng.random() < sim.idle_crash_prob:
                            sim.crashes += 1
                            sim.log.append((label, [], [-o for o in sim.offsets], seconds, "IDLE-CRASH"))
                            raise SimulatedCrash()
                        return StressResult(False, tr("sim: boşta WHEA"), seconds)
                    sim.log.append((label, [], [-o for o in sim.offsets], seconds, "idle-pass"))
                    return StressResult(True, "", seconds)
                limits = sim.lowload_limits if profile == "light" else sim.limits
                if sim.spurious and sim.rng.random() < sim.spurious:
                    sim.crashes += 1
                    sim.log.append((label, [], [], seconds, "SPURIOUS-CRASH"))
                    raise SimulatedCrash()
                if len(cpus) >= sim.n * (2 if sim.smt else 1):
                    cores = list(range(sim.n))
                    penalty = sim.penalty
                else:
                    cores = sorted({c // 2 if sim.smt else c for c in cpus})
                    penalty = 0
                worst, why = None, ""
                for c in cores:
                    others = [-sim.offsets[o] for o in range(sim.n) if o != c]
                    couple = int(sim.coupling * sum(others) / max(1, len(others)))
                    a, lim = -sim.offsets[c], limits[c] - penalty - couple
                    if a > lim:
                        worst, why = ("hard", c), tr("sim: hata (çekirdek {c}, a={a}, limit={lim})", c=c, a=a, lim=lim)
                        break
                    if a > lim - sim.band:
                        p = 1 - (1 - sim.flaky) ** (seconds / 60.0)
                        if sim.rng.random() < p:
                            worst, why = ("soft", c), tr("sim: aralıklı hata (çekirdek {c}, a={a})", c=c, a=a)
                if worst is None:
                    sim.log.append((label, cores, [-sim.offsets[c] for c in cores], seconds, "pass"))
                    for c in cores:
                        sim.max_a_applied_with_pass[c] = max(sim.max_a_applied_with_pass[c], -sim.offsets[c])
                    return StressResult(True, "", seconds)
                if worst[0] == "hard" and sim.rng.random() < sim.crash_prob:
                    sim.crashes += 1
                    sim.log.append((label, cores, [-sim.offsets[c] for c in cores], seconds, "CRASH"))
                    raise SimulatedCrash()
                sim.log.append((label, cores, [-sim.offsets[c] for c in cores], seconds, "fail"))
                return StressResult(False, why, seconds)

        return Stress()

    @property
    def boost(self):
        sim = self

        class Boost:
            def measure(self, cpu):
                c = cpu // 2 if sim.smt else cpu
                return float(5300 - 20 * c + 12 * (-sim.offsets[c]))

        return Boost()

    def hardware(self) -> Hardware:
        return Hardware(smu=self.smu, stress=self.stress, boost=self.boost, n_cores=self.n, smt=self.smt,
                        boot_time=lambda: self.boot, now=lambda: self.clock, sleep=lambda s: None)


def run_with_reboots(cfg: Config, sim: SimCPU, store: StateStore, log=print, max_boots: int = 200,
                     force_on_halt: bool = False) -> Optional[object]:
    """Gerçek hayattaki 'çök -> yeniden başla -> otomatik devam' döngüsünü taklit eder."""
    hw = sim.hardware()
    force = False
    for _ in range(max_boots):
        tuner = Tuner(cfg, hw, store, log=log, force=force)
        force = False
        try:
            return tuner.run()
        except SimulatedCrash:
            log(tr("*** SİSTEM ÇÖKTÜ (simülasyon) -> yeniden başlatılıyor ***"))
            sim.reboot()
        except Halted as e:
            log(tr("DURDURULDU: {e}", e=e))
            if not force_on_halt:
                return None
            force = True        # kullanıcı `run --force` yazmış gibi
    raise RuntimeError(tr("max_boots aşıldı"))
