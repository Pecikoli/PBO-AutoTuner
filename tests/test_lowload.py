"""Düşük yük + boşta testi (lowload)."""
import json

import pytest

from pbo_tuner.config import Config, ConfigError
from pbo_tuner.hw import Pulser, ToolError
from pbo_tuner.report import build_report
from pbo_tuner.sim import SimCPU, run_with_reboots
from pbo_tuner.state import StateStore, STAGE_DONE, STAGE_LOWLOAD
from pbo_tuner.tuner import Tuner, prepare_lowload, search_params


def cfg_for(tmp_path, **kw):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, lowload_seconds=60, idle_minutes=5)
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def finished_run(tmp_path, limits, **sim_kw):
    cfg = cfg_for(tmp_path)
    sim = SimCPU(limits, **sim_kw)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    return cfg, sim, store, st


LIMITS = [48, 44, 40, 36, 30, 28, 26, 24] * 2


def test_all_pass_leaves_values_unchanged(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    before = dict(st0.final)
    prepare_lowload(cfg, store)
    assert store.load(search_params(cfg)).stage == STAGE_LOWLOAD
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.final == before
    assert st.lowload["idle_result"] == "passed" and len(st.lowload["cores_done"]) == 16
    assert sim.offsets == [0] * 16
    text, _ = build_report(st, cfg)
    assert "tüm çekirdekler geçti" in text and "Boşta bekleme testi: geçti" in text


def test_failing_core_is_backed_off_others_untouched(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    before = dict(st0.final)
    weak = 3                                         # düşük yükte limit 20; ağır yükte 36'ydı
    lowload_limits = list(LIMITS)
    lowload_limits[weak] = 20
    sim.lowload_limits = lowload_limits
    prepare_lowload(cfg, store)
    logs = []
    st = run_with_reboots(cfg, sim, store, log=logs.append)
    assert st.final[weak] <= 20 and st.final[weak] >= 18          # 2'şer geri çekildi
    assert all(st.final[c] == before[c] for c in range(16) if c != weak)
    assert any("geri çekildi" in l for l in logs)
    text, _ = build_report(st, cfg)
    assert f"çekirdek {weak}: -{before[weak]} -> -{st.final[weak]}" in text


def test_lowload_uses_light_profile_single_thread_and_idle_profile(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=2, crash_prob=0.0, band=0, allcore_penalty=0)
    prepare_lowload(cfg, store)
    hw = sim.hardware()
    real = sim.stress
    calls = []

    class Spy:
        def run(self, cpus, seconds, label, profile="heavy"):
            calls.append((profile, tuple(cpus), seconds, label))
            return real.run(cpus, seconds, label, profile=profile)

    hw.stress = Spy()
    Tuner(cfg, hw, store, log=lambda s: None).run()
    light = [c for c in calls if c[0] == "light"]
    idle = [c for c in calls if c[0] == "idle"]
    assert len(light) == 16 and all(len(c[1]) == 1 and c[2] == 60 for c in light)
    assert [c[1][0] for c in light] == [2 * i for i in range(16)]          # SMT: ilk iş parçacığı
    assert len(idle) == 1 and idle[0][1] == () and idle[0][2] == 5 * 60
    assert not [c for c in calls if c[0] == "heavy"]


def test_crash_during_lowload_is_recorded_and_resumed(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=3, crash_prob=0.0, band=0, allcore_penalty=0)
    ll = list(LIMITS)
    ll[5] = 16
    sim.lowload_limits, sim.crash_prob = ll, 1.0
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    assert sim.crashes >= 1
    assert st.final[5] <= 16
    assert st.total_crashes >= 1


def test_idle_crash_is_reported_but_values_are_not_changed(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=4, crash_prob=0.0, band=0, allcore_penalty=0)
    before = dict(st0.final)
    sim.idle_fail_a, sim.idle_crash_prob = 40, 1.0           # bazı çekirdekler 40'tan derinde: boşta çöker
    assert max(before.values()) > 40
    prepare_lowload(cfg, store)
    logs = []
    st = run_with_reboots(cfg, sim, store, log=logs.append)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "crash"
    assert st.final == before                                  # çekirdek atfı yapılamaz: otomatik değiştirmez
    assert any("boşta" in n and "UYARI" in n for n in st.notes)
    text, _ = build_report(st, cfg)
    assert "SİSTEM ÇÖKTÜ" in text


def test_idle_minutes_zero_skips_idle(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=5, crash_prob=0.0, band=0, allcore_penalty=0)
    cfg.idle_minutes = 0
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "skipped"
    assert not any(row[0] == "idle" for row in sim.log)


def test_prepare_lowload_requires_finished_run(tmp_path):
    cfg = cfg_for(tmp_path)
    store = StateStore(tmp_path / "state.json")
    with pytest.raises(ToolError):
        prepare_lowload(cfg, store)                            # durum dosyası yok
    sim = SimCPU([30] * 16, crash_prob=0.0)
    run_with_reboots(cfg, sim, store, log=lambda s: None)
    st = store.load(search_params(cfg))
    st.stage = "search"
    store.save(st)
    with pytest.raises(ToolError):
        prepare_lowload(cfg, store)


def test_lowload_state_survives_json_roundtrip(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path, LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    prepare_lowload(cfg, store)
    st = store.load(search_params(cfg))
    assert st.lowload["initial"] == st0.final and st.lowload["seconds"] == 60 and st.lowload["idle_seconds"] == 300
    json.dumps(st.to_dict())                                   # serileştirilebilir


def test_config_validation_for_lowload():
    with pytest.raises(ConfigError):
        Config(lowload_seconds=10).validate()
    with pytest.raises(ConfigError):
        Config(lowload_pulse_on_ms=10).validate()
    with pytest.raises(ConfigError):
        Config(idle_minutes=-1).validate()
    Config(idle_minutes=0).validate()


# --------------------------------------------------------------------- Pulser
class FakeProc:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def suspend(self):
        self.log.append(("suspend", self.name))

    def resume(self):
        self.log.append(("resume", self.name))


def test_pulser_suspends_then_always_resumes_even_if_sleep_fails():
    log = []
    procs = [FakeProc(log, "a"), FakeProc(log, "b")]
    sleeps = []

    def sleeper(sec):
        sleeps.append(sec)
        if len(sleeps) == 2:                                   # "duruyor" beklemesi sırasında hata
            raise RuntimeError("boom")

    p = Pulser(lambda: procs, on_ms=300, off_ms=700, sleep=sleeper)
    with pytest.raises(RuntimeError):
        p.pulse_once()
    assert log == [("suspend", "a"), ("suspend", "b"), ("resume", "a"), ("resume", "b")]


def test_pulser_timing_is_jittered_around_configured_values():
    p = Pulser(lambda: [], on_ms=300, off_ms=700, sleep=lambda s: None)
    vals = [p._jit(300) for _ in range(200)]
    assert min(vals) >= 0.15 and max(vals) <= 0.45 and len(set(vals)) > 50


def test_pulser_skips_processes_that_fail_to_suspend():
    log = []

    class Bad(FakeProc):
        def suspend(self):
            raise OSError("access denied")

    p = Pulser(lambda: [Bad(log, "x"), FakeProc(log, "y")], 100, 100, sleep=lambda s: None)
    p.pulse_once()
    assert log == [("suspend", "y"), ("resume", "y")] and p.cycles == 1


def test_menu_has_lowload_entry_and_command_parses():
    from pbo_tuner import __main__ as cli
    assert any(cmd == ["lowload"] for _, cmd in cli.MENU)
    assert cli.MENU[-1][1] == ["lowload"]                      # önceki numaralar değişmedi (1-10)
