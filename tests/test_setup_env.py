"""Kurulum yardımcısı (setup_env) ve .bat dosyaları için statik kontroller."""
import re
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pbo_tuner import setup_env as se

ROOT = Path(__file__).resolve().parent.parent


class FakeRun:
    """subprocess.run taklidi. `plan`: komutun içinde geçen metne göre dönüş kodu."""
    def __init__(self, psutil_installed=False, fail=(), installs_on=None):
        self.calls, self.installed, self.fail = [], psutil_installed, set(fail)
        self.installs_on = installs_on or "pip install"

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        if "import psutil" in joined:
            return SimpleNamespace(returncode=0 if self.installed else 1, stdout="7.0\n", stderr="")
        key = "ensurepip" if "ensurepip" in joined else ("pip install --user" if "--user" in joined else "pip install")
        if key in self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="hata")
        if "pip install" in joined or "--user" in joined:
            self.installed = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_python_version_gate():
    assert se.python_ok((3, 11, 0)) and se.python_ok((3, 14, 2)) and not se.python_ok((3, 10, 9))


def test_psutil_already_installed_no_pip_call():
    run, logs = FakeRun(psutil_installed=True), []
    assert se.ensure_psutil("py.exe", run, logs.append)
    assert len(run.calls) == 1 and not any("pip" in " ".join(c) for c in run.calls)


def test_psutil_installed_with_plain_pip():
    run = FakeRun()
    assert se.ensure_psutil("py.exe", run, lambda s: None)
    assert any(c[:4] == ["py.exe", "-m", "pip", "install"] and "psutil>=5.9" in c for c in run.calls)
    assert not any("ensurepip" in " ".join(c) for c in run.calls)


def test_psutil_falls_back_to_ensurepip_then_user_install():
    run = FakeRun(fail={"pip install"})   # düz pip her seferinde başarısız (ensurepip sonrası da): son çare --user başarır
    assert se.ensure_psutil("py.exe", run, lambda s: None)
    joined = [" ".join(c) for c in run.calls]
    assert any("ensurepip" in j for j in joined) and any("--user" in j for j in joined)


def test_psutil_all_methods_fail_returns_false():
    run = FakeRun(fail={"pip install", "ensurepip", "pip install --user"})
    assert se.ensure_psutil("py.exe", run, lambda s: None) is False


def test_write_python_path_roundtrip(tmp_path):
    p = se.write_python_path(tmp_path, r"C:\Users\Biri Kişi\AppData\Local\Programs\Python\Python312\python.exe")
    assert p.read_text(encoding="utf-8").strip() == r"C:\Users\Biri Kişi\AppData\Local\Programs\Python\Python312\python.exe"


def make_cc(base: Path, name="CoreCycler-v0.11.0.3", complete=True):
    d = base / name
    for rel in se.COREKEYS if complete else se.COREKEYS[:1]:
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    return d


def test_find_corecycler_inside_project_prefers_complete_and_newest(tmp_path):
    make_cc(tmp_path, "CoreCycler-v0.10.0.0")
    new = make_cc(tmp_path, "CoreCycler-v0.11.0.3")
    make_cc(tmp_path, "CoreCycler-v0.12.0.0", complete=False)        # eksik: seçilmez
    assert se.find_corecycler(tmp_path) == new


def test_find_corecycler_next_to_project_and_none(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    assert se.find_corecycler(proj) is None
    cc = make_cc(tmp_path)
    assert se.find_corecycler(proj) == cc


def test_ensure_config_creates_from_example_with_path_and_never_overwrites(tmp_path):
    (tmp_path / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    cc = make_cc(tmp_path)
    assert se.ensure_config(tmp_path, cc, lambda s: None) == "created"
    cfg = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert cfg["paths"]["corecycler_dir"] == str(cc)
    (tmp_path / "config.toml").write_text("# benim ayarlarim\n", encoding="utf-8")
    assert se.ensure_config(tmp_path, cc, lambda s: None) == "exists"
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "# benim ayarlarim\n"


def test_ensure_config_without_corecycler_warns_and_keeps_placeholder(tmp_path):
    (tmp_path / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    logs = []
    assert se.ensure_config(tmp_path, None, logs.append) == "created-no-corecycler"
    assert any("elle düzenleyin" in l for l in logs)


def test_toml_string_handles_apostrophes_and_windows_paths():
    for path in (r"C:\Users\Example\Desktop\pbo_autotuner\CoreCycler-v0.11.0.3", r"C:\Users\O'Brien\CoreCycler", 'C:\\a "b"\\c'):
        assert tomllib.loads(f"x = {se._toml_string(path)}")["x"] == path


def test_main_end_to_end_with_fakes(tmp_path, monkeypatch):
    (tmp_path / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    make_cc(tmp_path)
    logs = []
    rc = se.main(str(tmp_path), logs.append, run=FakeRun())
    assert rc == 0
    assert (tmp_path / "python_path.txt").read_text(encoding="utf-8").strip() == sys.executable
    assert (tmp_path / "config.toml").exists()
    text = "\n".join(logs)
    assert "psutil kuruldu" in text and "CoreCycler" in text and "doctor" in text


def test_main_fails_cleanly_when_psutil_cannot_be_installed(tmp_path):
    logs = []
    rc = se.main(str(tmp_path), logs.append, run=FakeRun(fail={"pip install", "ensurepip", "pip install --user"}))
    assert rc == 1 and any("psutil kurulamadı" in l for l in logs)
    assert not (tmp_path / "python_path.txt").exists()


def test_setup_module_does_not_import_psutil():
    import subprocess
    r = subprocess.run([sys.executable, "-c", "import sys, pbo_tuner.setup_env; sys.exit(1 if 'psutil' in sys.modules else 0)"],
                       cwd=ROOT, capture_output=True)
    assert r.returncode == 0


# ------------------------------------------------------------------ .bat dosyaları (Windows'ta çalıştırılamaz: statik kontrol)
@pytest.mark.parametrize("name", ["kur.bat", "run_as_admin.bat"])
def test_bat_files_are_ascii_with_crlf(name):
    data = (ROOT / name).read_bytes()
    assert all(b < 128 for b in data), "bat dosyasında ASCII dışı karakter var (kod sayfası sorunu çıkarır)"
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_kur_bat_structure():
    text = (ROOT / "kur.bat").read_text()
    labels = set(re.findall(r"^:(\w+)", text, re.M))
    used = set(re.findall(r"(?:goto|call)\s+:?(\w+)", text)) - {"eof", "python"}
    assert used <= labels, used - labels
    assert "-m pbo_tuner.setup_env" in text
    assert "Python.Python.3.12" in text and "--scope user" in text
    assert "python-3.12.10-amd64.exe" in text and "/quiet InstallAllUsers=0 PrependPath=1" in text
    assert "sys.version_info >= (3, 11)" in text
    # parantezli if/for blokları yok: içeride ')' içeren komutlar bloğu bozmasın
    assert not re.search(r"^\s*(if|for)\b.*\($", text, re.M)


def test_run_as_admin_uses_recorded_python():
    text = (ROOT / "run_as_admin.bat").read_text()
    assert "python_path.txt" in text and '"%PY%" -m pbo_tuner %*' in text


# ------------------------------------------------------------------ PawnIO kurulumu (Windows taklit edilerek)
import hashlib
import io
import types


@pytest.fixture
def win(monkeypatch):
    """os.name == 'nt' taklidi + PawnIO durumu (installed['v'])."""
    monkeypatch.setattr(se, "os", types.SimpleNamespace(name="nt", environ={}))
    state = {"v": False}
    monkeypatch.setattr(se, "pawnio_version", lambda: "2.2.0" if state["v"] else None)
    monkeypatch.setattr(se, "pawnio_detected", lambda: state["v"])
    return state


class Installer:
    """subprocess.run taklidi: winget/yükleyici çağrılarını kaydeder, istenirse PawnIO'yu 'kurar'."""
    def __init__(self, state, winget_rc=0, winget_installs=True, exe_rc=0, exe_installs=True):
        self.state, self.calls = state, []
        self.cfg = dict(winget_rc=winget_rc, winget_installs=winget_installs, exe_rc=exe_rc, exe_installs=exe_installs)

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "winget":
            if self.cfg["winget_installs"]:
                self.state["v"] = True
            return SimpleNamespace(returncode=self.cfg["winget_rc"])
        if self.cfg["exe_installs"] and self.cfg["exe_rc"] in (0, se.REBOOT_REQUIRED):
            self.state["v"] = True
        return SimpleNamespace(returncode=self.cfg["exe_rc"])


def fake_download(monkeypatch, payload=b"fake installer", match=True):
    monkeypatch.setattr(se, "PAWNIO_SHA256", hashlib.sha256(payload if match else b"x" + payload).hexdigest().upper())
    return lambda url, timeout=0: io.BytesIO(payload)


def test_pawnio_constants_are_pinned_and_well_formed():
    assert re.fullmatch(r"[0-9A-F]{64}", se.PAWNIO_SHA256)
    assert se.PAWNIO_URL.startswith("https://github.com/namazso/PawnIO.Setup/releases/download/")
    assert se.PAWNIO_VERSION in se.PAWNIO_URL and se.PAWNIO_WINGET_ID == "namazso.PawnIO"


def test_pawnio_unsupported_outside_windows():
    assert se.ensure_pawnio(run=FakeRun(), log=lambda s: None) == "unsupported"


def test_pawnio_already_present_does_nothing(win):
    win["v"] = True
    run, asked = Installer(win), []
    assert se.ensure_pawnio(run, lambda s: None, ask=lambda q: asked.append(q) or True) == "present"
    assert run.calls == [] and asked == []


def test_pawnio_declined_installs_nothing(win):
    run = Installer(win)
    assert se.ensure_pawnio(run, lambda s: None, ask=lambda q: False, which=lambda n: "winget") == "declined"
    assert run.calls == [] and win["v"] is False


def test_pawnio_installed_via_winget_with_silent_flags(win):
    run = Installer(win)
    assert se.ensure_pawnio(run, lambda s: None, ask=lambda q: True, which=lambda n: "winget.exe") == "installed"
    cmd = run.calls[0]
    assert cmd[:2] == ["winget", "install"] and "namazso.PawnIO" in cmd and "--silent" in cmd
    assert "--accept-package-agreements" in cmd and "--accept-source-agreements" in cmd and len(run.calls) == 1


def test_pawnio_winget_reports_reboot_required(win):
    run = Installer(win, winget_rc=se.REBOOT_REQUIRED)
    assert se.ensure_pawnio(run, lambda s: None, ask=None, which=lambda n: "winget") == "reboot"


def test_pawnio_direct_download_non_admin_elevates_with_uac_and_cleans_up(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch)
    run = Installer(win)
    r = se.ensure_pawnio(run, lambda s: None, ask=None, urlopen=uo, admin=False, which=lambda n: None, tmpdir=tmp_path)
    assert r == "installed"
    cmd = run.calls[0]
    assert cmd[0] == "powershell" and "-Verb RunAs" in cmd[-1] and "-Wait" in cmd[-1] and "'-install','-silent'" in cmd[-1]
    assert not (tmp_path / "PawnIO_setup.exe").exists()                       # yükleyici sonra silinir


def test_pawnio_direct_download_admin_runs_installer_directly(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch)
    run = Installer(win)
    assert se.ensure_pawnio(run, lambda s: None, ask=None, urlopen=uo, admin=True, which=lambda n: None,
                            tmpdir=tmp_path) == "installed"
    assert run.calls[0][1:] == ["-install", "-silent"] and run.calls[0][0].endswith("PawnIO_setup.exe")


def test_pawnio_hash_mismatch_refuses_to_run_downloaded_file(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch, match=False)
    run, logs = Installer(win), []
    assert se.ensure_pawnio(run, logs.append, ask=None, urlopen=uo, admin=True, which=lambda n: None,
                            tmpdir=tmp_path) == "failed"
    assert run.calls == [] and not (tmp_path / "PawnIO_setup.exe").exists()
    assert any("SHA-256 uyuşmuyor" in l for l in logs)


def test_pawnio_download_error_fails_cleanly(win, tmp_path):
    def boom(url, timeout=0):
        raise OSError("ağ yok")
    run = Installer(win)
    assert se.ensure_pawnio(run, lambda s: None, ask=None, urlopen=boom, admin=True, which=lambda n: None,
                            tmpdir=tmp_path) == "failed"
    assert run.calls == []


def test_pawnio_falls_back_to_direct_download_when_winget_fails(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch)
    run = Installer(win, winget_rc=1, winget_installs=False)
    assert se.ensure_pawnio(run, lambda s: None, ask=None, urlopen=uo, admin=True, which=lambda n: "winget",
                            tmpdir=tmp_path) == "installed"
    assert run.calls[0][0] == "winget" and run.calls[1][0].endswith("PawnIO_setup.exe")


def test_pawnio_uac_refused_or_install_not_detected_is_reported(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch)
    run, logs = Installer(win, exe_rc=1, exe_installs=False), []
    assert se.ensure_pawnio(run, logs.append, ask=None, urlopen=uo, admin=False, which=lambda n: None,
                            tmpdir=tmp_path) == "failed"
    assert any("UAC" in l for l in logs)


def test_pawnio_installer_exit_3010_means_reboot(win, monkeypatch, tmp_path):
    uo = fake_download(monkeypatch)
    run = Installer(win, exe_rc=se.REBOOT_REQUIRED)
    assert se.ensure_pawnio(run, lambda s: None, ask=None, urlopen=uo, admin=True, which=lambda n: None,
                            tmpdir=tmp_path) == "reboot"


def test_main_flags_control_pawnio_step(tmp_path, win, monkeypatch):
    (tmp_path / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    asked, logs = [], []
    monkeypatch.setattr(se, "ensure_pawnio", lambda run, log, ask=None, **kw: asked.append(ask) or "present")
    monkeypatch.setattr(se, "ensure_corecycler", lambda *a, **kw: None)         # bu test yalnızca PawnIO adımını sınar
    assert se.main(str(tmp_path), logs.append, run=FakeRun(psutil_installed=True), yes=True) == 0
    assert asked == [None]                                                   # --yes: onay sorulmaz
    asked.clear()
    assert se.main(str(tmp_path), logs.append, run=FakeRun(psutil_installed=True), ask=lambda q: True) == 0
    assert callable(asked[0])                                                # varsayılan: onay sorulur
    asked.clear()
    assert se.main(str(tmp_path), logs.append, run=FakeRun(psutil_installed=True), no_pawnio=True) == 0
    assert asked == [] and any("--no-pawnio" in l for l in logs)


def test_ask_yes_no_defaults_and_eof(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "")
    assert se.ask_yes_no("?") is True
    monkeypatch.setattr("builtins.input", lambda p="": "h")
    assert se.ask_yes_no("?") is False

    def eof(p=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert se.ask_yes_no("?") is False
