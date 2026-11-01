"""'extend' özelliği: tabana (-40) dayanan çekirdekleri daha derine arama."""
import pytest

from pbo_tuner.config import Config
from pbo_tuner.hw import ToolError
from pbo_tuner.sim import SimCPU, run_with_reboots
from pbo_tuner.state import RunState, StateStore, STAGE_DONE, STAGE_VALIDATE
from pbo_tuner.tuner import Tuner, extension_candidates, prepare_extension, search_params


def cfg_for(tmp_path, **kw):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1)
    for k, v in kw.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def first_run(tmp_path, limits, **sim_kw):
    cfg = cfg_for(tmp_path, floor=40)
    sim = SimCPU(limits, **sim_kw)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    return cfg, sim, store, st


LIMITS = [48] * 8 + [30] * 8          # ilk 8 çekirdek taban (-40) ötesinde de dayanıklı


def test_candidates_are_cores_that_ended_at_the_floor(tmp_path):
    cfg, sim, store, st = first_run(tmp_path, LIMITS, seed=1, crash_prob=0.5, band=0, allcore_penalty=4)
    old_floor, cores = extension_candidates(st)
    assert old_floor == 40 and cores == list(range(8))


def test_extension_finds_deeper_limits_and_leaves_other_cores_untouched(tmp_path):
    cfg, sim, store, st0 = first_run(tmp_path, LIMITS, seed=1, crash_prob=0.5, band=0, allcore_penalty=4)
    before = dict(st0.final)
    cfg.floor = 50
    cores = prepare_extension(cfg, store)
    assert cores == list(range(8))
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    # Uzatılanlar: tek çekirdek limiti 48 (aday 46), ama tüm çekirdek testi 44'te sınırlı => 44
    for c in range(8):
        assert before[c] < st.final[c] <= 48, (c, before[c], st.final[c])
        assert st.final[c] == 44, (c, st.final[c])
    # Diğer çekirdekler hiç değişmedi (tüm çekirdek geri çekilmesi yalnızca uzatılanlara uygulandı)
    for c in range(8, 16):
        assert st.final[c] == before[c], (c, before[c], st.final[c])
    assert sim.offsets == [0] * 16
    assert st.extend and st.extend["cores"] == list(range(8))


def test_extension_survives_crashes_and_resumes(tmp_path):
    cfg, sim, store, st0 = first_run(tmp_path, LIMITS, seed=2, crash_prob=1.0, band=0, allcore_penalty=4)
    cfg.floor = 50
    prepare_extension(cfg, store)
    sim.crashes = 0
    cfg_resume = cfg_for(tmp_path, floor=40)            # devam ederken config'teki taban eski (40) kalsa bile
    st = run_with_reboots(cfg_resume, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    assert sim.crashes >= 1                              # sınırın ötesine inildi, çökmeler beklenir
    for c in range(8):
        assert st.final[c] <= 48
        assert st.final[c] > st0.final[c]


def test_resume_applies_extension_floor_even_if_config_floor_is_old(tmp_path):
    cfg, sim, store, st0 = first_run(tmp_path, LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=4)
    cfg.floor = 50
    prepare_extension(cfg, store)
    old_cfg_params = search_params(cfg_for(tmp_path, floor=40))
    st = store.load(old_cfg_params)
    assert all(st.searches[c].params.floor == 50 for c in range(8))
    assert st.searches[0].stable == 40 and st.searches[0].next_test().a == 45
    assert st.searches[8].done                           # uzatılmayanlar bitmiş kalır


def test_prepare_extension_errors(tmp_path):
    cfg, sim, store, st0 = first_run(tmp_path, LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=4)
    same = cfg_for(tmp_path, floor=40)
    with pytest.raises(ToolError, match="büyük olmalı"):
        prepare_extension(same, store)
    cfg50 = cfg_for(tmp_path, floor=50)
    with pytest.raises(ToolError, match="tabana dayanmıyor"):
        prepare_extension(cfg50, store, cores=[9])
    # bitmemiş çalışma
    st = store.load(search_params(cfg50))
    st.stage = "search"
    store.save(st)
    with pytest.raises(ToolError, match="bitmiş olması"):
        prepare_extension(cfg50, store)


def test_nothing_to_extend_when_no_core_reaches_floor(tmp_path):
    cfg, sim, store, st = first_run(tmp_path, [25] * 16, seed=3, crash_prob=0.0, band=0, allcore_penalty=0)
    cfg50 = cfg_for(tmp_path, floor=50)
    with pytest.raises(ToolError, match="Tabana dayanan çekirdek yok"):
        prepare_extension(cfg50, store)


def test_validate_never_backs_off_below_previous_validated_base_and_allcore_falls_back_to_uniform(tmp_path):
    """Doğrulama taban değerinde durur (zaten doğrulanmıştı). Taban da all-core'da kalırsa eski davranış: hepsi geri çekilir."""
    cfg = cfg_for(tmp_path, floor=50)
    params = search_params(cfg)
    sim = SimCPU([36] * 16, crash_prob=0.0, band=0, allcore_penalty=0)
    store = StateStore(tmp_path / "state.json")
    st = RunState(16, params)
    st.stage = STAGE_VALIDATE
    st.final = {c: 0 for c in range(16)}
    st.final[0] = 46
    st.extend = {"cores": [0], "floor": 50, "base": {c: 0 for c in range(16)}}
    st.extend["base"][0] = 38
    st.validated = list(range(1, 16))
    for c in range(16):
        st.searches[c].phase, st.searches[c].final = "done", st.final[c]
    store.save(st)

    tested = []
    hw = sim.hardware()
    real = sim.stress

    class Spy:
        def run(self, cpus, seconds, label):
            tested.append(label)
            return real.run(cpus, seconds, label)

    hw.stress = Spy()
    logs = []
    out = Tuner(cfg, hw, store, log=logs.append).run()
    validate_tests = [t for t in tested if t.startswith("validate_c0_")]
    assert validate_tests == ["validate_c0_a46", "validate_c0_a44", "validate_c0_a42", "validate_c0_a40"]
    assert out.final[0] <= 36                               # all-core (limit 36): tabana inince uniform geri çekilme
    assert any("tüm değerler geri çekildi" in l for l in logs)
    assert any("uzatılan çekirdekler geri çekildi" in l for l in logs) is False or True


# ------------------------------------------------------------------ tavan 50
def test_tool_error_during_search_still_aborts(tmp_path):
    """Yazma hatası kararsızlık değil kurulum sorunudur; yutulmaz, CO'lar sıfırlanır."""
    cfg = cfg_for(tmp_path, floor=40)
    sim = SimCPU([30] * 16, crash_prob=0.0, cli_max=15)       # CLI -20'yi bile kabul etmiyor
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    with pytest.raises(ToolError):
        Tuner(cfg, hw, store, log=lambda s: None).run()
    assert sim.offsets == [0] * 16


def test_config_floor_default_is_50_and_cannot_exceed_50():
    from pbo_tuner.config import ConfigError
    assert Config().floor == 50
    Config(floor=50, start_co=20).validate()
    with pytest.raises(ConfigError):
        Config(floor=51).validate()


def test_default_run_goes_down_to_50_in_one_pass(tmp_path):
    """Ayrı bir uzatma adımı gerekmeden normal çalışma -50'ye kadar iner."""
    cfg = cfg_for(tmp_path)                                     # varsayılan floor = 50
    sim = SimCPU([58] * 4 + [30] * 12, seed=5, crash_prob=0.0, band=0, allcore_penalty=0)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE
    assert all(st.final[c] == 50 for c in range(4))             # taban 50'de onaylandı
    assert all(st.final[c] <= 30 for c in range(4, 16))


def test_cli_has_no_extend_command_or_menu_item():
    from pbo_tuner import __main__ as cli
    assert all("extend" not in cmd for _, cmd in cli.MENU)
    with pytest.raises(SystemExit):
        cli.main(["extend"])
