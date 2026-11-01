"""Zen 3 / Zen 4 / Zen 5 algılama, ön ayarlar, APIC eşleme, 6/12 çekirdekli düzen."""
import pytest

from pbo_tuner.config import Config, ConfigError, load_config
from pbo_tuner.generations import (AVX512_MODES, GENERATIONS, classify, parse_identifier, resolve_generation)
from pbo_tuner.hw import ToolError, make_cpu_to_apic, whea_relevant
from pbo_tuner.report import build_report
from pbo_tuner.sim import SimCPU, run_with_reboots
from pbo_tuner.state import StateStore, STAGE_DONE

ID_Z5 = ("AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD", "AMD Ryzen 9 9950X3D 16-Core Processor")
ID_Z4 = ("AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD", "AMD Ryzen 9 7950X 16-Core Processor")
ID_Z3 = ("AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD", "AMD Ryzen 9 5900X 12-Core Processor")


def fresh_cfg(**explicit):
    cfg = Config()
    for k, v in explicit.items():
        setattr(cfg, k, v)
    cfg._explicit = set(explicit)
    return cfg


@pytest.mark.parametrize("ident,expected", [
    ("AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD", "zen5"),     # Granite Ridge
    ("AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD", "zen4"),     # Raphael
    ("AMD64 Family 25 Model 116 Stepping 1, AuthenticAMD", "zen4"),    # Phoenix (8000G)
    ("AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD", "zen3"),     # Vermeer
    ("AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD", "zen3"),     # Cezanne (5000G)
    ("AMD64 Family 23 Model 113 Stepping 0, AuthenticAMD", None),      # Zen 2: desteklenmiyor
    ("AMD64 Family 25 Model 17 Stepping 1, AuthenticAMD", None),       # Genoa (EPYC)
    ("Intel64 Family 6 Model 183 Stepping 1, GenuineIntel", None),
    ("saçma", None),
])
def test_classify_identifiers(ident, expected):
    fm = parse_identifier(ident)
    assert (classify(*fm) if fm else None) == expected


def test_presets_apply_when_keys_not_explicit_zen3():
    cfg = fresh_cfg()
    logs = []
    assert resolve_generation(cfg, logs.append, identity=ID_Z3) == "zen3"
    assert (cfg.mode, cfg.floor, cfg.start_co) == ("19-ZN2 ~ Kagari", 30, 10)
    assert cfg.lowload_mode == "19-ZN2 ~ Kagari" and cfg.lowload_mode not in AVX512_MODES
    assert any("Zen 3" in l for l in logs)


def test_presets_zen4_and_zen5():
    c4, c5 = fresh_cfg(), fresh_cfg()
    resolve_generation(c4, lambda s: None, identity=ID_Z4)
    resolve_generation(c5, lambda s: None, identity=ID_Z5)
    assert (c4.mode, c4.floor, c4.start_co) == ("22-ZN4 ~ Kizuna", 50, 15)
    assert (c5.mode, c5.floor, c5.start_co) == ("24-ZN5 ~ Komari", 50, 20)       # 9950X3D'de önceki davranış korunur


def test_explicit_values_are_kept_but_impossible_ones_are_clamped():
    cfg = fresh_cfg(floor=50, start_co=20, mode="24-ZN5 ~ Komari")        # 9950X3D config'i
    resolve_generation(cfg, lambda s: None, identity=ID_Z5)
    assert (cfg.floor, cfg.start_co, cfg.mode) == (50, 20, "24-ZN5 ~ Komari")

    cfg = fresh_cfg(floor=40, start_co=25)                                  # kullanıcı seçimi korunur (Zen 4)
    resolve_generation(cfg, lambda s: None, identity=ID_Z4)
    assert (cfg.floor, cfg.start_co) == (40, 25)

    logs = []
    cfg = fresh_cfg(floor=50, start_co=20)                                  # aynı config Zen 3'te: sınıra çekilir
    resolve_generation(cfg, logs.append, identity=ID_Z3)
    assert cfg.floor == 30 and cfg.start_co == 20 and any("UYARI" in l for l in logs)
    cfg = fresh_cfg(floor=50, start_co=40)
    resolve_generation(cfg, lambda s: None, identity=ID_Z3)
    assert cfg.start_co <= cfg.floor == 30


def test_avx512_binary_is_rejected_on_zen3_only():
    with pytest.raises(ConfigError, match="AVX-512"):
        resolve_generation(fresh_cfg(mode="24-ZN5 ~ Komari"), lambda s: None, identity=ID_Z3)
    with pytest.raises(ConfigError, match="AVX-512"):
        resolve_generation(fresh_cfg(lowload_mode="22-ZN4 ~ Kizuna"), lambda s: None, identity=ID_Z3)
    logs = []
    resolve_generation(fresh_cfg(mode="24-ZN5 ~ Komari"), logs.append, identity=ID_Z4)   # Zen 4'te yalnızca uyarı
    assert any("önerilen ikili değil" in l for l in logs)


def test_unsupported_and_locked_cpus_fail_clearly():
    with pytest.raises(ToolError, match="tanınmadı"):
        resolve_generation(fresh_cfg(), lambda s: None, identity=("AMD64 Family 23 Model 113 Stepping 0", "AMD Ryzen 7 3700X"))
    with pytest.raises(ToolError, match="kilitli"):
        resolve_generation(fresh_cfg(), lambda s: None,
                           identity=("AMD64 Family 25 Model 33 Stepping 2", "AMD Ryzen 7 5800X3D 8-Core Processor"))


def test_manual_generation_skips_detection():
    cfg = fresh_cfg(generation="zen4")
    assert resolve_generation(cfg, lambda s: None, identity=("tanınmayan", "?")) == "zen4"
    with pytest.raises(ConfigError):
        resolve_generation(fresh_cfg(generation="zen9"), lambda s: None)


def test_resolution_is_idempotent():
    cfg = fresh_cfg()
    logs = []
    resolve_generation(cfg, logs.append, identity=ID_Z3)
    n = len(logs)
    resolve_generation(cfg, logs.append, identity=("başka", "başka"))        # ikinci çağrı hiçbir şeyi değiştirmez
    assert len(logs) == n and cfg.floor == 30


def test_load_config_tracks_explicit_keys(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[search]\nfloor = 45\n[stress]\nseconds_per_test = 15\n')
    cfg = load_config(str(p))
    assert cfg._explicit == {"floor", "seconds_per_test"}
    resolve_generation(cfg, lambda s: None, identity=ID_Z4)
    assert cfg.floor == 45 and cfg.mode == "22-ZN4 ~ Kizuna"                 # floor açık, mode otomatik


def test_example_config_leaves_generation_dependent_keys_automatic():
    cfg = load_config("config.example.toml")
    assert not ({"floor", "start_co", "mode", "generation"} & cfg._explicit)


# ------------------------------------------------------------ APIC eşleme ve çekirdek düzeni
def test_apic_mapping_identity_for_8_8_16_and_single_ccd():
    f16 = make_cpu_to_apic(16, True)
    assert all(f16(c) == c for c in range(32))
    f6 = make_cpu_to_apic(6, True)
    assert all(f6(c) == c for c in range(12))
    f8_nosmt = make_cpu_to_apic(8, False)
    assert all(f8_nosmt(c) == c for c in range(8))


def test_apic_mapping_has_gap_for_6_plus_6():
    f = make_cpu_to_apic(12, True)                    # 5900X / 7900X: çekirdek 6 = APIC 16/17 (CoreCycler notu)
    assert [f(c) for c in (0, 1, 10, 11)] == [0, 1, 10, 11]
    assert [f(c) for c in (12, 13)] == [16, 17]       # çekirdek 6
    assert f(23) == 16 + 2 * 5 + 1


def test_whea_matching_uses_apic_mapping():
    f = make_cpu_to_apic(12, True)
    ev_core6 = [{"apic_id": 16}]
    assert whea_relevant(ev_core6, [12], True, cpu_to_apic=f) == ev_core6          # test edilen çekirdek (CPU 12)
    assert whea_relevant(ev_core6, [2], True, cpu_to_apic=f) == []                 # başka çekirdek
    assert whea_relevant([{"apic_id": 12}], [12], True, cpu_to_apic=f) == []       # harita yokken yanlış eşleşirdi


@pytest.mark.parametrize("n,limits", [(6, [26, 20, 14, 30, 22, 18]),
                                      (8, [28, 24, 20, 16, 30, 26, 22, 18]),
                                      (12, [30, 24, 18, 22, 28, 16, 20, 26, 14, 30, 24, 18])])
def test_full_sim_run_on_6_8_12_core_chips_and_ccd_labels(tmp_path, n, limits):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, floor=30, start_co=10)
    cfg.validate()
    sim = SimCPU(limits, seed=n, crash_prob=0.5, band=0, allcore_penalty=0)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=lambda s: None)
    assert st is not None and st.stage == STAGE_DONE and len(st.final) == n
    assert all(st.final[c] <= limits[c] and st.final[c] <= 30 for c in range(n))
    _, data = build_report(st, cfg)
    ccds = [r["ccd"] for r in data["cores"]]
    if n > 8:
        assert ccds == [0] * (n // 2) + [1] * (n // 2)                              # 12 çekirdek = 6+6
    else:
        assert set(ccds) == {0}                                                     # 6/8 çekirdek: tek CCD


def test_generation_table_is_consistent():
    for g, p in GENERATIONS.items():
        assert p["floor"] <= p["floor_max"] <= 50 and p["start_co"] <= p["floor"]
        assert (p["mode"] in AVX512_MODES) == (g != "zen3")


def test_make_real_hardware_applies_generation_preset_and_apic_map(tmp_path, monkeypatch):
    """Windows'a özgü kısım taklit edilerek: algılama -> ön ayar -> çalıştırıcı yapılandırması."""
    import types
    from pbo_tuner import generations, hw as hwmod
    monkeypatch.setattr(hwmod, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(generations, "read_cpu_identity", lambda: ID_Z3)
    monkeypatch.setattr(hwmod, "detect_topology", lambda c, s: (12, True))
    cfg = Config(corecycler_dir=str(tmp_path / "CoreCycler"), data_dir=str(tmp_path / "data"))
    cfg._explicit = set()
    hw = hwmod.make_real_hardware(cfg, lambda s: None)
    assert (cfg.mode, cfg.floor, cfg.start_co) == ("19-ZN2 ~ Kagari", 30, 10)
    assert hw.n_cores == 12 and hw.smt and hw.stress.exe.name == "19-ZN2 ~ Kagari.exe"
    assert hw.stress.cpu_to_apic(12) == 16 and hw.stress.n_logical == 24
    assert hw.cpus_for_core(11) == [22] and len(hw.all_cpus()) == 24
