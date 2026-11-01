"""Orkestratör: aşamaları sırayla yürütür, her adımı diske işler, çökmeden sonra devam eder.

Akış
----
baseline : (isteğe bağlı) CO 0'da her çekirdeğin etkin boost frekansını ölç
search   : çekirdek çekirdek arama (iniş -> ikili arama -> onay). Test edilen çekirdek dışındakiler CO 0.
validate : bulunan TÜM değerler aynı anda uygulanmışken her çekirdeği tekrar test et
allcore  : tüm çekirdekler birden yük testi; kalırsa hepsini geri çek
final    : son boost ölçümü, rapor

Güvenlik
--------
* Her testten önce `pending` diske yazılır. Sistem çökerse sonraki açılışta o seviye "kaldı" sayılır.
* Her testten sonra (hata dahil) tüm çekirdekler CO 0'a döndürülür.
* Her yazımdan sonra değer geri okunup doğrulanır (hw.smu.set_offsets).
* Üst üste `max_consecutive_crashes` çökmede durur; otomatik devam eden bir çökme döngüsü oluşmaz.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional

from .config import Config
from .hw import Hardware, StressResult, ToolError
from .i18n import tr
from .search import CoreSearch, PHASE_CONFIRM, SearchParams, Test
from .state import (RunState, StateStore, STAGE_ALLCORE, STAGE_BASELINE, STAGE_DONE, STAGE_FINAL, STAGE_IDLE,
                    STAGE_LOWLOAD, STAGE_SEARCH, STAGE_VALIDATE)

BOOT_TIME_TOLERANCE = 30.0    # sn. boot_time() ölçümleri arasında ~1-2 sn oynama olur; gerçek yeniden başlatma >= ~100 sn kayar


class Halted(Exception):
    """Çökme döngüsü koruması devrede. Elle `run --force` gerekir."""


def search_params(cfg: Config) -> SearchParams:
    return SearchParams(floor=cfg.floor, coarse_step=cfg.coarse_step, margin=cfg.margin,
                        confirm_backoff=cfg.confirm_backoff, max_crashes=cfg.max_crashes_per_core,
                        start=cfg.start_co)


class Tuner:
    def __init__(self, cfg: Config, hw: Hardware, store: StateStore,
                 log: Callable[[str], None] = print, force: bool = False):
        self.cfg, self.hw, self.store, self.log, self.force = cfg, hw, store, log, force
        self.st: Optional[RunState] = None

    # ------------------------------------------------------------------ yardımcılar
    @property
    def order(self) -> list:
        return list(self.cfg.core_order) or list(range(self.hw.n_cores))

    def zeros(self) -> list:
        return [0] * self.hw.n_cores

    def _reset_offsets(self, quiet: bool = False) -> None:
        try:
            self.hw.smu.set_offsets(self.zeros())
        except Exception as e:  # noqa: BLE001
            self.log(tr("!! CO sıfırlanamadı: {e}", e=e))
            if not quiet:
                raise

    def _save(self) -> None:
        self.store.save(self.st)

    def _values_isolated(self, core: int, a: int) -> list:
        v = self.zeros()
        v[core] = -a
        return v

    def _values_cumulative(self, core: int, a: int) -> list:
        """Birlikte test: diğer çekirdekler kendi bilinen en iyi değerinde (bitenler: nihai, onaydakiler: aday,
        diğerleri: şimdiye kadar geçtikleri en derin değer). Hata/çökme böylece test edilen çekirdeğe atfedilebilir
        (diğerleri kanıtlanmış değerlerde) ama koşul gerçek kullanıma yakındır."""
        v = []
        for c in range(self.hw.n_cores):
            if c == core:
                v.append(-a)
                continue
            cs = self.st.searches[c]
            ext = self.st.extend
            if ext and c not in ext["cores"]:
                cur = ext["base"][c]          # uzatma sırasında diğerleri önceden doğrulanmış nihai değerinde
            elif cs.done:
                cur = cs.final
            elif cs.phase == PHASE_CONFIRM and cs.candidate:
                cur = cs.candidate
            else:
                cur = cs.stable
            v.append(-cur)
        return v

    def _values_final(self) -> list:
        return [-self.st.final.get(c, 0) for c in range(self.hw.n_cores)]

    # ------------------------------------------------------------------ başlangıç
    def startup(self) -> None:
        params = search_params(self.cfg)
        st = self.store.load(params)
        if st is None:
            st = RunState(self.hw.n_cores, params)
            self.log(tr("Yeni çalışma başlatıldı ({n} çekirdek, SMT={smt}).", n=self.hw.n_cores,
                        smt=tr("açık") if self.hw.smt else tr("kapalı")))
        elif st.n_cores != self.hw.n_cores:
            raise ToolError(tr("Durum dosyası {saved} çekirdek için, sistem {now}. `run --fresh` ile yeniden başlayın.",
                               saved=st.n_cores, now=self.hw.n_cores))
        else:
            self.log(tr("Önceki çalışma bulundu: aşama={stage}, toplam çökme={crashes}.",
                        stage=st.stage, crashes=st.total_crashes))
        self.st = st

        if self.force:
            st.halted, st.consecutive_crashes, st.unattributed_reboots = False, 0, 0

        # Yeniden başlatma oldu mu? (boot_time == 0: ilk çalışma)
        rebooted = st.boot_time > 0 and abs(self.hw.boot_time() - st.boot_time) > BOOT_TIME_TOLERANCE
        if st.pending:
            if rebooted:
                self._apply_crash(st.pending)
            else:
                self.log(tr("Önceki çalışma yarıda kesilmiş (yeniden başlatma yok). Aynı seviye tekrar denenecek."))
            st.pending = None
        elif rebooted and not st.clean_exit:
            st.unattributed_reboots += 1
            self.log(tr("!! Test dışında beklenmedik yeniden başlatma ({n}). Araç temiz kapanmamış.",
                        n=st.unattributed_reboots))
            st.note(tr("test dışı beklenmedik yeniden başlatma"))
        st.boot_time = self.hw.boot_time()
        st.clean_exit = False

        # Güvenli taban: BIOS değerlerini bırakma, açıkça sıfırla
        self._reset_offsets()
        self._save()

        why = None
        if st.consecutive_crashes >= self.cfg.max_consecutive_crashes:
            why = tr("Arada hiç test tamamlanmadan üst üste {n} çökme oldu.", n=st.consecutive_crashes)
        elif st.unattributed_reboots >= self.cfg.max_unattributed_reboots:
            why = tr("Test dışında üst üste {n} beklenmedik yeniden başlatma oldu.", n=st.unattributed_reboots)
        if why:
            st.halted = True
            st.clean_exit = True
            self._save()
            raise Halted(tr("{why} Güvenlik için durduruldu. Sistemin kararsızlığı bu araçtan bağımsız bir "
                            "sorundan (RAM/PSU/ısı/BIOS) olabilir. Kontrol edip `run --force` ile devam edin.", why=why))

    def _apply_crash(self, p: dict) -> None:
        st, cfg = self.st, self.cfg
        st.consecutive_crashes += 1
        st.total_crashes += 1
        st.crash_log.append(self.hw.now())
        kind, core, a = p["kind"], p.get("core"), p["a"]
        self.log(tr("!! ÇÖKME tespit edildi: {kind} testi, çekirdek {core}, CO -{a}. Bu seviye 'kaldı' sayılıyor.",
                    kind=kind, core=core, a=a))
        st.note(tr("çökme: {kind} çekirdek={core} CO=-{a}", kind=kind, core=core, a=a))
        if kind == "search":
            cs = st.searches[core]
            nt = cs.next_test()
            if nt is not None and (nt.a, nt.level) == (a, p["level"]):
                cs.record(nt, False, tr("çökme/yeniden başlatma"), crashed=True)
            else:
                self.log(tr("   (arama durumu bu testle uyuşmuyor; yoksayıldı)"))
        elif kind == "validate":
            floor_a = st.extend["base"][core] if st.extend and core in st.extend["cores"] else 0
            st.final[core] = max(floor_a, st.final.get(core, a) - cfg.validate_backoff)
        elif kind == "allcore":
            self._allcore_backoff()
            st.allcore_rounds += 1
        elif kind == "lowload":
            st.final[core] = max(0, st.final.get(core, a) - cfg.validate_backoff)
        elif kind == "idle":
            if st.lowload:
                st.lowload["idle_done"], st.lowload["idle_result"] = True, "crash"
            st.note(tr("UYARI: boşta beklerken sistem çöktü; CO değerleri boşta kararsız olabilir"))

    # ------------------------------------------------------------------ tek test
    def _exec(self, kind: str, core: Optional[int], a: int, level: str, values: list,
              cpus: list, seconds: int, label: str, profile: Optional[str] = None) -> StressResult:
        st = self.st
        st.pending = {"kind": kind, "core": core, "a": a, "level": level, "ts": self.hw.now()}
        st.boot_time = self.hw.boot_time()
        self._save()                       # ÖNCE yaz: çökerse iz kalsın
        try:
            self.hw.smu.set_offsets(values)
            res = (self.hw.stress.run(cpus, seconds, label) if profile is None
                   else self.hw.stress.run(cpus, seconds, label, profile=profile))
        except BaseException as e:         # noqa: BLE001
            if getattr(e, "hard_crash", False):   # (yalnızca simülasyon) gerçek çökmede kod zaten durur
                raise
            self._reset_offsets(quiet=True)
            st.pending = None
            self._save()
            raise
        self._reset_offsets(quiet=True)
        st.pending = None
        st.consecutive_crashes = 0        # sistem testi çökmeden bitirdi (geçse de kalsa da)
        st.unattributed_reboots = 0
        self._save()
        return res

    # ------------------------------------------------------------------ aşamalar
    def _stage_baseline(self) -> None:
        st = self.st
        if self.cfg.measure_boost:
            self.log(tr("Aşama 1/5: CO 0'da etkin boost frekansları ölçülüyor (yaklaşık değer)."))
            for c in self.order:
                if c in st.baseline_mhz:
                    continue
                mhz = self.hw.boost.measure(self.hw.cpus_for_core(c)[0])
                st.baseline_mhz[c] = mhz
                self.log(tr("  çekirdek {c:2d}: {mhz} MHz", c=c, mhz=mhz if mhz else tr("ölçülemedi")))
                self._save()
        st.stage = STAGE_SEARCH
        self._save()

    def _search_one_test(self, core: int, tag: str = "") -> None:
        st, cfg = self.st, self.cfg
        cs = st.searches[core]
        t: Test = cs.next_test()
        secs = cfg.level_seconds(t.level)
        self.log(tr("  çekirdek {core:2d} [{phase}] CO {co:+d}  ({level}, ~{secs} sn){tag}",
                    core=core, phase=cs.phase, co=t.co, level=t.level, secs=secs, tag=tag))
        values = (self._values_isolated(core, t.a) if cfg.isolate_cores
                  else self._values_cumulative(core, t.a))
        res = self._exec("search", core, t.a, t.level, values,
                         self.hw.cpus_for_core(core, cfg.threads_per_core), secs,
                         f"c{core}_a{t.a}_{t.level}")
        was_done = cs.done
        cs.record(t, res.passed, res.reason)
        self._save()
        self.log("      -> " + (tr("GEÇTİ") if res.passed else tr("KALDI: {reason}", reason=res.reason)))
        if cs.done and not was_done:
            self.log(tr("  => Çekirdek {core}: nihai aday CO -{final}", core=core, final=cs.final)
                     + (f"  ({cs.note})" if cs.note else ""))

    def _stage_search(self) -> None:
        st, cfg = self.st, self.cfg
        mode = tr("izole (diğer çekirdekler CO 0)") if cfg.isolate_cores else tr("birlikte (tur tur)")
        self.log(tr("Aşama 2/5: çekirdek başına CO araması, mod: {mode}.", mode=mode))
        if cfg.isolate_cores:
            for core in self.order:
                while not st.searches[core].done:
                    self._search_one_test(core)
        else:
            rnd = 0
            while True:
                active = [c for c in self.order if not st.searches[c].done]
                if not active:
                    break
                rnd += 1
                self.log(tr("--- Tur {rnd}: {n} çekirdek ---", rnd=rnd, n=len(active)))
                for core in active:
                    self._search_one_test(core)
        if st.extend:
            for c in st.extend["cores"]:
                st.final[c] = st.searches[c].final
            st.validated = [c for c in range(self.hw.n_cores) if c not in st.extend["cores"]]
        elif not st.final:
            st.final = {c: st.searches[c].final for c in range(self.hw.n_cores)}
        st.stage = STAGE_VALIDATE
        self._save()

    def _stage_validate(self) -> None:
        st, cfg = self.st, self.cfg
        self.log(tr("Aşama 3/5: tüm değerler uygulanmışken çekirdek çekirdek doğrulama."))
        for core in self.order:
            if core in st.validated:
                continue
            base = st.extend["base"][core] if st.extend and core in st.extend["cores"] else None
            while st.final[core] > 0:
                a = st.final[core]
                if base is not None and a <= base:
                    st.final[core] = base      # taban zaten önceki çalışmada tüm çekirdek testiyle doğrulanmıştı
                    break
                secs = cfg.level_seconds("validate")
                self.log(tr("  çekirdek {core}: CO -{a} doğrulanıyor (~{secs} sn)", core=core, a=a, secs=secs))
                values = self._values_final()
                res = self._exec("validate", core, a, "validate", values,
                                 self.hw.cpus_for_core(core, cfg.threads_per_core), secs,
                                 f"validate_c{core}_a{a}")
                if res.passed:
                    self.log(tr("      -> GEÇTİ"))
                    break
                st.final[core] = max(base or 0, a - cfg.validate_backoff)
                self.log(tr("      -> KALDI ({reason}); CO -{a}'a geri çekildi", reason=res.reason, a=st.final[core]))
                self._save()
            st.validated.append(core)
            self._save()
        st.stage = STAGE_ALLCORE
        self._save()

    def _allcore_backoff(self) -> str:
        """Tüm çekirdek testi kalınca geri çekilme. Uzatma modunda yalnızca uzatılan çekirdekler sorumlu tutulur
        (uzatmadan önceki yapılandırma bu testi geçmişti); onlar tabana inmişse eski davranış: hepsi."""
        st, cfg = self.st, self.cfg
        ext = st.extend
        if ext:
            moved = False
            for c in ext["cores"]:
                base = ext["base"][c]
                if st.final[c] > base:
                    st.final[c] = max(base, st.final[c] - cfg.allcore_backoff)
                    moved = True
            if moved:
                return tr("uzatılan çekirdekler geri çekildi")
        for c in range(self.hw.n_cores):
            st.final[c] = max(0, st.final.get(c, 0) - cfg.allcore_backoff)
        return tr("tüm değerler geri çekildi")

    def _stage_allcore(self) -> None:
        st, cfg = self.st, self.cfg
        self.log(tr("Aşama 4/5: tüm çekirdek birlikte yük testi."))
        max_rounds = cfg.allcore_max_rounds
        if st.extend:
            gap = max((st.final[c] - st.extend["base"][c]) for c in st.extend["cores"])
            max_rounds = max(max_rounds, -(-max(gap, 0) // cfg.allcore_backoff) + 2)
        while st.allcore_rounds < max_rounds and any(st.final.values()):
            secs = cfg.allcore_minutes * 60
            self.log(tr("  tüm çekirdekler, {minutes} dk", minutes=cfg.allcore_minutes))
            res = self._exec("allcore", None, 0, "allcore", self._values_final(),
                             self.hw.all_cpus(), secs, "allcore")
            if res.passed:
                self.log(tr("      -> GEÇTİ"))
                break
            what = self._allcore_backoff()
            st.allcore_rounds += 1
            self.log(tr("      -> KALDI ({reason}); {what} ({step})", reason=res.reason, what=what,
                        step=cfg.allcore_backoff))
            self._save()
        else:
            if any(st.final.values()):
                st.note(tr("UYARI: tüm çekirdek testi geri çekilmelere rağmen geçmedi"))
                self.log(tr("  !! Tüm çekirdek testi geçmedi. RAM/ısı/PSU gibi başka bir kararsızlık kaynağı olabilir."))
        st.stage = STAGE_FINAL
        self._save()

    def _stage_lowload(self) -> None:
        """Tüm CO değerleri uygulanmışken her çekirdeğe hafif + aralıklı yük (sık boşta<->yük geçişi).
        Kalan çekirdek 2 geri çekilip yeniden denenir. Ağır yük testlerinin kaçırdığı kararsızlığı arar."""
        st, cfg = self.st, self.cfg
        ll = st.lowload
        self.log(tr("Düşük yük testi: çekirdek başına ~{sec} sn hafif yük, {on}/{off} ms aralıklı. "
                    "Tüm CO değerleri uygulanmış durumda.", sec=ll["seconds"], on=cfg.lowload_pulse_on_ms,
                    off=cfg.lowload_pulse_off_ms))
        for core in self.order:
            if core in ll["cores_done"]:
                continue
            while st.final[core] > 0:
                a = st.final[core]
                self.log(tr("  çekirdek {core:2d}: CO -{a} (~{sec} sn)", core=core, a=a, sec=ll["seconds"]))
                res = self._exec("lowload", core, a, "lowload", self._values_final(),
                                 self.hw.cpus_for_core(core, 1), ll["seconds"], f"lowload_c{core}_a{a}",
                                 profile="light")
                if res.passed:
                    self.log(tr("      -> GEÇTİ"))
                    break
                st.final[core] = max(0, a - cfg.validate_backoff)
                self.log(tr("      -> KALDI ({reason}); CO -{a}'a geri çekildi", reason=res.reason, a=st.final[core]))
                self._save()
            ll["cores_done"].append(core)
            self._save()
        st.stage = STAGE_IDLE
        self._save()

    def _stage_idle(self) -> None:
        """Hiç yük yokken bekler. Boşta kararsızlık nadir ve rastgele olduğu için uzun süre gerekir;
        sistem çökerse devam mantığı bunu yakalar. Çekirdek atfı yapılamaz: yalnızca raporlanır."""
        st = self.st
        ll = st.lowload
        if not ll["idle_done"] and ll["idle_seconds"] > 0:
            self.log(tr("Boşta bekleme testi: {minutes} dk, hiç yük yok, tüm CO değerleri uygulanmış.",
                        minutes=ll["idle_seconds"] // 60))
            res = self._exec("idle", None, 0, "idle", self._values_final(), [], ll["idle_seconds"], "idle",
                             profile="idle")
            ll["idle_done"] = True
            ll["idle_result"] = "passed" if res.passed else "failed"
            if res.passed:
                self.log(tr("      -> GEÇTİ"))
            else:
                st.note(tr("UYARI: boşta bekleme testi kaldı: {reason}", reason=res.reason))
                self.log(tr("      -> KALDI ({reason})", reason=res.reason))
            self._save()
        elif not ll["idle_done"]:
            ll["idle_done"], ll["idle_result"] = True, "skipped"
        st.stage = STAGE_DONE
        self._save()

    def _stage_final(self) -> None:
        st = self.st
        if self.cfg.measure_boost and any(st.final.values()):
            self.log(tr("Aşama 5/5: nihai değerlerle boost ölçümü."))
            try:
                self.hw.smu.set_offsets(self._values_final())
                for c in self.order:
                    if c in st.final_mhz:
                        continue
                    st.final_mhz[c] = self.hw.boost.measure(self.hw.cpus_for_core(c)[0])
                    self.log(tr("  çekirdek {c:2d}: {mhz} MHz", c=c, mhz=st.final_mhz[c] or tr("ölçülemedi")))
                    self._save()
            finally:
                self._reset_offsets(quiet=True)
        st.stage = STAGE_DONE
        self._save()

    # ------------------------------------------------------------------ ana döngü
    def run(self) -> RunState:
        self.startup()
        stages = [(STAGE_BASELINE, self._stage_baseline), (STAGE_SEARCH, self._stage_search),
                  (STAGE_VALIDATE, self._stage_validate), (STAGE_ALLCORE, self._stage_allcore),
                  (STAGE_FINAL, self._stage_final), (STAGE_LOWLOAD, self._stage_lowload),
                  (STAGE_IDLE, self._stage_idle)]
        try:
            for name, fn in stages:
                order = [n for n, _ in stages]
                if self.st.stage == STAGE_DONE:
                    break
                if order.index(self.st.stage) > order.index(name):
                    continue
                fn()
        except BaseException as e:      # noqa: BLE001
            if getattr(e, "hard_crash", False):   # (yalnızca simülasyon) gerçek çökmede temizlik çalışmaz
                raise
            self._finish_cleanly()
            raise
        self._finish_cleanly()
        return self.st

    def _finish_cleanly(self) -> None:
        self._reset_offsets(quiet=True)
        self.st.clean_exit = True
        self._save()


# ====================================================================== uzatma (extend)
def extension_candidates(st: RunState) -> tuple:
    """(eski_taban, [çekirdekler]): aramada tabana kadar hatasız inip orada onaylanan çekirdekler."""
    if st.extend:
        old_floor = st.extend["floor"]
    elif st.floor_used:
        old_floor = st.floor_used
    else:  # eski durum dosyası: en derin denenen değer
        old_floor = max((-h["co"] for cs in st.searches.values() for h in cs.history), default=0)
    cores = [c for c, cs in st.searches.items() if cs.final is not None and cs.final == old_floor]
    return old_floor, cores


def prepare_extension(cfg: Config, store: StateStore, cores: Optional[list] = None) -> list:
    """Bitmiş bir çalışmada, tabana dayanan çekirdekleri cfg.floor'a kadar yeniden aramaya hazırlar.
    Donanıma dokunmaz; yalnızca durum dosyasını değiştirir. Dönüş: uzatılacak çekirdekler.
    NOT: Menüden/komut satırından artık erişilmez (varsayılan taban zaten 50). Bu işlev ve `RunState.extend`
    yalnızca daha önce başlatılmış bir uzatmanın kaldığı yerden devam edebilmesi (ve testler) içindir."""
    params = search_params(cfg)
    st = store.load(params)
    if st is None or st.stage != STAGE_DONE:
        raise ToolError(tr("Uzatma için önce normal çalışmanın bitmiş olması gerekir (`status` ile bakın)."))
    old_floor, candidates = extension_candidates(st)
    if cfg.floor <= old_floor:
        raise ToolError(tr("Yeni taban ({new}) eskisinden ({old}) büyük olmalı (en fazla 50).",
                           new=cfg.floor, old=old_floor))
    cores = list(cores) if cores else candidates
    bad = [c for c in cores if c not in candidates]
    if bad:
        raise ToolError(tr("Çekirdek(ler) {bad} tabana dayanmıyor; uzatılabilir olanlar: {candidates}",
                           bad=bad, candidates=candidates))
    if not cores:
        raise ToolError(tr("Tabana dayanan çekirdek yok; uzatılacak bir şey yok."))

    st.extend = {"cores": sorted(cores), "floor": cfg.floor,
                 "base": {c: st.final.get(c, 0) for c in range(st.n_cores)}}
    st.floor_used = cfg.floor
    for c in cores:
        ns = CoreSearch(params=replace(params, floor=cfg.floor))
        ns.stable = old_floor            # bu seviye birlikte testte zaten geçmişti
        st.searches[c] = ns
        st.final_mhz.pop(c, None)
    st.stage = STAGE_SEARCH
    st.validated = []
    st.allcore_rounds = 0
    st.halted, st.consecutive_crashes, st.unattributed_reboots = False, 0, 0
    st.note(tr("uzatma: çekirdekler {cores} CO -{old} -> -{new}", cores=sorted(cores), old=old_floor, new=cfg.floor))
    store.save(st)
    return sorted(cores)


# ====================================================================== düşük yük / boşta testi
def prepare_lowload(cfg: Config, store: StateStore) -> None:
    """Bitmiş bir çalışmanın nihai CO değerleri üzerinde düşük yük + boşta testini başlatmaya hazırlar.
    Donanıma dokunmaz; yalnızca durum dosyasını değiştirir."""
    st = store.load(search_params(cfg))
    if st is None or st.stage != STAGE_DONE or not st.final:
        raise ToolError(tr("Düşük yük testi için önce normal çalışmanın bitmiş olması gerekir (`status` ile bakın)."))
    st.lowload = {"cores_done": [], "idle_done": False, "idle_result": None, "seconds": cfg.lowload_seconds,
                  "idle_seconds": cfg.idle_minutes * 60, "initial": dict(st.final)}
    st.stage = STAGE_LOWLOAD
    st.halted, st.consecutive_crashes, st.unattributed_reboots = False, 0, 0
    st.note(tr("düşük yük testi başlatıldı: {sec} sn/çekirdek, boşta {idle} dk",
               sec=cfg.lowload_seconds, idle=cfg.idle_minutes))
    store.save(st)
