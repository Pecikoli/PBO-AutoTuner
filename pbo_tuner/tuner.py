"""Orkestratör: aşamaları sırayla yürütür, her adımı diske işler, çökmeden sonra devam eder.

Akış
----
baseline : (isteğe bağlı) CO 0'da her çekirdeğin etkin boost frekansını ölç
search   : çekirdek çekirdek arama (iniş -> ikili arama -> onay). Test edilen çekirdek dışındakiler CO 0.
validate : bulunan TÜM değerler aynı anda uygulanmışken her çekirdeği tekrar test et
allcore  : tüm çekirdekler birden yük testi; kalırsa hepsini geri çek
trim     : araç sınırına (-floor) hatasız inen çekirdeklerde MHz'e göre en sığ eşdeğer CO'yu seç
final    : son boost ölçümü, rapor
lowload  : (ayrı komut) çekirdek başına hafif + aralıklı yük
idle     : (ayrı komut) hiç yük yokken bekleme. Çökerse/kalırsa şüpheli çekirdekler geri çekilip tekrar denenir

Güvenlik
--------
* Her testten önce `pending` diske yazılır. Sistem çökerse sonraki açılışta o seviye "kaldı" sayılır.
* CO uygulanmışken yapılan boost ölçümleri (kırpma, son ölçüm) de aynı izi bırakır: hafif yükte çöken çekirdek geri çekilir.
* Her testten sonra (hata dahil) tüm çekirdekler CO 0'a döndürülür.
* Her yazımdan sonra değer geri okunup doğrulanır (hw.smu.set_offsets).
* Üst üste `max_consecutive_crashes` çökmede durur; otomatik devam eden bir çökme döngüsü oluşmaz.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from typing import Callable, Optional

from .config import Config, ConfigError
from .hw import Hardware, StressResult, ToolError
from .i18n import tr
from .search import CoreSearch, PHASE_CONFIRM, SearchParams, Test
from .state import (QUICK_STAGES, RunState, StateStore, STAGE_ALLCORE, STAGE_BASELINE, STAGE_DONE, STAGE_FINAL,
                    STAGE_IDLE, STAGE_LOWLOAD, STAGE_SEARCH, STAGE_TRIM, STAGE_VALIDATE)

BOOT_TIME_TOLERANCE = 30.0    # sn. boot_time() ölçümleri arasında ~1-2 sn oynama olur; gerçek yeniden başlatma >= ~100 sn kayar


class Halted(Exception):
    """Çökme döngüsü koruması devrede. Elle `run --force` gerekir."""


def search_params(cfg: Config) -> SearchParams:
    return SearchParams(floor=cfg.floor, coarse_step=cfg.coarse_step, margin=cfg.margin,
                        confirm_backoff=cfg.confirm_backoff, max_crashes=cfg.max_crashes_per_core,
                        start=cfg.start_co)


def trim_levels(a0: int, step: int, points: int) -> list:
    """Kırpmada ölçülecek CO seviyeleri (a cinsinden, derinden sığa): a0, a0-step, ... (0'ın altına inmez)."""
    out = []
    for i in range(points):
        a = a0 - i * step
        if a < 1:
            break
        out.append(a)
    return out


def choose_trim(measured: dict, tolerance: float) -> Optional[int]:
    """{a: MHz}. En iyi MHz'e `tolerance` içinde ulaşan en SIĞ (en küçük) a. Ölçülemeyen (None) seviyeler yok sayılır.
    İki seviyeden azı ölçüldüyse karar verilemez: None."""
    valid = {a: m for a, m in measured.items() if m}
    if len(valid) < 2:
        return None
    best = max(valid.values())
    return min(a for a, m in valid.items() if m >= best - tolerance)


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
    def _check_core_order(self) -> None:
        """core_order her çekirdeği tam bir kez içermeli. Eksik çekirdek hiç aranmaz (nihai değeri None kalır ve arama
        bitince çöker); fazla/yinelenen numara da hataya yol açar. Çekirdek sayısı ancak burada bilinir."""
        order = list(self.cfg.core_order)
        if not order:
            return
        n = self.hw.n_cores
        if any(isinstance(c, bool) or not isinstance(c, int) for c in order) or sorted(order) != list(range(n)):
            raise ConfigError(tr("core_order {n} çekirdeğin her birini tam bir kez içermeli (0..{last}); verilen: {order}",
                                 n=n, last=n - 1, order=order))

    def startup(self) -> None:
        self._check_core_order()
        params = search_params(self.cfg)
        st = self.store.load(params)
        if st is None:
            st = RunState(self.hw.n_cores, params)
            st.quick = bool(getattr(self.cfg, "_quick", False))
            self.log(tr("Yeni çalışma başlatıldı ({n} çekirdek, SMT={smt}).", n=self.hw.n_cores,
                        smt=tr("açık") if self.hw.smt else tr("kapalı")))
        elif st.n_cores != self.hw.n_cores:
            raise ToolError(tr("Durum dosyası {saved} çekirdek için, sistem {now}. `run --fresh` ile yeniden başlayın.",
                               saved=st.n_cores, now=self.hw.n_cores))
        else:
            self.log(tr("Önceki çalışma bulundu: aşama={stage}, toplam çökme={crashes}.",
                        stage=st.stage, crashes=st.total_crashes))
            if st.extend is None and st.stage in (STAGE_BASELINE, STAGE_SEARCH):
                st.floor_used = params.floor      # arama sürerken config tabanı değiştiyse kayıt da onu izlesin
            if getattr(self.cfg, "_quick", False) and st.stage in QUICK_STAGES:
                st.quick = True                   # normal çalışma `--quick` ile sürdürüldü: otomatik devam da kısa testlerle sürsün
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
        if core is None:      # tüm çekirdek / boşta testi: tek bir çekirdek ya da CO değeri yok ("çekirdek None, CO -0" yazma)
            self.log(tr("!! ÇÖKME tespit edildi: {kind} testi (tüm çekirdekler, nihai CO değerleriyle). Bu test 'kaldı' sayılıyor.",
                        kind=kind))
            st.note(tr("çökme: {kind} (tüm çekirdekler)", kind=kind))
        else:
            self.log(tr("!! ÇÖKME tespit edildi: {kind} testi, çekirdek {core}, CO -{a}. Bu seviye 'kaldı' sayılıyor.",
                        kind=kind, core=core, a=a))
            st.note(tr("çökme: {kind} çekirdek={core} CO=-{a}", kind=kind, core=core, a=a))
        attrib = self._crash_attribution(p)
        if attrib["cores"]:
            self.log(tr("   WHEA kaydı çökmenin kaynağını gösteriyor: çekirdek {cores} (APIC {apic}).",
                        cores=attrib["cores"], apic=attrib["apic"]))
            st.note(tr("çökme kaynağı (WHEA APIC {apic}): çekirdek {cores}", apic=attrib["apic"], cores=attrib["cores"]))
        elif kind == "idle":
            self.log(tr("   Çekirdek belirlenemedi: WHEA kaydı yok (donma-reset olabilir) ya da okunamadı."))
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
            if not self._allcore_targeted(attrib["cores"]):
                self._allcore_backoff()
                st.allcore_rounds += 1
        elif kind == "lowload":
            st.final[core] = max(0, st.final.get(core, a) - cfg.validate_backoff)
        elif kind in ("trim", "final"):
            self._boost_crash_backoff(kind, core, a)
        elif kind == "idle":
            if st.lowload:
                st.lowload["idle_done"], st.lowload["idle_result"] = True, "crash"
                st.lowload["idle_attrib"] = attrib
            if cfg.idle_max_rounds <= 0:      # geri çekme kapalı: eski davranış (yalnızca uyarı)
                st.note(tr("UYARI: boşta beklerken sistem çöktü; CO değerleri boşta kararsız olabilir"))

    def _boost_crash_backoff(self, kind: str, core: int, a: int) -> None:
        """Boost ölçümü (hafif yük) sırasında çökme. Düşük yük testindeki gibi ele alınır: çekirdek, çöken seviyenin
        `validate_backoff` altına geri çekilir. Kırpma ölçümüyse çekirdek kırpmadan çıkarılır: hafif yükte hata görüldü,
        sınırı artık 'bilinmiyor' değildir. Geri çekilecek yer yoksa (zaten CO 0) ölçüm atlanır; yoksa aynı çökme
        her açılışta yinelenirdi."""
        st, cfg = self.st, self.cfg
        old = st.final.get(core, a)
        new = max(0, min(old, a) - cfg.validate_backoff)
        if kind == "trim" and st.trim:      # her durumda kırpmadan çıkar: aynı seviye bir daha ölçülmesin
            t = st.trim
            t["cores"] = [c for c in t["cores"] if c != core]
            for key in ("from", "measured", "chosen", "skipped"):
                t[key].pop(core, None)
        if new == old:        # CO 0: bu çekirdek geri çekilemez (çökme başka bir nedenden olabilir)
            st.final_mhz[core] = None
            self.log(tr("   Çekirdek {core} zaten CO 0'da; boost ölçümü atlandı.", core=core))
            return
        st.final[core] = new
        st.final_mhz.pop(core, None)
        st.note(tr("UYARI: çekirdek {core} hafif yükte (boost ölçümü, CO -{a}) sistemi çökertti; CO -{new} değerine geri "
                   "çekildi. Bu çekirdek hafif yüke duyarlı: düşük yük testini (`lowload`) çalıştırın.",
                   core=core, a=a, new=new))
        self.log(tr("   Hafif yükte (boost ölçümü) çökme: çekirdek {core} CO -{old} -> -{new}.", core=core, old=old, new=new))

    # ------------------------------------------------------------------ çökme/hata atfı (WHEA -> APIC ID -> çekirdek)
    def _attrib_from_events(self, events: list) -> dict:
        """WHEA CPU olaylarındaki APIC ID'lerden çekirdek bul. Eşleşmeyen APIC ID'ler yok sayılır (tahmin yok)."""
        mapper = self.hw.apic_to_core
        if mapper is None:
            return {"cores": [], "apic": [], "source": "unavailable"}
        apics = sorted({e["apic_id"] for e in events if e.get("apic_id") is not None})
        cores = sorted({c for c in (mapper(a) for a in apics) if c is not None})
        return {"cores": cores, "apic": apics, "source": "whea" if cores else "unknown"}

    def _crash_attribution(self, p: dict) -> dict:
        """Yeniden başlatmadan sonra: çöken testin başladığı andan beri yazılmış WHEA 18/19 olaylarını oku.
        Zen'de boşta 'donma -> reset' olursa Windows yalnızca Kernel-Power 41 yazar (WHEA yok): o zaman
        kaynak 'unknown'. Okunamazsa 'unavailable'. Hiçbir durumda tahmin edilmez."""
        hw = self.hw
        ts = float(p.get("ts") or 0)
        if hw.crash_events is None or hw.apic_to_core is None or ts <= 0:
            return {"cores": [], "apic": [], "source": "unavailable"}
        for _ in range(3):             # olay günlüğü servisi açılışta geç gelebilir
            try:
                return self._attrib_from_events(hw.crash_events(ts))
            except Exception as e:  # noqa: BLE001
                self.log(tr("   (WHEA olayları okunamadı: {e}; tekrar denenecek)", e=e))
                hw.sleep(10)
        return {"cores": [], "apic": [], "source": "unavailable"}

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

    def _boost_under_co(self, kind: str, core: int, a: int, values: list, samples: int = 1) -> Optional[float]:
        """CO değerleri uygulanmışken tek çekirdek boost ölçümü (medyan MHz ya da None). Derin CO en çok hafif yükte
        çöker; bu yüzden `_exec` gibi ölçümden ÖNCE `pending` yazılır ve çökme o çekirdeğe atfedilir
        (`_boost_crash_backoff`). İz olmasaydı aynı ölçüm her açılışta yeniden denenir, araç bunu 'test dışı yeniden
        başlatma' sayıp dururdu. Değerleri sıfırlamak ve sonucu kaydetmek çağıranın işidir."""
        st = self.st
        st.pending = {"kind": kind, "core": core, "a": a, "level": kind, "ts": self.hw.now()}
        st.boot_time = self.hw.boot_time()
        self._save()                       # ÖNCE yaz: çökerse iz kalsın
        try:
            self.hw.smu.set_offsets(values)
            cpu = self.hw.cpus_for_core(core)[0]
            got = [m for m in (self.hw.boost.measure(cpu) for _ in range(samples)) if m]
        except BaseException as e:         # noqa: BLE001
            if getattr(e, "hard_crash", False):   # (yalnızca simülasyon) gerçek çökmede kod zaten durur
                raise
            st.pending = None
            self._save()
            raise
        st.pending = None
        st.consecutive_crashes = 0        # sistem ölçümü çökmeden bitirdi
        st.unattributed_reboots = 0
        return float(statistics.median(got)) if got else None

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

    def _allcore_targeted(self, cores: list) -> bool:
        """Tüm çekirdek testi kalınca/çökünce WHEA'daki APIC ID bir çekirdeği gösteriyorsa YALNIZCA onu geri çek
        (herkesi geri çekmek sağlam çekirdeklerden boşuna MHz alır). Çekirdek belirli değilse, geri çekilecek yeri
        kalmamışsa ya da hedefli tur hakkı bittiyse False döner; çağıran eski davranışa (hepsi) geçer."""
        st, cfg = self.st, self.cfg
        if not cores or st.allcore_targeted >= cfg.allcore_attrib_rounds:
            return False
        ext = st.extend
        moved = []
        for c in cores:
            floor_a = ext["base"][c] if ext and c in ext["cores"] else 0
            if ext and c not in ext["cores"]:
                continue              # uzatmada yalnızca uzatılanlar sorumlu tutulur (önceki yapılandırma testi geçmişti)
            a = st.final.get(c, 0)
            if a > floor_a:
                st.final[c] = max(floor_a, a - cfg.allcore_backoff)
                moved.append((c, a, st.final[c]))
        if not moved:
            return False
        st.allcore_targeted += 1
        text = ", ".join(f"{c}: -{a0} -> -{a1}" for c, a0, a1 in moved)
        st.note(tr("tüm çekirdek testi: WHEA APIC ID'si çekirdeği gösterdi; yalnızca o geri çekildi ({moves})", moves=text))
        self.log(tr("  Tüm çekirdek testi: WHEA APIC ID'si çekirdeği gösteriyor; yalnızca geri çekiliyor: {moves}  "
                    "(hedefli tur {n}/{max})", moves=text, n=st.allcore_targeted, max=cfg.allcore_attrib_rounds))
        return True

    def _allcore_backoff(self) -> str:
        """Tüm çekirdek testi kalınca geri çekilme. Uzatma modunda yalnızca uzatılan çekirdekler sorumlu tutulur
        (uzatmadan önceki yapılandırma bu testi geçmişti); onlar tabana inmişse eski davranış: hepsi."""
        st, cfg = self.st, self.cfg
        st.allcore_blanket += cfg.allcore_backoff
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
                st.allcore_ok = True
                break
            self.log(tr("      -> KALDI ({reason})", reason=res.reason))
            if not self._allcore_targeted(self._attrib_from_events(res.whea)["cores"]):
                what = self._allcore_backoff()
                st.allcore_rounds += 1
                self.log(tr("  {what} ({step})", what=what, step=cfg.allcore_backoff))
            self._save()
        else:
            if any(st.final.values()):
                st.allcore_ok = False
                st.note(tr("UYARI: tüm çekirdek testi geri çekilmelere rağmen geçmedi"))
                self.log(tr("  !! Tüm çekirdek testi geçmedi. RAM/ısı/PSU gibi başka bir kararsızlık kaynağı olabilir."))
        st.stage = STAGE_TRIM
        self._save()

    def _trim_candidates(self) -> list:
        """Araç sınırına hatasız inen ve hâlâ o değerde duran çekirdekler (daha önce kırpılmamış)."""
        st = self.st
        done = set(st.trim["from"]) if st.trim else set()
        return [c for c in st.capped_cores() if c not in done]

    def _stage_trim(self) -> None:
        """Bir çekirdek araç sınırına (-floor) kadar hiç hata vermeden indiyse gerçek sınırı bilinmez; `-floor` yazmak
        'sınırı buldum' demek olur. Burada o çekirdeğin tek çekirdek boost MHz'i birkaç CO seviyesinde ölçülür ve
        en iyi MHz'e bir boost adımı (trim_tolerance_mhz) içinde ulaşan EN SIĞ seviye seçilir. Sığlaştırma testten
        geçmiş bir değeri daha kararlı yapar; yeniden doğrulama gerekmez. Sınırı bulduğunu iddia etmez."""
        st, cfg = self.st, self.cfg
        cands = self._trim_candidates() if cfg.trim_enabled else []
        nxt = STAGE_LOWLOAD if st.lowload else STAGE_FINAL
        if not cands and not (st.trim and any(c not in st.trim["chosen"] and c not in st.trim["skipped"]
                                              for c in st.trim["cores"])):
            st.stage = nxt
            self._save()
            return
        if st.trim is None:
            st.trim = {"cores": [], "from": {}, "measured": {}, "chosen": {}, "skipped": {}}
        for c in cands:
            if c not in st.trim["from"]:
                st.trim["cores"].append(c)
                st.trim["from"][c] = st.final[c]
        self.log(tr("Kırpma: çekirdek {cores} araç sınırına (-{floor}) hatasız indi; gerçek sınırları bilinmiyor. "
                    "MHz'e göre en sığ eşdeğer CO seçiliyor (~{minutes} dk).",
                    cores=st.trim["cores"], floor=cfg.floor,
                    minutes=max(1, len(st.trim["cores"]) * cfg.trim_points * cfg.trim_samples * 8 // 60)))
        try:
            for c in list(st.trim["cores"]):
                if c in st.trim["chosen"] or c in st.trim["skipped"]:
                    continue
                self._trim_one(c)
        finally:
            self._reset_offsets(quiet=True)
        st.stage = nxt
        self._save()

    def _trim_one(self, core: int) -> None:
        st, cfg = self.st, self.cfg
        t = st.trim
        a0 = t["from"][core]
        meas = t["measured"].setdefault(core, {})
        for a in trim_levels(a0, cfg.trim_step, cfg.trim_points):
            if a in meas:
                continue
            values = self._values_final()
            values[core] = -a                 # diğerleri nihai değerlerinde: gerçek kullanıma yakın koşul
            meas[a] = self._boost_under_co("trim", core, a, values, cfg.trim_samples)
            self.log(tr("  çekirdek {core:2d}: CO -{a}: {mhz} MHz", core=core, a=a,
                        mhz=int(meas[a]) if meas[a] else tr("ölçülemedi")))
            self._save()
        pick = choose_trim(meas, cfg.trim_tolerance_mhz)
        if pick is None:
            t["skipped"][core] = "unmeasurable"
            st.note(tr("kırpma: çekirdek {core} ölçülemedi; CO -{a0} bırakıldı (gerçek sınırı bilinmiyor)",
                       core=core, a0=a0))
            self.log(tr("  => Çekirdek {core}: MHz ölçülemedi, CO -{a0} bırakıldı.", core=core, a0=a0))
        else:
            t["chosen"][core] = pick
            st.final[core] = pick
            st.final_mhz[core] = meas[pick]
            if st.lowload:        # kırpma düşük yük testinden ÖNCE çalışır: kırpılmış değer o testin başlangıcıdır,
                st.lowload["initial"][core] = pick      # yoksa rapor kırpmayı "düşük yükte geri çekildi" diye gösterir
            if pick == a0:
                self.log(tr("  => Çekirdek {core}: CO -{a0} MHz'e katkı yapıyor, olduğu gibi bırakıldı.", core=core, a0=a0))
            else:
                st.note(tr("kırpma: çekirdek {core} CO -{a0} -> -{pick} (MHz fark <= {tol})",
                           core=core, a0=a0, pick=pick, tol=cfg.trim_tolerance_mhz))
                self.log(tr("  => Çekirdek {core}: CO -{a0} -> -{pick} (MHz aynı seviyede, daha sığ = daha kararlı).",
                            core=core, a0=a0, pick=pick))
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

    # ------------------------------------------------------------------ boşta testi + geri çekme
    def _idle_suspects(self, attrib: dict) -> tuple:
        """Boşta kararsızlıktan sorumlu tutulacak çekirdekler. (çekirdekler, kaynak)
        1) WHEA'daki APIC ID bir çekirdeği gösteriyorsa yalnızca o (geri çekilebilir olanlar).
        2) Yoksa: en derin CO'lu çekirdekler (en derinin 4 basamak içindekiler; en çok max(2, n/3) tane).
           Çünkü boşta/düşük yükte kararsızlık derin CO'dan çıkar ve hangi çekirdek olduğu bilinemez."""
        st = self.st
        deep = {c: a for c, a in st.final.items() if a > 0}
        named = [c for c in attrib.get("cores", []) if c in deep]
        if named:
            return named, "whea"
        if not deep:
            return [], "deepest"
        ranked = sorted(deep, key=lambda c: (-deep[c], c))
        top = deep[ranked[0]]
        cap = max(2, self.hw.n_cores // 3)
        return [c for c in ranked if deep[c] >= top - 4][:cap], "deepest"

    def _idle_remediate(self) -> bool:
        """Boşta testi çöktü/kaldı. Şüpheli çekirdekleri `idle_backoff` kadar geri çek, bunların düşük yük testini ve
        boşta testini yeniden yaptır (en fazla `idle_max_rounds` tur). True: geri çekildi, yeniden denenmeli."""
        st, cfg, ll = self.st, self.cfg, self.st.lowload
        rounds = ll.get("idle_rounds", 0)
        attrib = ll.get("idle_attrib") or {"cores": [], "apic": [], "source": "unavailable"}
        entry = {"round": rounds + 1, "result": ll["idle_result"], "source": attrib.get("source", "unavailable"),
                 "cores": list(attrib.get("cores", [])), "apic": list(attrib.get("apic", [])),
                 "by": None, "backed_off": []}
        history = ll.setdefault("idle_history", [])
        suspects, by = [], None
        if cfg.idle_max_rounds > 0 and rounds < cfg.idle_max_rounds:
            suspects, by = self._idle_suspects(attrib)
        if not suspects:
            history.append(entry)
            if cfg.idle_max_rounds > 0:
                st.note(tr("UYARI: boşta kararsızlık {n} geri çekme turundan sonra da giderilemedi", n=rounds))
                self.log(tr("  !! Boşta test {n} geri çekme turundan sonra da geçmedi; sonuç DOĞRULANMADI.", n=rounds))
            return False
        moved = []
        for c in suspects:
            a = st.final[c]
            st.final[c] = max(0, a - cfg.idle_backoff)
            moved.append([c, a, st.final[c]])
        entry["by"], entry["backed_off"] = by, moved
        history.append(entry)
        ll["idle_rounds"] = rounds + 1
        ll["cores_done"] = [c for c in ll["cores_done"] if c not in suspects]
        ll["idle_done"], ll["idle_result"], ll["idle_attrib"] = False, None, None
        st.stage = STAGE_LOWLOAD          # geri çekilenlerin düşük yük testi yeniden yapılacak (çökme olursa buradan devam)
        why = (tr("WHEA APIC ID'si çekirdeği gösterdi") if by == "whea"
               else tr("çekirdek belirlenemedi; en derin CO'lular şüpheli"))
        text = ", ".join(f"{c}: -{a0} -> -{a1}" for c, a0, a1 in moved)
        st.note(tr("boşta testi {n}. tur geri çekme ({why}): {moves}", n=rounds + 1, why=why, moves=text))
        self.log(tr("  Boşta test kaldı. {why}; geri çekiliyor: {moves}  (tur {n}/{max})",
                    why=why, moves=text, n=rounds + 1, max=cfg.idle_max_rounds))
        self._save()
        return True

    def _stage_idle(self) -> None:
        """Hiç yük yokken bekler. Boşta kararsızlık nadir ve rastgele olduğu için uzun süre gerekir; sistem çökerse
        devam mantığı bunu yakalar. Kalırsa/çökerse: WHEA APIC ID ile çekirdek bulunabiliyorsa yalnızca o, yoksa en
        derin CO'lu çekirdekler geri çekilir; düşük yük + boşta testi tekrarlanır. Yalnızca geçerse doğrulanmış sayılır."""
        st, cfg = self.st, self.cfg
        ll = st.lowload
        while True:
            if not ll["idle_done"]:
                if ll["idle_seconds"] > 0:
                    self.log(tr("Boşta bekleme testi: {minutes} dk, hiç yük yok, tüm CO değerleri uygulanmış.",
                                minutes=ll["idle_seconds"] // 60))
                    res = self._exec("idle", None, 0, "idle", self._values_final(), [], ll["idle_seconds"], "idle",
                                     profile="idle")
                    ll["idle_done"] = True
                    ll["idle_result"] = "passed" if res.passed else "failed"
                    if res.passed:
                        self.log(tr("      -> GEÇTİ"))
                    else:
                        ll["idle_attrib"] = self._attrib_from_events(res.whea)
                        self.log(tr("      -> KALDI ({reason})", reason=res.reason))
                        if cfg.idle_max_rounds <= 0:
                            st.note(tr("UYARI: boşta bekleme testi kaldı: {reason}", reason=res.reason))
                    self._save()
                else:
                    ll["idle_done"], ll["idle_result"] = True, "skipped"
            if ll["idle_result"] not in ("crash", "failed"):
                break
            if cfg.idle_max_rounds <= 0 or not self._idle_remediate():
                break
            self._stage_lowload()         # yalnızca geri çekilenler yeniden test edilir; sonunda stage = IDLE
        st.stage = STAGE_DONE
        self._save()

    def _stage_final(self) -> None:
        st = self.st
        if self.cfg.measure_boost and any(st.final.values()):
            self.log(tr("Aşama 5/5: nihai değerlerle boost ölçümü."))
            try:
                for c in self.order:
                    if c in st.final_mhz:
                        continue
                    # Değerler her ölçümde yeniden hesaplanır: önceki açılışta çöken çekirdek geri çekilmiş olabilir
                    st.final_mhz[c] = self._boost_under_co("final", c, st.final.get(c, 0), self._values_final())
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
                  (STAGE_TRIM, self._stage_trim), (STAGE_FINAL, self._stage_final), (STAGE_LOWLOAD, self._stage_lowload),
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
                  "idle_seconds": cfg.idle_minutes * 60, "initial": dict(st.final), "idle_rounds": 0,
                  "idle_history": [], "idle_attrib": None}
    # Araç sınırına hatasız inen çekirdekler daha önce kırpılmadıysa (eski çalışma): önce MHz'e göre kırp
    needs_trim = bool(cfg.trim_enabled and st.trim is None and st.capped_cores())
    st.stage = STAGE_TRIM if needs_trim else STAGE_LOWLOAD
    st.halted, st.consecutive_crashes, st.unattributed_reboots = False, 0, 0
    st.note(tr("düşük yük testi başlatıldı: {sec} sn/çekirdek, boşta {idle} dk",
               sec=cfg.lowload_seconds, idle=cfg.idle_minutes))
    store.save(st)
