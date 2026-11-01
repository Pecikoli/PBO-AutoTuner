"""Orkestratör testleri: sahte işlemci üzerinde tam çalıştırma, çökme enjeksiyonu, devam etme."""
import json
import random

import pytest

from pbo_tuner.config import Config
from pbo_tuner.sim import SimCPU, run_with_reboots, SimulatedCrash
from pbo_tuner.state import StateStore, STAGE_DONE
from pbo_tuner.tuner import Tuner, Halted, search_params


def make_cfg(tmp_path, **kw):
    cfg = Config(data_dir=str(tmp_path), measure_boost=True, allcore_minutes=1)
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def full_run(tmp_path, limits, seed=0, **sim_kw):
    cfg = make_cfg(tmp_path)
    sim = SimCPU(limits, seed=seed, **sim_kw)
    store = StateStore(tmp_path / "state.json")
    logs = []
    st = run_with_reboots(cfg, sim, store, log=logs.append)
    return cfg, sim, store, st, logs


def test_full_run_no_crash_finds_expected_values(tmp_path):
    limits = [10 + 2 * i for i in range(16)]           # 10..40
    cfg, sim, store, st, logs = full_run(tmp_path, limits, crash_prob=0.0, band=0)
    assert st.stage == STAGE_DONE
    for c in range(16):
        # band=0, kesin sınır: nihai = limit - margin (taban 40'ta sınırlı)
        expect = min(40, max(0, limits[c] - cfg.margin)) if limits[c] < 40 else 40
        assert st.final[c] <= limits[c]
        # tüm-çekirdek cezası (2) olduğu için en fazla 2'şer geri çekilmiş olabilir
        assert st.final[c] >= expect - 2 * cfg.allcore_max_rounds
    assert st.total_crashes == 0
    # Boost ölçümü yapılmış
    assert len(st.baseline_mhz) == 16 and len(st.final_mhz) == 16
    # Bitişte CO'lar sıfırlanmış
    assert sim.offsets == [0] * 16


def test_never_exceeds_hard_limit_with_crashes_and_flaky_band(tmp_path):
    rng = random.Random(7)
    for seed in range(8):
        limits = [rng.randint(5, 45) for _ in range(16)]
        d = tmp_path / f"run{seed}"
        d.mkdir()
        cfg, sim, store, st, logs = full_run(d, limits, seed=seed, crash_prob=0.6, band=3)
        assert st is not None, "çökme döngüsü koruması yanlışlıkla devreye girdi"
        assert st.stage == STAGE_DONE
        for c in range(16):
            assert st.final[c] <= limits[c], (seed, c, st.final[c], limits[c])
            assert st.final[c] <= cfg.floor
        # Nihai değerler, geçen testlerde fiilen uygulanmış olmalı (hiç doğrulanmadan verilmesin)
        assert sim.offsets == [0] * 16


def test_crash_is_recorded_as_failure_and_search_converges(tmp_path):
    limits = [20] * 16
    cfg, sim, store, st, logs = full_run(tmp_path, limits, seed=3, crash_prob=1.0, band=0)
    assert st.total_crashes > 0
    assert any("ÇÖKME tespit edildi" in l for l in logs)
    for c in range(16):
        assert st.final[c] <= 20
        assert st.searches[c].crashes >= 1


def test_pending_is_written_before_test_and_cleared_after(tmp_path):
    cfg = make_cfg(tmp_path)
    sim = SimCPU([15] * 16, crash_prob=0.0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    seen = []
    real_run = hw.stress.run

    class Spy:
        def run(self, cpus, seconds, label):
            seen.append(json.loads((tmp_path / "state.json").read_text())["pending"])
            return real_run(cpus, seconds, label)

    hw.stress = Spy()
    Tuner(cfg, hw, store, log=lambda s: None).run()
    assert seen and all(p is not None for p in seen)
    assert json.loads((tmp_path / "state.json").read_text())["pending"] is None


def test_interrupt_without_reboot_does_not_count_as_crash(tmp_path):
    """Araç elle kapatıldı (yeniden başlatma yok): hata sayılmaz, aynı seviye tekrar denenir."""
    cfg = make_cfg(tmp_path)
    sim = SimCPU([15] * 16, crash_prob=0.0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()

    class Boom(Exception):
        pass

    calls = {"n": 0}
    real = hw.stress.run

    class Interrupter:
        def run(self, cpus, seconds, label):
            calls["n"] += 1
            if calls["n"] == 3:
                raise Boom()
            return real(cpus, seconds, label)

    hw.stress = Interrupter()
    with pytest.raises(Boom):
        Tuner(cfg, hw, store, log=lambda s: None).run()
    assert sim.offsets == [0] * 16                     # temizlik çalıştı
    st = store.load(search_params(cfg))
    assert st.pending is None and st.total_crashes == 0

    hw.stress = sim.stress
    st = Tuner(cfg, hw, store, log=lambda s: None).run()
    assert st.stage == STAGE_DONE and st.total_crashes == 0


def test_hard_crash_leaves_pending_and_resume_marks_it_failed(tmp_path):
    cfg = make_cfg(tmp_path)
    sim = SimCPU([10] * 16, crash_prob=1.0, band=0, seed=1)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    with pytest.raises(SimulatedCrash):
        Tuner(cfg, hw, store, log=lambda s: None).run()
    st = store.load(search_params(cfg))
    assert st.pending is not None and st.pending["kind"] == "search"
    pend = dict(st.pending)

    sim.reboot()
    t = Tuner(cfg, hw, store, log=lambda s: None)
    t.startup()
    assert t.st.pending is None
    assert t.st.total_crashes == 1 and t.st.consecutive_crashes == 1
    hist = t.st.searches[pend["core"]].history
    assert hist[-1]["crashed"] is True and hist[-1]["co"] == -pend["a"]


def test_cpu_where_nothing_survives_halts_at_threshold(tmp_path):
    """Hiçbir çekirdek -1'i bile kaldırmıyor ve her hata çökme: 8 çökmede durup kullanıcıya sorar."""
    cfg = make_cfg(tmp_path)
    sim = SimCPU([0] * 16, crash_prob=1.0, band=0, seed=2)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is None
    assert sim.crashes == 8
    assert store.load(search_params(cfg)).halted


def test_breaker_halts_on_systemic_crashes_then_force_continues(tmp_path):
    cfg = make_cfg(tmp_path, max_consecutive_crashes=8)
    sim = SimCPU([30] * 16, crash_prob=0.0, band=0, seed=2, spurious_crash_prob=1.0)  # her test çöküyor
    store = StateStore(tmp_path / "state.json")
    logs = []
    st = run_with_reboots(cfg, sim, store, log=logs.append)
    assert st is None
    assert any("DURDURULDU" in l for l in logs)
    state = store.load(search_params(cfg))
    assert state.halted and state.consecutive_crashes >= 8
    assert sim.crashes == 8                                   # sonsuz döngü yok

    # Kullanıcı sorunu giderdi (spurious=0) ve --force ile devam ediyor
    sim.spurious = 0.0
    st = run_with_reboots(cfg, sim, store, log=logs.append, force_on_halt=True)
    assert st is not None and st.stage == STAGE_DONE
    assert all(st.final[c] <= 30 for c in range(16))


def test_unattributed_reboots_outside_tests_halt(tmp_path):
    """Araç testin dışında (ör. boost ölçerken) çökerse iz kalmaz; üst üste 3 kez olursa durur."""
    cfg = make_cfg(tmp_path)
    sim = SimCPU([20] * 16, crash_prob=0.0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()

    class BadBoost:
        def measure(self, cpu):
            raise SimulatedCrash()

    hw.boost = BadBoost()
    halted = False
    for i in range(6):
        try:
            Tuner(cfg, hw, store, log=lambda s: None).run()
        except SimulatedCrash:
            sim.reboot()
        except Halted:
            halted = True
            break
    assert halted and i == 3          # 3 beklenmedik yeniden başlatmadan sonra 4. açılışta durur
    st = store.load(search_params(cfg))
    assert st.unattributed_reboots >= 3 and st.total_crashes == 0


def test_resume_from_every_stage_gives_same_kind_of_result(tmp_path):
    """Çalışma her adımda kesilip yeniden başlatılsa da bitiyor ve limitleri aşmıyor."""
    cfg = make_cfg(tmp_path)
    limits = [12 + i for i in range(16)]
    sim = SimCPU(limits, crash_prob=0.0, band=0, seed=5)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real = sim.stress

    class Killer:
        n = 0

        def run(self, cpus, seconds, label):
            Killer.n += 1
            if Killer.n % 7 == 0:
                raise SimulatedCrash()        # her 7. testte sert çökme (limit içinde de olsa)
            return real.run(cpus, seconds, label)

    hw.stress = Killer()
    st = None
    for _ in range(300):
        try:
            st = Tuner(cfg, hw, store, log=lambda s: None).run()
            break
        except SimulatedCrash:
            sim.reboot()
        except Halted:
            # sahte çökmeler art arda gelmediği için olmamalı
            raise
    assert st is not None and st.stage == STAGE_DONE
    for c in range(16):
        assert st.final[c] <= limits[c]


def test_isolation_other_cores_are_zero_during_search(tmp_path):
    cfg = make_cfg(tmp_path, measure_boost=False, isolate_cores=True)
    sim = SimCPU([15] * 16, crash_prob=0.0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real = sim.stress
    violations = []

    class Check:
        def run(self, cpus, seconds, label):
            if label.startswith("c"):
                core = cpus[0] // 2
                others = [v for i, v in enumerate(sim.offsets) if i != core]
                if any(others):
                    violations.append((label, list(sim.offsets)))
            return real.run(cpus, seconds, label)

    hw.stress = Check()
    Tuner(cfg, hw, store, log=lambda s: None).run()
    assert violations == []


# ---------------------------------------------------------------- birlikte (tur tur) arama
def test_combined_search_runs_in_rounds_with_all_cores_at_same_level_first(tmp_path):
    cfg = make_cfg(tmp_path, measure_boost=False)           # varsayılan: isolate_cores=False, start_co=20
    sim = SimCPU([30] * 16, crash_prob=0.0, band=0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real = sim.stress
    seen = []

    class Spy:
        def run(self, cpus, seconds, label):
            if label.startswith("c"):
                core = cpus[0] // 2
                seen.append((core, -sim.offsets[core], list(sim.offsets)))
            return real.run(cpus, seconds, label)

    hw.stress = Spy()
    Tuner(cfg, hw, store, log=lambda s: None).run()
    first_round = seen[:16]
    assert [c for c, _, _ in first_round] == list(range(16))     # sıra: 0..15
    assert all(a == cfg.start_co for _, a, _ in first_round)     # herkes önce aynı seviyede (20)
    second_round = seen[16:32]
    assert [c for c, _, _ in second_round] == list(range(16)) and all(a == 25 for _, a, _ in second_round)
    # Birlikte test: ikinci turda test edilen çekirdeğin diğerleri sıfırda değil, kanıtlı değerlerinde
    core5, a5, offs = second_round[5]
    assert offs[5] == -25 and offs[0] == -25 and offs[6] == -cfg.start_co


def test_start_co_validation():
    import pytest as _pt
    from pbo_tuner.config import ConfigError
    cfg = Config(floor=40, start_co=45)
    with _pt.raises(ConfigError):
        cfg.validate()


def test_combined_search_needs_fewer_validation_backoffs_than_isolated_when_cores_interact(tmp_path):
    """Çekirdekler birbirini etkiliyorsa (gerçek donanımda gözlenen), izole arama hepsini tabana taşır ve
    doğrulama aşaması düzeltmek zorunda kalır. Birlikte arama bunu baştan bulur."""
    def run(mode_isolated, seed):
        d = tmp_path / f"{'iso' if mode_isolated else 'comb'}{seed}"
        d.mkdir()
        cfg = make_cfg(d, measure_boost=False, isolate_cores=mode_isolated)
        rng = random.Random(seed)
        limits = [rng.randint(24, 44) for _ in range(16)]
        sim = SimCPU(limits, seed=seed, crash_prob=0.0, band=0, coupling=0.25, allcore_penalty=0)
        store = StateStore(d / "state.json")
        logs = []
        st = run_with_reboots(cfg, sim, store, log=logs.append)
        assert st is not None and st.stage == STAGE_DONE
        backoffs = sum(1 for l in logs if "geri çekildi" in l)
        total_tests = sum(1 for l in logs if "[" in l and "CO" in l)
        return backoffs, st, total_tests

    iso_back = comb_back = 0
    for seed in range(6):
        b_iso, _, _ = run(True, seed)
        b_comb, st, _ = run(False, seed)
        iso_back += b_iso
        comb_back += b_comb
    assert comb_back < iso_back, (comb_back, iso_back)


def test_combined_search_crash_resume_roundtrip(tmp_path):
    cfg = make_cfg(tmp_path, measure_boost=False)
    limits = [20 + i for i in range(16)]
    sim = SimCPU(limits, seed=11, crash_prob=0.7, band=2, coupling=0.2)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    for c in range(16):
        assert st.final[c] <= limits[c]
