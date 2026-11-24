"""Gözden kaçmış hatalar için regresyon testleri: rapor (kırpma / düşük yük ayrımı, Zen 3 tabanı), ayar dosyası
okuma ve doğrulama, bozuk durum dosyası, --quick'in devamda korunması, resume.bat / run_as_admin.bat kodlaması."""
import subprocess
import types
from pathlib import Path

import pytest

from pbo_tuner import __main__ as cli
from pbo_tuner import hw as hwmod
from pbo_tuner import i18n, share
from pbo_tuner.config import Config, ConfigError, load_config, quick_preset
from pbo_tuner.hw import ToolError, WheaReader
from pbo_tuner.report import build_report, is_warning, lowload_changes
from pbo_tuner.sim import SimCPU, SimulatedCrash, run_with_reboots
from pbo_tuner.state import RunState, StateStore, STAGE_DONE, STAGE_SEARCH
from pbo_tuner.tuner import Tuner, prepare_lowload, search_params

ROOT = Path(__file__).resolve().parent.parent
TRIM_LIMITS = [60, 60, 60, 60, 30, 30, 30, 30] * 2        # ilk 4 çekirdek/CCD araç sınırına (-50) hatasız iner


def quiet(_msg):
    pass


def write_cfg(tmp_path, body: str = "", raw: bytes = None) -> str:
    p = tmp_path / "config.toml"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text(f"[paths]\ndata_dir = '{tmp_path / 'data'}'\n" + body, encoding="utf-8")
    return str(p)


# ----------------------------------------------------------------------------- rapor: kırpma, düşük yük geri çekmesi değildir
def lowload_after_old_code_run(tmp_path, lowload_limits=None):
    """Kırpmadan önceki sürümle bitmiş çalışma + `lowload`: önce kırpar, sonra düşük yük + boşta testini yapar."""
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, lowload_seconds=60, idle_minutes=120,
                 trim_enabled=False)
    cfg.validate()
    sim = SimCPU(TRIM_LIMITS, seed=1, crash_prob=0.0, band=0, allcore_penalty=0, fmax=[5550] * 16, cli_max=50,
                 lowload_limits=lowload_limits)
    store = StateStore(tmp_path / "state.json")
    st0 = run_with_reboots(cfg, sim, store, log=quiet)
    cfg.trim_enabled = True
    prepare_lowload(cfg, store)
    st = run_with_reboots(cfg, sim, store, log=quiet)
    assert st.stage == STAGE_DONE and st.lowload["idle_result"] == "passed"
    return cfg, st0, st


def test_trim_before_lowload_is_not_reported_as_a_lowload_backoff(tmp_path):
    """Gerçek rapor: 'Low-load test: backed off: core 4: -48 -> -28, core 6: -48 -> -28, core 9: -48 -> -8' yazıyordu;
    oysa bu üç çekirdek düşük yük testinde hiç kalmamış, testten ÖNCE MHz'e göre kırpılmıştı."""
    cfg, st0, st = lowload_after_old_code_run(tmp_path)
    trimmed = [c for c, a in st.trim["chosen"].items() if a != st.trim["from"][c]]
    assert trimmed, "bu senaryoda en az bir çekirdek kırpılmalı"
    assert lowload_changes(st) == []
    text = build_report(st, cfg)[0]
    assert "tüm çekirdekler geçti" in text and "geri çekilenler" not in text
    assert "MHz'e göre kırpma" in text and "-50 ->" in text                 # kırpma kendi bölümünde yazmaya devam eder
    assert all(st.lowload["initial"][c] == st.trim["chosen"][c] for c in trimmed)


def test_real_lowload_backoff_is_still_reported_next_to_trimmed_cores(tmp_path):
    weak = 5                                                # ağır yükte 30; düşük yükte 20
    ll = list(TRIM_LIMITS)
    ll[weak] = 20
    cfg, st0, st = lowload_after_old_code_run(tmp_path, lowload_limits=ll)
    assert lowload_changes(st) == [(weak, st0.final[weak], st.final[weak])] and st.final[weak] <= 20
    text = build_report(st, cfg)[0]
    assert f"geri çekilenler: çekirdek {weak}: -{st0.final[weak]} -> -{st.final[weak]}" in text
    info = {"tool_version": "x"}
    assert "cores backed off: 1" in share.format_report(info, st)


def test_state_saved_by_the_old_code_reports_trim_and_lowload_separately(tmp_path):
    """Düzeltmeden önce yazılmış durum dosyası: `initial` kırpmadan ÖNCEKİ değerleri taşır (kullanıcının gerçek dosyası)."""
    cfg, st0, st = lowload_after_old_code_run(tmp_path)
    st.lowload["initial"] = {**st.lowload["initial"], **st.trim["from"]}
    assert lowload_changes(st) == []
    c = next(c for c, a in st.trim["chosen"].items() if a != st.trim["from"][c])
    st.final[c] = st.trim["chosen"][c] - 2                  # kırpmadan sonra düşük yük testi ayrıca 2 geri çekti
    assert lowload_changes(st) == [(c, st.trim["chosen"][c], st.trim["chosen"][c] - 2)]


# ----------------------------------------------------------------------------- Zen 3: taban durum dosyasından okunur
def test_report_uses_the_floor_the_search_really_used_not_the_unresolved_default(tmp_path):
    """`report` / `status` / `share` nesil ön ayarını uygulamadan yükler: config tabanı 50 kalır. Zen 3'te (taban 30)
    -30'a hatasız inen çekirdekler çalışma sonu raporunda 'bilinmiyor', `report` komutunda 'bulundu' görünüyordu."""
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, floor=30, start_co=10, trim_enabled=False)
    cfg.validate()
    sim = SimCPU([60, 60, 20, 20, 60, 20], seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    store = StateStore(tmp_path / "state.json")
    st = run_with_reboots(cfg, sim, store, log=quiet)
    assert st.capped_cores() == [0, 1, 4]
    plain = Config(data_dir=str(tmp_path))                  # `report` komutunun gördüğü ayarlar (floor = 50)
    again = store.load(search_params(plain))
    assert again.floor_used == 30 and again.capped_cores() == [0, 1, 4]
    text, data = build_report(again, plain)
    assert [r["limit"] for r in data["cores"]] == ["unknown", "unknown", "found", "found", "unknown", "found"]
    assert "(-30)" in text and "(-50)" not in text


def test_old_state_without_floor_used_falls_back_to_the_config_floor():
    st = RunState(2, search_params(Config()))
    st.floor_used = None
    st.searches[0].final = st.final[0] = 50
    st.searches[1].final = st.final[1] = 30
    assert st.capped_cores() == [0]


def test_floor_changed_in_config_while_searching_is_followed_on_resume(tmp_path):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, trim_enabled=False)
    sim = SimCPU([60] * 4, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real, n = hw.stress, {"n": 0}

    class Stop:
        def run(self, cpus, seconds, label, profile="heavy"):
            n["n"] += 1
            if n["n"] > 2:
                raise KeyboardInterrupt
            return real.run(cpus, seconds, label, profile=profile)

    hw.stress = Stop()
    with pytest.raises(KeyboardInterrupt):
        Tuner(cfg, hw, store, log=quiet).run()
    assert store.load(search_params(cfg)).floor_used == 50
    cfg.floor = 40
    st = run_with_reboots(cfg, sim, store, log=quiet)
    assert st.floor_used == 40 and st.capped_cores() == [0, 1, 2, 3] and all(a == 40 for a in st.final.values())


# ----------------------------------------------------------------------------- ayar dosyası
def test_toml_syntax_error_is_a_config_error_with_advice(tmp_path, capsys):
    """En olası yazım hatası: Windows yolu çift tırnakla. Ham TOMLDecodeError izi yerine anlaşılır hata."""
    cfg = write_cfg(tmp_path, raw=b'[paths]\ncorecycler_dir = "C:\\Users\\PC\\CoreCycler"\n')
    with pytest.raises(ConfigError, match="tek tırnak"):
        load_config(cfg)
    assert cli.main(["--config", cfg, "--lang", "tr", "status"]) == 2
    assert "Ayar hatası" in capsys.readouterr().out


def test_non_utf8_config_is_a_config_error(tmp_path):
    cfg = write_cfg(tmp_path, raw="# çekirdek ayarı\n[search]\nmargin = 2\n".encode("cp1254"))
    with pytest.raises(ConfigError, match="UTF-8"):
        load_config(cfg)


def test_config_with_utf8_bom_is_accepted(tmp_path):
    cfg = write_cfg(tmp_path, raw=b'\xef\xbb\xbf[ui]\nlanguage = "en"\n[search]\nmargin = 3\n')
    assert load_config(cfg).margin == 3
    assert i18n.peek_config_language(cfg) == "en"


@pytest.mark.parametrize("line", ['floor = "40"', "margin = 2.5", "tests = \"SFTv4\"", "seconds_per_test = true",
                                  "smt = 1", "mode = 24", "trim_enabled = \"yes\""])
def test_wrong_value_type_is_a_config_error_not_a_traceback(tmp_path, line):
    with pytest.raises(ConfigError, match=line.split(" ")[0]):
        load_config(write_cfg(tmp_path, raw=(line + "\n").encode("utf-8")))


def test_right_value_types_load(tmp_path):
    cfg = load_config(write_cfg(tmp_path, raw=b'smt = false\ncores = 12\ncore_order = [1, 0]\nmode = "x"\nfloor = 44\n'))
    assert (cfg.smt, cfg.cores, cfg.core_order, cfg.mode, cfg.floor) == (False, 12, [1, 0], "x", 44)


def test_explicit_config_path_that_does_not_exist_is_an_error(tmp_path, capsys):
    """`--config confg.toml` (yazım hatası) sessizce varsayılan ayarlarla ve başka bir veri klasörüyle çalışıyordu."""
    missing = str(tmp_path / "confg.toml")
    with pytest.raises(ConfigError, match="bulunamadı"):
        load_config(missing)
    assert cli.main(["--config", missing, "--lang", "tr", "status"]) == 2
    assert load_config(None).floor == 50                    # yol verilmediyse varsayılanlar (değişmedi)


def test_only_floor_written_does_not_trip_over_the_default_start_co(tmp_path):
    """floor = 15 yazıp start_co'yu otomatik bırakan kullanıcı 'start_co 0..floor arasında olmalı' hatası alıyordu."""
    cfg = load_config(write_cfg(tmp_path, raw=b"[search]\nfloor = 15\n"))
    assert (cfg.floor, cfg.start_co) == (15, 15)
    with pytest.raises(ConfigError, match="start_co"):       # açıkça yazılan hatalı değer yine reddedilir
        load_config(write_cfg(tmp_path, raw=b"[search]\nfloor = 15\nstart_co = 20\n"))


@pytest.mark.parametrize("bad", [{"validate_backoff": 0}, {"validate_backoff": -2}, {"allcore_backoff": 0},
                                 {"max_crashes_per_core": 0}, {"max_consecutive_crashes": 0},
                                 {"max_unattributed_reboots": 0}, {"allcore_minutes": 0}, {"allcore_max_rounds": -1},
                                 {"resume_delay_seconds": -1}, {"cores": -1}])
def test_values_that_would_loop_or_halt_forever_are_rejected(bad):
    """validate_backoff = 0: kalan doğrulama testi aynı değerde sonsuza kadar tekrarlanırdı; allcore_backoff = 0 sıfıra
    bölerdi; max_consecutive_crashes = 0 her açılışta 'durduruldu' derdi."""
    with pytest.raises(ConfigError):
        Config(**bad).validate()
    Config().validate()


@pytest.mark.parametrize("order", [[0, 1, 2], [0, 1, 2, 3, 4, 5, 6, 8], [0, 0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 4, 5, 6, "7"]])
def test_core_order_must_cover_every_core_exactly_once(tmp_path, order):
    """Eksik çekirdek hiç aranmıyor, arama bitince `-None` ile çöküyordu."""
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, core_order=order)
    sim = SimCPU([30] * 8, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    with pytest.raises(ConfigError, match="core_order"):
        run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=quiet)
    assert not (tmp_path / "state.json").exists()            # hiçbir şeye başlanmadı


def test_core_order_permutation_is_followed(tmp_path):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, core_order=[3, 1, 2, 0])
    sim = SimCPU([30] * 4, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=quiet)
    assert st.stage == STAGE_DONE and sorted(st.final) == [0, 1, 2, 3]
    first_round = [row[1][0] for row in sim.log[:4]]
    assert first_round == [3, 1, 2, 0]


# ----------------------------------------------------------------------------- durum dosyası
@pytest.mark.parametrize("content", ['{"version": 1, "n_cores": 16', '{"version": 99}', '{"version": 1}', "[]", ""])
def test_unreadable_state_file_is_a_tool_error_with_advice(tmp_path, capsys, content):
    cfg = write_cfg(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "state.json").write_text(content, encoding="utf-8")
    with pytest.raises(ToolError, match="run --fresh"):
        StateStore(data / "state.json").load(search_params(Config()))
    for command in ("status", "report"):
        assert cli.main(["--config", cfg, "--lang", "tr", command]) == 4
        assert "Araç hatası" in capsys.readouterr().out


def test_fresh_run_gets_past_a_corrupt_state_file(tmp_path, capsys):
    cfg = write_cfg(tmp_path)
    sim_dir = tmp_path / "data_sim"
    sim_dir.mkdir()
    (sim_dir / "state.json").write_text("{bozuk", encoding="utf-8")
    assert cli.main(["--config", cfg, "run", "--simulate", "--yes", "--seed", "3"]) == 4
    assert cli.main(["--config", cfg, "run", "--simulate", "--yes", "--seed", "3", "--fresh"]) == 0
    assert list(sim_dir.glob("state.bak*"))                  # eski dosya saklandı


# ----------------------------------------------------------------------------- --quick devamda korunur
def interrupted_run(data_dir: Path, cfg: Config) -> StateStore:
    """16 çekirdekli simülasyonda (CLI'nin `--simulate` düzeni) üç testten sonra kesilmiş bir çalışma bırakır."""
    sim = SimCPU([30] * 16, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    store = StateStore(data_dir / "state.json")
    hw = sim.hardware()
    real, n = hw.stress, {"n": 0}

    class Stop:
        def run(self, cpus, seconds, label, profile="heavy"):
            n["n"] += 1
            if n["n"] > 3:
                raise KeyboardInterrupt
            return real.run(cpus, seconds, label, profile=profile)

    hw.stress = Stop()
    with pytest.raises(KeyboardInterrupt):
        Tuner(cfg, hw, store, log=quiet).run()
    return store


def resumed_settings(tmp_path, monkeypatch, *extra) -> dict:
    """`run --simulate` ile devam edildiğinde orkestratöre giden ayarları yakalar (çalıştırmadan)."""
    import pbo_tuner.sim as simmod
    seen = {}

    def fake(cfg, sim, store, **kw):
        seen.update(sec=cfg.seconds_per_test, confirm=cfg.confirm_cycles, allcore=cfg.allcore_minutes)
        return None

    monkeypatch.setattr(simmod, "run_with_reboots", fake)
    assert cli.main(["--config", write_cfg(tmp_path), "--lang", "tr", "run", "--simulate", "--yes", *extra]) == 3
    return seen


def test_quick_run_resumed_without_the_flag_keeps_its_short_tests(tmp_path, monkeypatch, capsys):
    """Otomatik devam (resume.bat) `--quick` taşımaz: hızlı deneme çökmeden sonra uzun testlerle sürüyordu."""
    data = tmp_path / "data_sim"
    store = interrupted_run(data, quick_preset(Config(data_dir=str(data), measure_boost=False)))
    saved = store.load(search_params(Config()))
    assert saved.quick is True and saved.stage == STAGE_SEARCH
    assert resumed_settings(tmp_path, monkeypatch) == {"sec": 10, "confirm": 2, "allcore": 5}
    assert "--quick" in capsys.readouterr().out               # kullanıcıya neden kısa test koştuğu söylenir


def test_normal_run_is_not_turned_into_a_quick_one_on_resume(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data_sim"
    store = interrupted_run(data, Config(data_dir=str(data), measure_boost=False))
    assert store.load(search_params(Config())).quick is False
    assert resumed_settings(tmp_path, monkeypatch) == {"sec": 20, "confirm": 5, "allcore": 10}
    assert "--quick" not in capsys.readouterr().out
    assert resumed_settings(tmp_path, monkeypatch, "--quick")["sec"] == 10          # açıkça istenirse eskisi gibi


def test_quick_state_does_not_shorten_the_light_tests_of_lowload(tmp_path, monkeypatch, capsys):
    """Hızlı denemenin ardından `lowload`: hafif testlerin süresi (y-cruncher SecondsPerTest) config'teki gibi kalır."""
    data = tmp_path / "data_sim"
    store = interrupted_run(data, quick_preset(Config(data_dir=str(data), measure_boost=False)))
    st = store.load(search_params(Config()))
    st.stage = "lowload"
    store.save(st)
    assert resumed_settings(tmp_path, monkeypatch)["sec"] == 20
    assert "--quick" not in capsys.readouterr().out


def test_normal_run_continued_with_quick_is_remembered_as_quick(tmp_path):
    """`run --quick` ile sürdürülen normal çalışma: sonraki otomatik devam uzun testlere geri dönmesin."""
    data = tmp_path / "d"
    store = interrupted_run(data, Config(data_dir=str(data), measure_boost=False))
    assert store.load(search_params(Config())).quick is False
    sim = SimCPU([30] * 16, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    Tuner(quick_preset(Config(data_dir=str(data), measure_boost=False)), sim.hardware(), store, log=quiet).startup()
    assert store.load(search_params(Config())).quick is True


def test_share_still_works_when_the_state_file_is_unreadable(tmp_path, capsys):
    cfg = write_cfg(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "state.json").write_text("{bozuk", encoding="utf-8")
    assert cli.main(["--config", cfg, "--lang", "tr", "share", "--no-open"]) == 0
    out = capsys.readouterr().out
    assert "Araç hatası" in out and "### PBO AutoTuner results report" in out and "No saved run yet" in out


def test_state_file_without_quick_key_loads_as_a_normal_run(tmp_path):
    import json
    data = tmp_path / "d"
    store = interrupted_run(data, quick_preset(Config(data_dir=str(data), measure_boost=False)))
    d = json.loads(store.path.read_text(encoding="utf-8"))
    assert d.pop("quick") is True
    store.path.write_text(json.dumps(d), encoding="utf-8")
    assert store.load(search_params(Config())).quick is False


# ----------------------------------------------------------------------------- resume.bat / run_as_admin.bat
def test_resume_bat_text_is_crlf_utf8_and_sets_the_code_page_before_any_path():
    """Eski hali metin kipinde "\\r\\n" yazıyordu (dosyada CR CR LF) ve yerel kod sayfasını kullanıyordu: Türkçe harfli
    yol (ör. C:\\Users\\Gökhan\\...) cmd'nin OEM kod sayfasında bozuluyor, otomatik devam hiç başlamıyordu."""
    root = r"C:\Users\Gökhan Şen\pbo 100%"
    py = r"C:\Users\Gökhan Şen\AppData\Local\Programs\Python\Python312\python.exe"
    text = cli.resume_bat_text(root, py, None)
    lines = text.split("\r\n")
    assert lines[:2] == ["@echo off", "chcp 65001 >nul"] and lines[-1] == ""
    assert "\n" not in text.replace("\r\n", "") and "\r\r" not in text
    assert lines[2] == 'cd /d "C:\\Users\\Gökhan Şen\\pbo 100%%"'              # % ikilenir
    assert lines[3] == f'"{py}" -m pbo_tuner run --auto-resume'
    assert lines[4] == "if errorlevel 1 pause"
    assert text.encode("utf-8").decode("utf-8") == text


def test_resume_bat_text_passes_the_config_path(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    text = cli.resume_bat_text(tmp_path, "python.exe", str(cfg))
    assert f'--auto-resume --config "{cfg.resolve()}"\r\n' in text


def test_install_autostart_writes_the_bat_as_bytes_without_doubled_cr(tmp_path, monkeypatch, capsys):
    calls = []
    bat = tmp_path / "resume.bat"
    monkeypatch.setattr(cli, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(cli, "_bat_path", lambda: bat)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    assert cli.install_autostart(None) == 0
    data = bat.read_bytes()
    assert data.startswith(b"@echo off\r\nchcp 65001 >nul\r\ncd /d ") and b"\r\r\n" not in data
    assert b"\n" not in data.replace(b"\r\n", b"") and data.endswith(b"if errorlevel 1 pause\r\n")
    assert len(calls) == 1 and calls[0][0] == "schtasks" and f'"{bat}"' in calls[0]


def test_run_as_admin_switches_to_utf8_before_reading_python_path():
    """python_path.txt UTF-8 yazılır; `set /p` onu konsolun kod sayfasıyla okur. chcp 65001 olmadan ASCII dışı harfli
    Python yolu (kullanıcı adı) bulunamıyordu (Windows'ta denendi: 857/437/850/1254 kod sayfalarının hepsinde)."""
    text = (ROOT / "run_as_admin.bat").read_text(encoding="ascii")
    assert "chcp 65001 >nul" in text
    assert text.index("chcp 65001 >nul") < text.index("set /p PY=<python_path.txt")


# ----------------------------------------------------------------------------- boost ölçümünde (hafif yük) çökme
def crashing_boost(sim, crash_if):
    """`sim.hardware()` artık, `crash_if(çekirdek, a)` doğruysa ölçüm sırasında sistemi çökerten bir boost ölçer verir.
    Dönen listeye her ölçüm (çekirdek, a) olarak işlenir."""
    real, make, seen = sim.boost, sim.hardware, []

    class Meter:
        def measure(self, cpu):
            core = cpu // 2 if sim.smt else cpu
            a = -sim.offsets[core]
            seen.append((core, a))
            if crash_if(core, a):
                sim.crashes += 1
                raise SimulatedCrash()
            return real.measure(cpu)

    def hardware():
        hw = make()
        hw.boost = Meter()
        return hw

    sim.hardware = hardware
    return seen


def test_crash_while_measuring_a_trim_level_backs_the_core_off_instead_of_looping(tmp_path):
    """Kırpma ölçümü çökme izi bırakmıyordu: aynı seviye her açılışta yeniden deneniyor, üç çökmeden sonra araç
    'test dışı beklenmedik yeniden başlatma' diyerek RAM/PSU'yu suçlayıp duruyor, `run --force` da aynı döngüye
    giriyordu. Artık düşük yük testindeki gibi: çöken çekirdek geri çekilir ve kırpılmaz (sınırı görülmüştür)."""
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1)
    sim = SimCPU([60, 60, 60, 60, 30, 30, 30, 30], seed=1, crash_prob=0.0, band=0, allcore_penalty=0, fmax=[5550] * 8)
    crashing_boost(sim, lambda core, a: a >= 50)          # ağır testleri -50'de geçen çekirdekler hafif yükte çöküyor
    logs = []
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=logs.append)
    assert st is not None and st.stage == STAGE_DONE and not st.halted
    assert [st.final[c] for c in range(8)] == [48, 48, 48, 48, 28, 28, 28, 28]
    assert st.total_crashes == 4 and st.unattributed_reboots == 0 and st.pending is None
    assert not any("beklenmedik yeniden başlatma" in l for l in logs)
    assert any("ÇÖKME tespit edildi: trim testi, çekirdek 0, CO -50" in l for l in logs)
    assert not st.trim["cores"] and not st.trim["from"] and st.capped_cores() == []     # sınır görüldü: "bulundu"
    warns = [n for n in st.notes if is_warning(n)]
    assert len(warns) == 4 and all("lowload" in w for w in warns)
    text, data = build_report(st, cfg)
    assert all(r["limit"] == "found" for r in data["cores"]) and "UYARILAR:" in text
    assert "MHz'e göre kırpma" not in text                 # kırpılan çekirdek kalmadı
    assert sim.offsets == [0] * 8


def test_crash_at_a_shallower_trim_level_backs_off_below_that_level(tmp_path):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1)
    sim = SimCPU([60, 60, 30, 30], seed=1, crash_prob=0.0, band=0, allcore_penalty=0, fmax=[5550] * 4)
    crashing_boost(sim, lambda core, a: core == 0 and a == 40)       # -50 ölçüldü, -40'ta çöktü
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=quiet)
    assert st.stage == STAGE_DONE and st.final[0] == 38 and st.total_crashes == 1
    assert st.trim["cores"] == [1] and st.final[1] == st.trim["chosen"][1] < 50          # öteki çekirdek kırpıldı
    assert st.capped_cores() == [1]


def test_crash_during_the_final_boost_measurement_backs_off_and_measures_again(tmp_path):
    """Aynı açık son ölçümde de vardı: nihai değerlerle hafif yük, çökme izi yok."""
    cfg = Config(data_dir=str(tmp_path), measure_boost=True, allcore_minutes=1, trim_enabled=False)
    sim = SimCPU([40] * 4, seed=1, crash_prob=0.0, band=0, allcore_penalty=0)
    seen = crashing_boost(sim, lambda core, a: core == 2 and a >= 36)
    logs = []
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=logs.append)
    assert st is not None and st.stage == STAGE_DONE
    assert st.final == {0: 38, 1: 38, 2: 34, 3: 38}
    assert st.total_crashes == 2 and st.unattributed_reboots == 0 and st.pending is None
    assert st.final_mhz[2] == 5300 - 20 * 2 + 12 * 34 and all(st.final_mhz[c] for c in range(4))
    assert [x for x in seen if x[0] == 2 and x[1] > 0] == [(2, 38), (2, 36), (2, 34)]     # geri çekip yeniden ölçtü
    assert seen.count((0, 38)) == 1                          # ölçülmüş çekirdekler yeniden ölçülmedi
    assert sum(1 for n in st.notes if is_warning(n)) == 2 and sim.offsets == [0] * 4


def test_boost_measurements_under_co_leave_a_crash_trace_first(tmp_path):
    import json
    cfg = Config(data_dir=str(tmp_path), measure_boost=True, allcore_minutes=1)
    sim = SimCPU([60, 30], seed=1, crash_prob=0.0, band=0, allcore_penalty=0, fmax=[5550] * 2)
    hw = sim.hardware()
    real, traces = hw.boost, []

    class Spy:
        def measure(self, cpu):
            traces.append((json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["pending"],
                           list(sim.offsets)))
            return real.measure(cpu)

    hw.boost = Spy()
    st = Tuner(cfg, hw, StateStore(tmp_path / "state.json"), log=quiet).run()
    assert st.stage == STAGE_DONE and st.pending is None
    stock = [p for p, offsets in traces if not any(offsets)]
    assert stock and all(p is None for p in stock)           # CO 0'da (baseline) iz gerekmez
    under_co = [(p, offsets) for p, offsets in traces if any(offsets)]
    assert under_co and all(p is not None and -offsets[p["core"]] == p["a"] for p, offsets in under_co)
    assert {p["kind"] for p, _ in under_co} == {"trim", "final"}
    assert all(p["ts"] is not None and p["level"] == p["kind"] for p, _ in under_co)


def test_ctrl_c_during_a_trim_measurement_leaves_no_crash_trace(tmp_path):
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1)
    sim = SimCPU([60, 60, 30, 30], seed=1, crash_prob=0.0, band=0, allcore_penalty=0, fmax=[5550] * 4)
    store = StateStore(tmp_path / "state.json")
    hw = sim.hardware()
    real, n = hw.boost, {"n": 0}

    class Stop:
        def measure(self, cpu):
            n["n"] += 1
            if n["n"] == 5:
                raise KeyboardInterrupt
            return real.measure(cpu)

    hw.boost = Stop()
    with pytest.raises(KeyboardInterrupt):
        Tuner(cfg, hw, store, log=quiet).run()
    mid = store.load(search_params(cfg))
    assert mid.stage == "trim" and mid.pending is None and mid.clean_exit is True and sim.offsets == [0] * 4
    st = run_with_reboots(cfg, sim, store, log=quiet)        # yeniden başlatma yok: çökme sayılmaz, kırpma tamamlanır
    assert st.stage == STAGE_DONE and st.total_crashes == 0 and sorted(st.trim["chosen"]) == [0, 1]


# ----------------------------------------------------------------------------- çökme iletisi, WHEA okuma, Ctrl+C
def test_allcore_crash_message_does_not_say_core_none(tmp_path):
    """Gerçek günlük: '!! CRASH detected: allcore test, core None, CO -0.'"""
    cfg = Config(data_dir=str(tmp_path), measure_boost=False, allcore_minutes=1, lowload_seconds=60, idle_minutes=0)
    allcore = [99] * 16
    allcore[7] = 42
    sim = SimCPU([48] * 16, seed=1, crash_prob=1.0, band=0, allcore_penalty=1, allcore_limits=allcore)
    logs = []
    st = run_with_reboots(cfg, sim, StateStore(tmp_path / "state.json"), log=logs.append)
    crash_lines = [l for l in logs if "ÇÖKME tespit edildi: allcore" in l]
    assert crash_lines and all("tüm çekirdekler" in l and "None" not in l and "CO -0" not in l for l in crash_lines)
    assert any("çökme: allcore (tüm çekirdekler)" in n for n in st.notes) and not any("None" in n for n in st.notes)
    assert any("ÇÖKME tespit edildi: search testi, çekirdek" in l for l in logs)        # çekirdekli ileti değişmedi


def test_whea_reader_turns_timeouts_and_garbage_into_tool_errors(monkeypatch):
    from datetime import datetime, timezone
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(hwmod.subprocess, "run", timeout)
    with pytest.raises(ToolError, match="wevtutil"):
        WheaReader().events_since(since)
    seen = {}

    def garbage(cmd, **kw):
        seen.update(kw)
        return types.SimpleNamespace(returncode=0, stdout="<Event><System>", stderr="")

    monkeypatch.setattr(hwmod.subprocess, "run", garbage)
    with pytest.raises(ToolError, match="wevtutil"):
        WheaReader().events_since(since)
    assert seen.get("errors") == "replace"                    # ASCII dışı bilgisayar adı çözme hatası vermesin


def test_ctrl_c_inside_a_command_exits_cleanly(monkeypatch, capsys):
    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_status", interrupted)
    assert cli.main(["--lang", "tr", "status"]) == 130
    assert "İptal edildi." in capsys.readouterr().out
