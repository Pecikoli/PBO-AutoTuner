"""`share` komutu: anonim rapor, kişisel bilgi sızıntısı, onay akışı. Ağa çıkılmaz (tarayıcı sahte)."""
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pbo_tuner import __main__ as cli
from pbo_tuner import i18n, share
from pbo_tuner.config import Config
from pbo_tuner.state import RunState, StateStore
from pbo_tuner.tuner import search_params

IDENT = ("AMD64 Family 26 Model 68 Stepping 0", "AMD Ryzen 9 9950X3D 16-Core Processor")
NAMES = {"home": r"C:\Users\Zeynep", "project": r"C:\Users\Zeynep\Desktop\pbo_autotuner", "user": "Zeynep",
         "host": "ZEYNEP-PC"}


def make_cfg(tmp_path):
    return Config(data_dir=str(tmp_path / "data"))


def make_state(cfg, stage="done", warnings=True):
    st = RunState(4, search_params(cfg))
    st.stage, st.final, st.total_crashes = stage, {0: 29, 1: 44, 2: 0, 3: 50}, 3
    if warnings:
        st.note("WARNING: the system crashed while idle; CO values may be unstable at idle")
    st.note("crash: search core=1 CO=-45")
    return st


def body_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["body"][0]


# ------------------------------------------------------------------ redact
def test_redact_removes_paths_user_and_host_case_insensitively():
    text = (r"smu: C:\Users\Zeynep\Desktop\pbo_autotuner\CoreCycler\tools\x.exe | home=c:\users\zeynep\AppData"
            r" | host ZEYNEP-pc user zeynep | fwd C:/Users/Zeynep/x")
    out = share.redact(text, **NAMES)
    for secret in ("Zeynep", "ZEYNEP", "zeynep"):
        assert secret not in out
    assert "<project>" in out and "<user>" in out and "<host>" in out


def test_redact_generic_windows_profile_path_even_without_known_names():
    out = share.redact(r"error in C:\Users\Baska Kisi\x" + "\n" + r"and D:\Users\Ali\y")
    assert "Ali" not in out and r"C:\Users\<user>" in out and r"D:\Users\<user>" in out


def test_redact_does_not_mangle_words_that_merely_contain_the_name_and_skips_tiny_names():
    out = share.redact("Zeynepler gitti; PC ok", user="Zeynep", host="PC")      # 'PC' çok kısa: dokunulmaz
    assert "Zeynepler" in out and "PC ok" in out
    assert share.redact("Zeynep olmadan", user="Zeynep") == "<user> olmadan"


def test_redact_with_nothing_to_hide_is_identity():
    assert share.redact("hello world") == "hello world"


# ------------------------------------------------------------------ collect_info / format_report
def test_collect_info_detects_generation_and_preset(tmp_path):
    info = share.collect_info(make_cfg(tmp_path), None, identity_reader=lambda: IDENT)
    assert info["cpu_name"] == IDENT[1] and info["generation"] == "zen5"
    assert "24-ZN5 ~ Komari" in info["preset"] and info["tool_version"]


def test_collect_info_survives_an_unreadable_cpu(tmp_path):
    def boom():
        raise OSError("registry yok")

    info = share.collect_info(make_cfg(tmp_path), None, identity_reader=boom)
    assert info["cpu_name"] is None and info["generation"] is None
    assert "unknown" in share.format_report(info)


def test_format_report_full_run_has_table_warnings_and_copy_notice(tmp_path):
    cfg = make_cfg(tmp_path)
    st = make_state(cfg)
    rows = [{"core": c, "co": -st.final[c], "search_result": -st.final[c], "crashes": c, "mhz_delta": 40 + c}
            for c in range(4)]
    text = share.format_report(share.collect_info(cfg, st, lambda: IDENT), st, rows, doctor="[ OK ] Windows")
    assert "| 0 | -29 |" in text and "Total crashes: 3" in text and "Warnings: 1" in text
    assert "crashed while idle" in text and "Do not copy them to other processors" in text
    assert "```\n[ OK ] Windows\n```" in text and "Stage: done\n" in text


def test_format_report_can_omit_the_per_core_values(tmp_path):
    cfg = make_cfg(tmp_path)
    st = make_state(cfg)
    rows = [{"core": 0, "co": -29, "search_result": -29, "crashes": 0, "mhz_delta": 5}]
    text = share.format_report(share.collect_info(cfg, st, lambda: IDENT), st, rows, include_values=False)
    assert "| 0 |" not in text and "Omitted by the user" in text and "Warnings:" in text


def test_format_report_marks_unfinished_runs_as_provisional_and_handles_no_run(tmp_path):
    cfg = make_cfg(tmp_path)
    info = share.collect_info(cfg, None, lambda: IDENT)
    assert "provisional" in share.format_report(info, make_state(cfg, stage="search"))
    assert "No saved run yet" in share.format_report(info, None)


# ------------------------------------------------------------------ prepare / adres
def test_prepare_builds_a_prefilled_issue_url_that_round_trips(tmp_path):
    cfg = make_cfg(tmp_path)
    st = make_state(cfg)
    pre = share.prepare(cfg, st, identity_reader=lambda: IDENT, names=NAMES)
    parsed = urlparse(pre["url"])
    assert pre["url"].startswith(share.NEW_ISSUE_URL + "?") and parsed.netloc == "github.com"
    q = parse_qs(parsed.query)
    assert q["title"][0] == "[results] AMD Ryzen 9 9950X3D 16-Core Processor (zen5)"
    assert q["body"][0] == pre["report"] and q["labels"] == ["results"]
    assert len(pre["url"]) <= share.MAX_URL_LEN and pre["trimmed"] is False


def test_prepare_trims_a_huge_doctor_output_and_points_to_the_saved_file(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.data_path.mkdir(parents=True)
    (cfg.data_path / share.DOCTOR_FILE).write_text("# doctor\n" + "[ OK ] satir uzun uzun uzun\n" * 400, encoding="utf-8")
    pre = share.prepare(cfg, make_state(cfg), identity_reader=lambda: IDENT, names=NAMES)
    assert pre["trimmed"] is True and len(pre["url"]) <= share.MAX_URL_LEN
    assert "satir uzun" in pre["report"]                                   # tam rapor yine de dosyaya yazılır
    assert "satir uzun" not in body_of(pre["url"]) and "share_report.txt" in body_of(pre["url"])


def test_prepare_never_leaks_personal_names_anywhere(tmp_path):
    """Sızıntı testi: doctor çıktısında ve nottaki yollarda kullanıcı/bilgisayar adı geçse bile hiçbiri çıkmamalı."""
    cfg = Config(data_dir=r"C:\Users\Zeynep\Desktop\pbo_autotuner\data")
    cfg.data_dir = str(tmp_path / "data")
    cfg.data_path.mkdir(parents=True)
    (cfg.data_path / share.DOCTOR_FILE).write_text(
        "# doctor\n[ OK ] ryzen-smu-cli.exe - C:\\Users\\Zeynep\\Desktop\\pbo_autotuner\\CoreCycler\\tools\\a.exe\n"
        "[FAIL ] log - C:/Users/zeynep/AppData/x ZEYNEP-PC\n", encoding="utf-8")
    st = make_state(cfg)
    st.note(r"WARNING: wrapper blocked at C:\Users\Zeynep\Desktop\x on ZEYNEP-PC")
    pre = share.prepare(cfg, st, identity_reader=lambda: IDENT, names=NAMES)
    haystack = pre["report"] + pre["url"] + body_of(pre["url"]) + pre["title"]
    for secret in ("Zeynep", "ZEYNEP", "zeynep"):
        assert secret not in haystack, secret


# ------------------------------------------------------------------ doctor çıktısı kaydı
def test_save_and_read_doctor_roundtrip_and_never_raises(tmp_path):
    cfg = make_cfg(tmp_path)
    assert share.read_doctor(cfg) is None
    share.save_doctor(cfg, ["[ OK ] a", "[FAIL ] b - x"])
    text = share.read_doctor(cfg)
    assert text.startswith("# doctor, ") and "[FAIL ] b - x" in text

    class Bad:
        data_path = Path("/proc/yazilamaz/yok")
    share.save_doctor(Bad(), ["x"])                                        # hata vermemeli


def cli_cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f"[paths]\ndata_dir = '{tmp_path / 'data'}'\n", encoding="utf-8")
    return str(p)


def test_doctor_command_records_its_output_for_share(tmp_path, capsys):
    cfg = cli_cfg(tmp_path)
    assert cli.main(["--config", cfg, "--lang", "en", "doctor"]) == 1       # Linux'ta Windows denetimi kalır: beklenen
    out = capsys.readouterr().out
    saved = (tmp_path / "data" / share.DOCTOR_FILE).read_text(encoding="utf-8")
    assert "Windows" in out and "Windows" in saved and "FAIL" in saved


# ------------------------------------------------------------------ share komutu
@pytest.fixture
def browser(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    return opened


def answer(monkeypatch, *replies):
    it, prompts = iter(replies), []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(it))
    return prompts


def test_share_asks_first_and_opens_the_prefilled_page_only_on_explicit_yes(tmp_path, monkeypatch, browser, capsys):
    cfg = cli_cfg(tmp_path)
    answer(monkeypatch, "e")
    assert cli.main(["--config", cfg, "share"]) == 0
    out = capsys.readouterr().out
    assert len(browser) == 1 and browser[0].startswith(share.NEW_ISSUE_URL)
    assert "TAMAMIDIR" in out and "HERKESE AÇIK" in out and "### PBO AutoTuner results report" in out
    assert (tmp_path / "data" / share.SHARE_FILE).read_text(encoding="utf-8").startswith("### PBO AutoTuner results report")


@pytest.mark.parametrize("reply", ["", "h", "hayır", "n", "no", "belki"])
def test_share_default_and_any_other_answer_means_no(tmp_path, monkeypatch, browser, capsys, reply):
    answer(monkeypatch, reply)
    assert cli.main(["--config", cli_cfg(tmp_path), "share"]) == 0
    assert browser == [] and "Hiçbir şey gönderilmedi" in capsys.readouterr().out


def test_share_eof_on_prompt_means_no(tmp_path, monkeypatch, browser):
    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["--config", cli_cfg(tmp_path), "share"]) == 0 and browser == []


def test_share_no_open_never_prompts_or_opens(tmp_path, monkeypatch, browser, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("sormamalıydı"))
    assert cli.main(["--config", cli_cfg(tmp_path), "--lang", "en", "share", "--no-open"]) == 0
    out = capsys.readouterr().out
    assert browser == [] and share.NEW_ISSUE_URL in out and "COMPLETE content" in out


def test_share_no_values_leaves_the_table_out(tmp_path, monkeypatch, browser):
    cfg = Config(data_dir=str(tmp_path / "data"))
    StateStore(cfg.data_path / "state.json").save(make_state(cfg))
    answer(monkeypatch, "evet")
    assert cli.main(["--config", cli_cfg(tmp_path), "share", "--no-values"]) == 0
    assert "Omitted by the user" in body_of(browser[0]) and "| 0 |" not in body_of(browser[0])


def test_share_includes_the_per_core_table_for_a_finished_run(tmp_path, monkeypatch, browser):
    cfg = Config(data_dir=str(tmp_path / "data"))
    StateStore(cfg.data_path / "state.json").save(make_state(cfg))
    answer(monkeypatch, "y")
    assert cli.main(["--config", cli_cfg(tmp_path), "share"]) == 0
    body = body_of(browser[0])
    assert "| 0 | -29 |" in body and "Stage: done" in body and "crashed while idle" in body


def test_share_prints_the_url_when_the_browser_cannot_be_opened(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: False)
    answer(monkeypatch, "e")
    assert cli.main(["--config", cli_cfg(tmp_path), "--lang", "en", "share"]) == 0
    assert "could not be opened" in capsys.readouterr().out


def test_share_english_ui_and_prompt_language(tmp_path, monkeypatch, browser, capsys):
    prompts = answer(monkeypatch, "", "")
    assert cli.main(["--config", cli_cfg(tmp_path), "--lang", "en", "share"]) == 0
    out = capsys.readouterr().out
    assert "Nothing was sent" in out and "COMPLETE content" in out and browser == []
    assert prompts == ["Open the GitHub page in the browser? [y/N] "]
    assert cli.main(["--config", cli_cfg(tmp_path), "--lang", "tr", "share"]) == 0
    assert prompts[1] == "Tarayıcıda GitHub sayfasını açayım mı? [e/H] "


def test_share_is_listed_last_in_the_menu():
    assert cli.MENU[-1][1] == ["share"] and len(cli.MENU) == 12
    i18n.set_language("en")
    assert "Share results" in i18n.tr(cli.MENU[-1][0])
