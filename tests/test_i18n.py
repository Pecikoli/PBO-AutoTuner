"""Dil desteği: sözlüğün eksiksizliği, dil seçim önceliği ve İngilizce çıktının gerçekten İngilizce olması."""

import ast
import pathlib
import re
import string

import pytest

from pbo_tuner import __main__ as cli
from pbo_tuner import i18n
from pbo_tuner.config import Config, ConfigError, load_config
from pbo_tuner.lang_en import EN

PKG = pathlib.Path(__file__).resolve().parent.parent / "pbo_tuner"
TURKISH_LETTERS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
FIELD = re.compile(r"\{([^{}]*)\}")


def _call_name(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def _literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    return []


def source_keys():
    keys = set()
    for p in PKG.glob("*.py"):
        if p.name in ("lang_en.py", "i18n.py"):
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and _call_name(n) in ("tr", "mark") and n.args:
                keys.update(_literals(n.args[0]))
    return keys


def fields(text):
    """str.format alanları (ad + biçim). Yer tutucuların iki dilde aynı olduğunu denetlemek için."""
    return sorted(FIELD.findall(text))


# ----------------------------------------------------------------------------- sözlük
def test_every_source_string_has_an_english_translation():
    missing = sorted(k for k in source_keys() if k not in EN)
    assert not missing, f"İngilizce karşılığı eksik {len(missing)} metin, ilki: {missing[0]!r}"


def test_catalog_has_no_stale_entries():
    stale = sorted(k for k in EN if k not in source_keys())
    assert not stale, f"kodda artık olmayan sözlük girdisi: {stale[0]!r}"


def test_placeholders_and_edge_whitespace_match():
    for tr_text, en_text in EN.items():
        assert fields(tr_text) == fields(en_text), f"yer tutucular farklı: {tr_text!r} / {en_text!r}"
        assert tr_text[:len(tr_text) - len(tr_text.lstrip())] == en_text[:len(en_text) - len(en_text.lstrip())], tr_text
        assert tr_text[len(tr_text.rstrip()):] == en_text[len(en_text.rstrip()):], tr_text


def test_english_values_contain_no_turkish_letters():
    bad = [(k, v) for k, v in EN.items() if TURKISH_LETTERS.search(v)]
    assert not bad, f"İngilizce metinde Türkçe harf: {bad[0]!r}"


def test_format_strings_are_valid_for_their_placeholders():
    fmt = string.Formatter()
    for text in list(EN) + list(EN.values()):
        list(fmt.parse(text))       # bozuk {süslü parantez} varsa ValueError verir


def test_no_untranslated_turkish_literals_left_in_code():
    """Kullanıcıya görünecek yeni Türkçe metin `tr(...)` ya da `mark(...)` olmadan eklenmemeli."""
    offenders = []
    for p in sorted(PKG.glob("*.py")):
        if p.name == "lang_en.py":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        safe = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body:
                first = n.body[0]
                if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                    safe.add(id(first.value))
            if isinstance(n, ast.Call) and _call_name(n) in ("tr", "mark") and n.args:
                safe.update(id(m) for m in ast.walk(n.args[0]))
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in safe \
                    and TURKISH_LETTERS.search(n.value):
                offenders.append(f"{p.name}:{n.lineno}: {n.value[:60]!r}")
    assert not offenders, offenders[:5]


# ----------------------------------------------------------------------------- tr()
def test_tr_formats_in_both_languages():
    key = "Rapor yazıldı: {path}"
    i18n.set_language("tr")
    assert i18n.tr(key, path="x") == "Rapor yazıldı: x"
    i18n.set_language("en")
    assert i18n.tr(key, path="x") == "Report written: x"


def test_tr_falls_back_to_turkish_for_unknown_text():
    i18n.set_language("en")
    assert i18n.tr("katalogda olmayan {x}", x=1) == "katalogda olmayan 1"


def test_mark_does_not_translate():
    i18n.set_language("en")
    assert i18n.mark("Çıkış") == "Çıkış"
    assert i18n.tr(i18n.mark("Çıkış")) == "Exit"


def test_set_language_rejects_unknown_code():
    with pytest.raises(ValueError):
        i18n.set_language("de")


# ----------------------------------------------------------------------------- dil seçimi
def test_resolve_values(monkeypatch):
    assert i18n.resolve("tr") == "tr" and i18n.resolve("EN") == "en"
    monkeypatch.setattr(i18n, "system_language", lambda: "tr")
    assert i18n.resolve("auto") == "tr" and i18n.resolve(None) == "tr" and i18n.resolve("") == "tr"
    with pytest.raises(ValueError):
        i18n.resolve("fr")


@pytest.mark.parametrize("name,expected", [("tr-TR", "tr"), ("tr_TR.UTF-8", "tr"), ("en-US", "en"),
                                           ("en_GB.UTF-8", "en"), ("de-DE", "en"), ("", "en")])
def test_locale_name_mapping(name, expected):
    assert i18n._from_locale_name(name) == expected


def test_system_language_reads_environment_off_windows(monkeypatch):
    monkeypatch.setattr(i18n.os, "name", "posix")
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.system_language() == "en"
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.system_language() == "tr"
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")          # LC_ALL, LANG'dan önce gelir
    assert i18n.system_language() == "en"


class _FakeKernel32:
    def __init__(self, ui_lang, locale_name):
        self.ui_lang, self.locale_name = ui_lang, locale_name

    def GetUserDefaultUILanguage(self):
        return self.ui_lang

    def GetUserDefaultLocaleName(self, buf, size):
        if self.locale_name is None:
            return 0
        buf.value = self.locale_name
        return len(self.locale_name) + 1


class _FakeWindll:
    def __init__(self, **kw):
        self.kernel32 = _FakeKernel32(**kw)


@pytest.mark.parametrize("ui_lang,locale_name,expected", [
    (0x041F, "en-US", "tr"),        # ekran dili Türkçe, bölgesel ayar İngilizce: Türkçe
    (0x0409, "tr-TR", "tr"),        # ekran dili İngilizce, bölge Türkiye: Türkçe
    (0x0409, "en-US", "en"),
    (0x0407, "de-DE", "en"),
    (0x0409, None, "en"),           # yerel ad okunamadı
])
def test_windows_system_language(monkeypatch, ui_lang, locale_name, expected):
    import ctypes
    monkeypatch.setattr(i18n.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(ui_lang=ui_lang, locale_name=locale_name), raising=False)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.system_language() == expected


def test_windows_api_failure_falls_back_to_environment(monkeypatch):
    import ctypes

    class Broken:
        @property
        def kernel32(self):
            raise OSError("yok")

    monkeypatch.setattr(i18n.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", Broken(), raising=False)
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.system_language() == "tr"


def write_cfg(tmp_path, body):
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_priority_cli_over_env_over_config_over_system(monkeypatch, tmp_path):
    cfg = write_cfg(tmp_path, '[ui]\nlanguage = "en"\n')
    monkeypatch.setattr(i18n, "system_language", lambda: "tr")
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    assert i18n.init([], cfg) == "en"                                 # config, sistem dilinden önce
    assert i18n.init([], None) == "tr"                                # config yok: sistem dili
    monkeypatch.setenv(i18n.ENV_VAR, "tr")
    assert i18n.init([], cfg) == "tr"                                 # ortam değişkeni config'i geçer
    assert i18n.init(["--lang", "en"], cfg) == "en"                   # komut satırı hepsini geçer
    assert i18n.init(["--lang=en"], cfg) == "en"
    assert i18n.get_language() == "en"


def test_config_auto_follows_system(monkeypatch, tmp_path):
    cfg = write_cfg(tmp_path, '[ui]\nlanguage = "auto"\n')
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.init([], cfg) == "en"


def test_invalid_candidates_are_skipped_not_fatal(monkeypatch, tmp_path):
    cfg = write_cfg(tmp_path, '[ui]\nlanguage = "klingon"\n')
    monkeypatch.setenv(i18n.ENV_VAR, "xx")
    monkeypatch.setattr(i18n, "system_language", lambda: "en")
    assert i18n.init(["--lang", "zz"], cfg) == "en"                   # hepsi geçersiz: sistem dili


def test_peek_config_language_is_forgiving(tmp_path):
    assert i18n.peek_config_language(None) is None
    assert i18n.peek_config_language(str(tmp_path / "yok.toml")) is None
    assert i18n.peek_config_language(write_cfg(tmp_path, "bozuk = = =")) is None
    assert i18n.peek_config_language(write_cfg(tmp_path, 'language = "en"\n')) == "en"          # tablo dışında da olur
    assert i18n.peek_config_language(write_cfg(tmp_path, '[ui]\nlanguage = "tr"\n')) == "tr"


# ----------------------------------------------------------------------------- config
def test_config_accepts_language_and_validates_it(tmp_path):
    cfg = load_config(write_cfg(tmp_path, '[ui]\nlanguage = "en"\n'))
    assert cfg.language == "en"
    assert Config().language == "auto"
    with pytest.raises(ConfigError, match="language"):
        load_config(write_cfg(tmp_path, '[ui]\nlanguage = "klingon"\n'))


def test_config_error_message_is_translated():
    i18n.set_language("en")
    with pytest.raises(ConfigError, match="floor must be between 1 and 50"):
        Config(floor=99).validate()
    i18n.set_language("tr")
    with pytest.raises(ConfigError, match="floor 1..50 arasında olmalı"):
        Config(floor=99).validate()


# ----------------------------------------------------------------------------- uçtan uca
def sim_config(tmp_path):
    return write_cfg(tmp_path, f"[paths]\ndata_dir = '{tmp_path / 'data'}'\n")


def run_cli(args, capsys):
    code = cli.main(args)
    return code, capsys.readouterr().out


def test_english_simulated_run_is_fully_english(tmp_path, capsys):
    cfg = sim_config(tmp_path)
    code, out = run_cli(["--config", cfg, "--lang", "en", "run", "--simulate", "--yes", "--seed", "3"], capsys)
    assert code == 0
    assert "Stage 2/5" in out and "PASSED" in out and "Report written" in out
    assert "To enter in the BIOS" in out and "Final CO" in out
    leftovers = sorted({ch for ch in out if TURKISH_LETTERS.match(ch)})
    assert not leftovers, f"İngilizce çıktıda Türkçe harf: {leftovers}"
    report = (tmp_path / "data_sim" / "report.txt").read_text(encoding="utf-8")
    assert "result report" in report and not TURKISH_LETTERS.search(report)


def test_turkish_simulated_run_stays_turkish(tmp_path, capsys):
    cfg = sim_config(tmp_path)
    code, out = run_cli(["--config", cfg, "--lang", "tr", "run", "--simulate", "--yes", "--seed", "3"], capsys)
    assert code == 0
    assert "Aşama 2/5" in out and "GEÇTİ" in out and "Rapor yazıldı" in out and "BIOS'a girmek için" in out


def test_status_and_report_follow_language(tmp_path, capsys):
    run_cli(["--config", sim_config(tmp_path), "--lang", "en", "run", "--simulate", "--yes", "--seed", "3"], capsys)
    # `status`/`report` gerçek veri klasörünü okur; simülasyonun yazdığı klasöre çevirerek gerçek tabloları görürüz
    real = write_cfg(tmp_path, f"[paths]\ndata_dir = '{tmp_path / 'data_sim'}'\n")
    code, out = run_cli(["--config", real, "--lang", "en", "status"], capsys)
    assert code == 0 and "Stage: done" in out and "phase" in out and "stable" in out
    code, out = run_cli(["--config", real, "--lang", "en", "report"], capsys)
    assert code == 0 and "result report" in out and "Final CO" in out and not TURKISH_LETTERS.search(out)
    code, out = run_cli(["--config", real, "--lang", "tr", "status"], capsys)
    assert "Aşama: done" in out and "faz" in out
    code, out = run_cli(["--config", sim_config(tmp_path), "--lang", "en", "status"], capsys)
    assert out.strip() == "No saved run."          # data klasörü boş
    code, out = run_cli(["--config", sim_config(tmp_path), "--lang", "tr", "status"], capsys)
    assert out.strip() == "Kayıtlı çalışma yok."


def test_menu_and_help_follow_language(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")
    code, out = run_cli(["--lang", "en"], capsys)
    assert code == 0 and "Exit" in out and "Environment check (doctor)" in out and "Çıkış" not in out
    code, out = run_cli([], capsys)
    assert "Çıkış" in out and "Ortam kontrolü" in out
    with pytest.raises(SystemExit):
        cli.main(["--lang", "en", "--help"])
    help_en = capsys.readouterr().out
    assert "interface language" in help_en and "start the search" in help_en
    with pytest.raises(SystemExit):
        cli.main(["--lang", "tr", "--help"])
    assert "arayüz dili" in capsys.readouterr().out


def test_menu_keeps_language_choice_for_the_commands_it_launches(monkeypatch):
    answers = iter(["5", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    seen = []
    monkeypatch.setattr(cli, "menu", lambda base: seen.append(base) or 0)
    cli.main(["--lang", "en", "--config", "x.toml"])
    assert seen == [["--config", "x.toml", "--lang", "en"]]


def test_confirmation_word_accepts_both_languages(monkeypatch):
    for word, ok in (("EVET", True), ("YES", True), ("yes", False), ("", False), ("hayır", False)):
        monkeypatch.setattr("builtins.input", lambda prompt="", w=word: w)
        assert cli.confirmed("?") is ok


def test_banner_is_translated():
    i18n.set_language("en")
    assert "WARNING" in i18n.tr(cli.BANNER) and "UYARI" not in i18n.tr(cli.BANNER)
    i18n.set_language("tr")
    assert "UYARI" in i18n.tr(cli.BANNER)


def test_report_recognises_warning_notes_in_both_languages():
    from pbo_tuner.report import is_warning
    assert is_warning("UYARI: x") and is_warning("WARNING: x")
    assert is_warning("2026-11-01 04:28:55 UYARI: x") and is_warning("2026-11-01 04:28:55 WARNING: x")  # tarih damgalı
    assert not is_warning("2026-11-01 04:28:55 çökme: x") and not is_warning("crash: UYARI sözcüğü içeriyor")


@pytest.mark.parametrize("lang,header,word", [("tr", "UYARILAR:", "UYARI"), ("en", "WARNINGS:", "WARNING")])
def test_warnings_from_real_notes_are_listed_in_the_report(lang, header, word):
    """Gerçek olay: notlar RunState.note() ile tarih damgalı kaydedilir; uyarılar raporda görünmeli."""
    from pbo_tuner.config import Config
    from pbo_tuner.report import build_report
    from pbo_tuner.state import RunState
    from pbo_tuner.tuner import search_params
    i18n.set_language(lang)
    st = RunState(4, search_params(Config()))
    st.stage, st.final = "done", {0: 10, 1: 5, 2: 0, 3: 0}
    st.note(f"{word}: idle crash")
    st.note("unrelated note")
    text = build_report(st, Config())[0]
    assert header in text and f"{word}: idle crash" in text and "unrelated note" not in text
