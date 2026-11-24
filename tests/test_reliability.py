"""Dürüst/kararlı sonuç: WHEA APIC ID ile çekirdek atfı, boşta + tüm çekirdek testinde hedefli geri çekme,
boşta geri çekme döngüsü, MHz'e göre kırpma, rapor hükmü ve durum dosyası uyumluluğu."""
import json

import pytest

from pbo_tuner import __main__ as cli
from pbo_tuner.config import Config, ConfigError
from pbo_tuner.hw import make_apic_to_core, make_cpu_to_apic
from pbo_tuner.report import NOT_VERIFIED, PARTIAL, VERIFIED, build_report, verdict
from pbo_tuner.sim import SimCPU, run_with_reboots
from pbo_tuner.state import RunState, StateStore, STAGE_DONE, STAGE_LOWLOAD, STAGE_TRIM
from pbo_tuner.tuner import Tuner, choose_trim, prepare_lowload, search_params, trim_levels

LIMITS = [48, 44, 40, 36, 30, 28, 26, 24] * 2


def cfg_for(tmp_path, **kw):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, lowload_seconds=60, idle_minutes=120)
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def finished_run(tmp_path, limits=LIMITS, cfg=None, **sim_kw):
    cfg = cfg or cfg_for(tmp_path)
    sim_kw.setdefault("crash_prob", 0.0)
    sim_kw.setdefault("band", 0)
    sim_kw.setdefault("allcore_penalty", 0)
    sim_kw.setdefault("seed", 1)
    sim = SimCPU(limits, **sim_kw)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    return cfg, sim, store, st


# ----------------------------------------------------------------------------- APIC -> çekirdek
@pytest.mark.parametrize("n,smt", [(16, True), (16, False), (12, True), (12, False), (8, True), (6, True), (8, False)])
def test_apic_to_core_is_inverse_of_cpu_to_apic(n, smt):
    fwd, inv = make_cpu_to_apic(n, smt), make_apic_to_core(n, smt)
    for core in range(n):
        cpus = [2 * core, 2 * core + 1] if smt else [core]
        for cpu in cpus:
            assert inv(fwd(cpu)) == core


def test_apic_to_core_returns_none_for_gaps_and_out_of_range():
    inv12 = make_apic_to_core(12, True)          # 6+6: APIC 12..15 boşluk
    assert inv12(12) is None and inv12(15) is None and inv12(16) == 6
    assert make_apic_to_core(16, True)(64) is None
    assert make_apic_to_core(8, False)(8) is None


# ----------------------------------------------------------------------------- boşta: çekirdek belli
def test_idle_crash_with_whea_backs_off_only_the_named_core(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    before = dict(st0.final)
    weak = 5
    sim.idle_limits = [99] * 16
    sim.idle_limits[weak] = before[weak] - 2          # 2 geri çekilince geçer
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "passed"
    assert st.final[weak] == before[weak] - 2
    assert all(st.final[c] == before[c] for c in range(16) if c != weak)      # diğerlerine dokunulmadı
    h = st.lowload["idle_history"]
    assert len(h) == 1 and h[0]["by"] == "whea" and h[0]["cores"] == [weak] and h[0]["result"] == "crash"
    assert h[0]["backed_off"] == [[weak, before[weak], before[weak] - 2]]
    assert st.lowload["idle_rounds"] == 1 and sim.crashes == 1
    assert verdict(st) == (VERIFIED, [])
    text, data = build_report(st, cfg)
    assert text.splitlines()[1].startswith("SONUÇ: DOĞRULANDI") and data["verdict"] == VERIFIED
    assert f"{weak}: -{before[weak]} -> -{before[weak] - 2}" in text


def test_idle_failure_without_crash_also_uses_whea_events(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    before = dict(st0.final)
    sim.idle_limits = [99] * 16
    sim.idle_limits[2] = before[2] - 2
    sim.idle_crash_prob = 0.0                          # çökmeden, yalnızca WHEA ile "kaldı"
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.lowload["idle_result"] == "passed" and sim.crashes == 0
    assert st.final[2] == before[2] - 2 and st.lowload["idle_history"][0]["by"] == "whea"
    assert st.lowload["idle_history"][0]["result"] == "failed"


# ----------------------------------------------------------------------------- boşta: çekirdek bilinmiyor
def test_idle_crash_without_whea_backs_off_deepest_cores(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    before = dict(st0.final)
    top = max(before.values())
    sim.whea_visible = False                           # donma-reset: yalnızca Kernel-Power 41, WHEA yok
    sim.idle_fail_a = top - 2
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.lowload["idle_result"] == "passed" and st.lowload["idle_rounds"] == 1
    h = st.lowload["idle_history"][0]
    assert h["by"] == "deepest" and h["source"] == "unknown"
    moved = {c for c, a0, a1 in h["backed_off"]}
    assert moved and all(before[c] >= top - 4 for c in moved)                  # yalnızca en derinler
    assert len(moved) <= max(2, 16 // 3)
    assert all(st.final[c] == before[c] for c in range(16) if c not in moved)
    assert "çekirdek belirlenemedi" in build_report(st, cfg)[0]


def test_idle_remediation_gives_up_after_max_rounds_and_is_not_verified(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    sim.whea_visible = False
    sim.idle_fail_a = 5                                # hiçbir 2'lik geri çekme yetmez
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "crash"
    assert st.lowload["idle_rounds"] == cfg.idle_max_rounds == 3
    assert sim.crashes == 4                            # ilk + 3 yeniden deneme
    v, reasons = verdict(st)
    assert v == NOT_VERIFIED and any("idle" in r for r in reasons)
    text, data = build_report(st, cfg)
    assert "SONUÇ: DOĞRULANMADI" in text and "BIOS'a GİRMEYİN" in text
    assert data["verdict"] == NOT_VERIFIED
    assert any("giderilemedi" in n for n in st.notes)


def test_crash_during_retried_lowload_resumes_and_backs_off_further(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    before = dict(st0.final)
    weak = 6
    sim.idle_limits = [99] * 16
    sim.idle_limits[weak] = before[weak] - 2
    ll = list(LIMITS)
    ll[weak] = before[weak] - 3                        # idle geri çekmesinden (-2) sonra hafif yükte hâlâ kalır
    sim.lowload_limits, sim.crash_prob = ll, 1.0
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "passed"
    assert st.final[weak] == before[weak] - 4
    assert sim.crashes == 2                            # biri boşta, biri yeniden denenen düşük yükte
    assert verdict(st)[0] == VERIFIED


def test_idle_remediation_can_be_disabled(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    cfg.idle_max_rounds = 0
    sim.idle_limits = [99] * 16
    sim.idle_limits[1] = st0.final[1] - 2
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.final == st0.final and st.lowload["idle_result"] == "crash"
    assert verdict(st)[0] == NOT_VERIFIED


# ----------------------------------------------------------------------------- WHEA okunamazsa
def test_crash_attribution_survives_unreadable_event_log(tmp_path):
    cfg = cfg_for(tmp_path)
    sim = SimCPU(LIMITS)
    hw = sim.hardware()
    calls = []

    def broken(ts):
        calls.append(ts)
        raise OSError("wevtutil yok")

    hw.crash_events = broken
    t = Tuner(cfg, hw, StateStore(tmp_path / "s.json"), log=lambda s: None)
    assert t._crash_attribution({"ts": 5.0}) == {"cores": [], "apic": [], "source": "unavailable"}
    assert len(calls) == 3                              # 3 deneme, sonra vazgeç (tahmin yok)
    hw.crash_events = None
    assert t._crash_attribution({"ts": 5.0})["source"] == "unavailable"


def test_unmapped_apic_ids_are_never_guessed(tmp_path):
    cfg = cfg_for(tmp_path)
    sim = SimCPU([30] * 12)
    hw = sim.hardware()
    t = Tuner(cfg, hw, StateStore(tmp_path / "s.json"), log=lambda s: None)
    assert t._attrib_from_events([{"apic_id": 13}, {"apic_id": None}])["cores"] == []      # 6+6 boşluğu
    a = t._attrib_from_events([{"apic_id": 16}, {"apic_id": 17}])
    assert a["cores"] == [6] and a["source"] == "whea"


# ----------------------------------------------------------------------------- tüm çekirdek testi: hedefli geri çekme
def allcore_cfg(tmp_path, **kw):
    return cfg_for(tmp_path, idle_minutes=0, **kw)


def test_allcore_crash_with_whea_backs_off_only_the_named_core(tmp_path):
    cfg = allcore_cfg(tmp_path)
    allcore = [99] * 16
    allcore[7] = 42                                    # çekirdek 7 yalnızca tüm çekirdek yükünde zayıf (arama sonucu: 46)
    sim = SimCPU([48] * 16, seed=1, crash_prob=1.0, band=0, allcore_penalty=1, allcore_limits=allcore)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE and st.allcore_ok is True
    assert st.final[7] == 42 and all(st.final[c] == 46 for c in range(16) if c != 7)        # yalnızca 7 geri çekildi
    assert st.allcore_targeted == 2 and st.allcore_rounds == 0
    assert sum(1 for row in sim.log if row[0] == "allcore" and row[4] == "CRASH") == 2     # tüm çekirdekte 2 çökme
    text = build_report(st, cfg)[0]
    assert "2 hedefli tur" in text and "genel tur" not in text          # hiç genel tur yok: söylenmez


def test_allcore_failure_without_whea_backs_off_everyone_as_before(tmp_path):
    cfg = allcore_cfg(tmp_path)
    allcore = [99] * 16
    allcore[7] = 42
    sim = SimCPU([48] * 16, seed=1, crash_prob=1.0, band=0, allcore_penalty=1, allcore_limits=allcore,
                 whea_visible=False)                   # donma-reset: kaynak bilinmiyor
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.allcore_targeted == 0 and st.allcore_rounds >= 1
    assert all(st.final[c] < 46 for c in range(16))    # tüm çekirdekler geri çekildi


def test_allcore_targeted_rounds_are_capped_then_everyone_backs_off(tmp_path):
    cfg = allcore_cfg(tmp_path, allcore_attrib_rounds=1)
    allcore = [99] * 16
    allcore[7] = 40                                    # tek çekirdek 3 tur ister; hedefli hak 1
    sim = SimCPU([48] * 16, seed=1, crash_prob=1.0, band=0, allcore_penalty=1, allcore_limits=allcore)
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=lambda s: None)
    assert st.allcore_targeted == 1 and st.allcore_rounds >= 1
    assert st.final[7] <= 40 and st.final[0] < 46


def test_allcore_targeting_can_be_disabled(tmp_path):
    cfg = allcore_cfg(tmp_path, allcore_attrib_rounds=0)
    allcore = [99] * 16
    allcore[7] = 42
    sim = SimCPU([48] * 16, seed=1, crash_prob=1.0, band=0, allcore_penalty=1, allcore_limits=allcore)
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=lambda s: None)
    assert st.allcore_targeted == 0 and st.allcore_rounds >= 1


def test_whea_named_core_with_nothing_left_to_back_off_falls_back_to_deepest(tmp_path):
    cfg = cfg_for(tmp_path)
    t = Tuner(cfg, SimCPU([30] * 16).hardware(), StateStore(tmp_path / "s.json"), log=lambda s: None)
    t.st = RunState(16, search_params(cfg))
    t.st.final = {c: 10 for c in range(16)}
    t.st.final.update({3: 0, 5: 30, 9: 30, 12: 28, 14: 20})
    assert t._idle_suspects({"cores": [3]}) == ([5, 9, 12], "deepest")           # 3 zaten 0: atıf kullanılamaz
    assert t._idle_suspects({"cores": [14]}) == ([14], "whea")
    assert t._idle_suspects({"cores": []}) == ([5, 9, 12], "deepest")            # en derinin 4 içi, eşitlikte küçük numara


# ----------------------------------------------------------------------------- MHz'e göre kırpma
def test_trim_levels_and_choice():
    assert trim_levels(50, 10, 5) == [50, 40, 30, 20, 10]
    assert trim_levels(12, 10, 5) == [12, 2]
    assert choose_trim({50: 5550.0, 40: 5550.0, 30: 5550.0, 20: 5540.0, 10: 5420.0}, 45) == 20
    assert choose_trim({50: 5600.0, 40: 5500.0}, 45) == 50                  # derin CO MHz kazandırıyor: dokunma
    assert choose_trim({50: 5550.0, 40: None, 30: None}, 45) is None         # ölçülemedi
    assert choose_trim({50: None, 40: 5500.0, 30: 5490.0}, 45) == 30        # ölçülenlerin en sığı


def trim_limits():
    return [60, 60, 60, 60, 30, 30, 30, 30] * 2          # ilk 4 çekirdek/CCD araç sınırının (-50) üstünde


def test_trim_picks_shallowest_equivalent_for_capped_cores(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg.idle_minutes = 0
    fmax = [5550] * 16
    cfg, sim, store, st = finished_run(tmp_path, trim_limits(), cfg=cfg, fmax=fmax, cli_max=50)
    capped = [c for c in range(16) if c % 8 < 4]
    assert st.capped_cores() == capped
    assert set(st.trim["from"]) == set(capped) and all(a == 50 for a in st.trim["from"].values())
    for c in capped:                                     # elle hesap: 5300 - 20c + 12a, 5550'de tavan, tolerans 45
        expect = min(a for a in (50, 40, 30, 20, 10) if min(5300 - 20 * (c) + 12 * a, 5550) >= 5550 - 45)
        assert st.final[c] == expect < 50
        assert st.final_mhz[c] is not None
    others = [c for c in range(16) if c not in capped]
    assert all(st.final[c] == st.searches[c].final for c in others)              # sınırı bulunanlara dokunulmaz
    text, data = build_report(st, cfg)
    assert text.count("bilinmiyor") >= len(capped)
    assert all(r["limit"] == ("unknown" if r["core"] in capped else "found") for r in data["cores"])
    assert "MHz'e göre kırpma" in text and "-50 ->" in text


def test_trim_keeps_value_when_deeper_co_still_adds_mhz(tmp_path):
    cfg = cfg_for(tmp_path, idle_minutes=0)
    cfg, sim, store, st = finished_run(tmp_path, trim_limits(), cfg=cfg, cli_max=50)        # fmax yok: doğrusal
    for c in st.trim["from"]:
        assert st.final[c] == 50 and st.trim["chosen"][c] == 50
    assert st.capped_cores() == [c for c in range(16) if c % 8 < 4]            # yine de "sınır bilinmiyor"


def test_trim_disabled_leaves_capped_cores_at_floor_but_still_flags_them(tmp_path):
    cfg = cfg_for(tmp_path, idle_minutes=0, trim_enabled=False)
    cfg, sim, store, st = finished_run(tmp_path, trim_limits(), cfg=cfg, fmax=[5550] * 16, cli_max=50)
    assert st.trim is None and all(st.final[c] == 50 for c in range(16) if c % 8 < 4)
    assert "bilinmiyor" in build_report(st, cfg)[0]


def test_trim_unmeasurable_keeps_value_and_says_so(tmp_path):
    cfg = cfg_for(tmp_path, idle_minutes=0)
    sim = SimCPU(trim_limits(), seed=1, crash_prob=0.0, band=0, allcore_penalty=0, cli_max=50)
    hw = sim.hardware()
    hw.boost = type("B", (), {"measure": lambda self, cpu: None})()          # WMI sayacı okunamıyor
    st = Tuner(cfg, hw, StateStore(tmp_path / "state.json"), log=lambda s: None).run()
    assert st.trim["from"] and all(st.final[c] == 50 and st.trim["skipped"][c] == "unmeasurable" for c in st.trim["from"])
    assert "ölçülemedi" in build_report(st, cfg)[0]


def test_trim_runs_before_lowload_on_a_finished_run_from_old_code(tmp_path):
    """Kırpmadan önceki sürümle bitmiş bir çalışma: `lowload` önce kırpar, sonra düşük yük + boşta testini yapar."""
    cfg = cfg_for(tmp_path, idle_minutes=120, trim_enabled=False)
    cfg, sim, store, st0 = finished_run(tmp_path, trim_limits(), cfg=cfg, fmax=[5550] * 16, cli_max=50)
    assert st0.trim is None and st0.final[0] == 50
    cfg.trim_enabled = True
    prepare_lowload(cfg, store)
    assert store.load(search_params(cfg)).stage == STAGE_TRIM
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.stage == STAGE_DONE and st.final[0] < 50 and st.trim["chosen"][0] == st.final[0]
    assert st.lowload["idle_result"] == "passed" and len(st.lowload["cores_done"]) == 16
    assert verdict(st)[0] == VERIFIED


def test_crash_in_the_middle_of_trim_resumes_without_remeasuring(tmp_path):
    from pbo_tuner.sim import SimulatedCrash
    cfg = cfg_for(tmp_path, idle_minutes=0)
    sim = SimCPU(trim_limits(), seed=1, crash_prob=0.0, band=0, allcore_penalty=0, cli_max=50, fmax=[5550] * 16)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real, count = hw.boost, {"n": 0}

    class Boom:
        def measure(self, cpu):
            count["n"] += 1
            if count["n"] == 20:                      # trim ortasında: sistem çöker
                raise SimulatedCrash()
            return real.measure(cpu)

    hw.boost = Boom()
    with pytest.raises(SimulatedCrash):
        Tuner(cfg, hw, store, log=lambda s: None).run()
    mid = store.load(search_params(cfg))
    assert mid.stage == STAGE_TRIM and mid.trim["measured"]
    done_levels = sum(len(v) for v in mid.trim["measured"].values())
    sim.reboot()
    hw2, calls = sim.hardware(), {"n": 0}
    real2 = hw2.boost

    class Count:
        def measure(self, cpu):
            calls["n"] += 1
            return real2.measure(cpu)

    hw2.boost = Count()
    st = Tuner(cfg, hw2, store, log=lambda s: None).run()
    assert st.stage == STAGE_DONE and st.trim["chosen"]
    total_levels = sum(len(v) for v in st.trim["measured"].values())
    # kaldığı yerden devam: bitmiş seviyeler yeniden ölçülmedi (en fazla son yarım kalan + final ölçümleri)
    assert calls["n"] <= (total_levels - done_levels) * cfg.trim_samples + 16 * 1 + cfg.trim_samples


# ----------------------------------------------------------------------------- hüküm
def test_verdict_partial_when_lowload_and_idle_were_not_run(tmp_path):
    cfg, sim, store, st = finished_run(tmp_path)
    v, reasons = verdict(st)
    assert v == PARTIAL and any("lowload" in r for r in reasons)
    text = build_report(st, cfg)[0]
    assert "SONUÇ: KISMEN DOĞRULANDI" in text and "BIOS'a GİRMEYİN" not in text


def test_verdict_partial_for_short_idle_and_verified_for_long_idle(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    cfg.idle_minutes = 5
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    v, reasons = verdict(st)
    assert v == PARTIAL and any("kısa" in r for r in reasons)
    cfg.idle_minutes = 120
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert verdict(st) == (VERIFIED, [])


def test_verdict_not_verified_when_allcore_never_passed(tmp_path):
    cfg, sim, store, st = finished_run(tmp_path)
    st.allcore_ok = False
    v, reasons = verdict(st)
    assert v == NOT_VERIFIED and any("allcore" in r for r in reasons)
    st.allcore_ok, st.stage = True, "idle"
    assert verdict(st)[0] == NOT_VERIFIED and "idle" in verdict(st)[1][0]


# ----------------------------------------------------------------------------- durum dosyası uyumluluğu
def test_old_state_files_without_new_keys_still_load_and_work(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    prepare_lowload(cfg, store)
    d = json.loads(store.path.read_text(encoding="utf-8"))
    for k in ("trim", "allcore_ok", "allcore_targeted"):
        d.pop(k)
    for k in ("idle_rounds", "idle_history", "idle_attrib"):
        d["lowload"].pop(k)
    store.path.write_text(json.dumps(d), encoding="utf-8")
    old = store.load(search_params(cfg))
    assert old.trim is None and old.allcore_ok is None and old.allcore_targeted == 0
    sim.idle_limits = [99] * 16
    sim.idle_limits[3] = st0.final[3] - 2
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st.lowload["idle_result"] == "passed" and st.final[3] == st0.final[3] - 2


def test_trim_state_survives_json_roundtrip(tmp_path):
    cfg = cfg_for(tmp_path, idle_minutes=0)
    cfg, sim, store, st = finished_run(tmp_path, trim_limits(), cfg=cfg, fmax=[5550] * 16, cli_max=50)
    again = store.load(search_params(cfg))
    assert again.trim == st.trim
    assert all(isinstance(c, int) for c in again.trim["measured"]) and all(
        isinstance(a, int) for lv in again.trim["measured"].values() for a in lv)


def test_new_config_keys_are_validated():
    for bad in ({"idle_max_rounds": -1}, {"idle_backoff": 0}, {"trim_points": 1}, {"trim_step": 0},
                {"trim_samples": 0}, {"trim_tolerance_mhz": -1}, {"allcore_attrib_rounds": -1}):
        with pytest.raises(ConfigError):
            cfg = Config()
            for k, v in bad.items():
                setattr(cfg, k, v)
            cfg.validate()


# ----------------------------------------------------------------------------- İngilizce rapor
def test_english_report_has_no_turkish_for_every_verdict(tmp_path):
    import re
    from pbo_tuner import i18n
    cfg = cfg_for(tmp_path)
    cfg, sim, store, st0 = finished_run(tmp_path, trim_limits(), cfg=cfg, fmax=[5550] * 16, cli_max=50)
    texts = []
    cfg.idle_minutes = 120
    prepare_lowload(cfg, store)
    sim.whea_visible = False
    sim.idle_fail_a = 5
    st_bad = run_with_reboots(cfg, sim, store, log=lambda s: None)       # DOĞRULANMADI + geçmiş + kırpma + bilinmiyor
    i18n.set_language("en")
    try:
        texts.append(build_report(st_bad, cfg)[0])
        texts.append(build_report(st0, cfg)[0])                          # KISMEN
        sim.idle_fail_a = None
        prepare_lowload(cfg, store)
        st_ok = run_with_reboots(cfg, sim, store, log=lambda s: None)
        texts.append(build_report(st_ok, cfg)[0])                        # DOĞRULANDI
    finally:
        i18n.set_language("tr")
    assert "RESULT: NOT VERIFIED" in texts[0] and "RESULT: PARTIALLY VERIFIED" in texts[1] \
        and "RESULT: VERIFIED" in texts[2]
    stamp = re.compile(r"^\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")     # notlar yazıldıkları dilde saklanır (eski kayıt)
    for t in texts:
        bad = [l for l in t.splitlines() if re.search(r"[çğıöşüÇĞİÖŞÜ]", l) and not stamp.match(l)]
        assert not bad, bad[:3]


def test_capped_cores_ignore_stale_note_text_from_older_state_files():
    """Gerçek eski durum dosyasında uzatma sonrası notlar 'CLI sınırı: en fazla -50' idi: -50'de HATA görenler (sınırı
    bulunmuş) da, -50'ye hatasız inenler de aynı notu taşıyordu. Karar nota değil sonuca dayanır."""
    cfg = Config()
    st = RunState(4, search_params(cfg))
    for c, (final, note) in enumerate([(50, "CLI sınırı: en fazla -50"),        # -50'de geçti: sınır bilinmiyor
                                       (44, "CLI sınırı: en fazla -50"),        # -50'de kaldı, 44'te onaylandı: bulundu
                                       (50, "floor reached without error"),
                                       (30, "")]):
        st.searches[c].final, st.searches[c].note = final, note
        st.final[c] = final
    assert st.capped_cores() == [0, 2]
    st.final[0] = 48                                    # sonradan doğrulamada/boşta geri çekildi: sınır görüldü
    assert st.capped_cores() == [2]


def test_blanket_allcore_backoff_does_not_make_capped_cores_look_found(tmp_path):
    """Gerçek çalışma: 4/6/9 numaralı çekirdekler -50'de hatasız geçti, sonra tüm çekirdek testi (başka bir yüzünden)
    kalınca herkese -2 uygulandı. Bu çekirdeklerin sınırı hâlâ bilinmiyor; -48 görünmesi 'bulundu' demek değil."""
    cfg = cfg_for(tmp_path, idle_minutes=0, trim_enabled=False)
    sim = SimCPU(trim_limits(), seed=1, crash_prob=0.0, band=0, allcore_penalty=3, cli_max=50)
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=lambda s: None)
    assert st.allcore_rounds >= 1 and st.allcore_blanket == 2 * st.allcore_rounds
    capped = [c for c in range(16) if c % 8 < 4]
    assert all(st.final[c] == 50 - st.allcore_blanket for c in capped)          # -50'den geri çekilmiş görünüyor...
    assert st.capped_cores() == capped                                           # ...ama sınır yine "bilinmiyor"
    assert build_report(st, cfg)[1]["cores"][0]["limit"] == "unknown"


def test_old_state_files_derive_blanket_from_allcore_rounds(tmp_path):
    cfg, sim, store, st0 = finished_run(tmp_path)
    d = json.loads(store.path.read_text(encoding="utf-8"))
    d.pop("allcore_blanket", None)
    d["allcore_rounds"] = 1
    store.path.write_text(json.dumps(d), encoding="utf-8")
    assert store.load(search_params(cfg)).allcore_blanket == 2


def test_a_real_backoff_beyond_the_blanket_still_marks_the_limit_as_found():
    cfg = Config()
    st = RunState(2, search_params(cfg))
    for c in (0, 1):
        st.searches[c].final, st.searches[c].note = 50, "floor reached without error"
    st.allcore_blanket = 2
    st.final = {0: 48, 1: 46}            # 0: yalnızca genel -2; 1: ayrıca doğrulamada/boşta bir hata görüp daha geri çekildi
    assert st.capped_cores() == [0]


def test_report_does_not_claim_whea_named_a_core_when_only_general_rounds_ran():
    """Gerçek rapor: 1 genel tur, 0 hedefli tur. 'WHEA çekirdeği gösterdi' demek yanlıştı."""
    cfg = Config()
    st = RunState(2, search_params(cfg))
    for c in (0, 1):
        st.searches[c].final = 30
    st.final, st.stage, st.allcore_rounds, st.allcore_targeted = {0: 28, 1: 28}, STAGE_DONE, 1, 0
    text = build_report(st, cfg)[0]
    assert "1 genel tur" in text and "WHEA" not in text.split("geri çekmeleri:")[1].splitlines()[0]
    st.allcore_targeted = 2
    assert "2 hedefli tur (WHEA APIC ID" in build_report(st, cfg)[0]
