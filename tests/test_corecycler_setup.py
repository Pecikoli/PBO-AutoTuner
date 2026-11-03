"""CoreCycler'ın kurulum sırasında indirilip açılması (setup_env.ensure_corecycler). Ağa ve gerçek arşive ihtiyaç
duymaz: indirme ve açma sahte işlevlerle taklit edilir."""
import hashlib
import io
import re
import tomllib
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace

import pytest

from pbo_tuner import setup_env as se

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = b"sahte 7z arsivi"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest().upper()
Usage = namedtuple("Usage", "total used free")


def populate(dest: Path, files: int = 6, complete: bool = True):
    """Gerçek arşivin yapısını taklit eder: tek üst klasör + gereken programlar + yeterince dosya."""
    top = dest / se.COREYCLER_DIRNAME
    keys = se.COREKEYS if complete else se.COREKEYS[:1]
    for rel in keys:
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_bytes(b"MZ")
    for i in range(files):
        (top / "extra").mkdir(exist_ok=True)
        (top / "extra" / f"f{i}.txt").write_text("x")


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Sahte ortam: sabit özet sahte yüke ayarlı, alt sınır düşürülmüş, tar ve 7-Zip yolları kontrol edilebilir."""
    monkeypatch.setattr(se, "COREYCLER_SHA256", PAYLOAD_SHA)
    monkeypatch.setattr(se, "COREYCLER_MIN_FILES", 5)
    monkeypatch.setattr(se.shutil, "disk_usage", lambda p: Usage(10**12, 0, 10**12))
    monkeypatch.setattr(se, "windows_tar", lambda *a, **k: "TAR.EXE")
    monkeypatch.setattr(se, "find_7zip", lambda *a, **k: None)
    project, tmp = tmp_path / "proje", tmp_path / "gecici"
    project.mkdir()
    tmp.mkdir()
    state = SimpleNamespace(project=project, tmp=tmp, urls=[], runs=[], logs=[])

    def urlopen(url, timeout=None):
        state.urls.append(url)
        return io.BytesIO(PAYLOAD)

    def make_run(extracts=True, code=0, complete=True):
        def run(cmd, **kw):
            state.runs.append(cmd)
            if extracts:
                dest = Path(cmd[cmd.index("-C") + 1]) if "-C" in cmd else Path(
                    next(c for c in cmd if c.startswith("-o"))[2:])
                populate(dest, complete=complete)
            return SimpleNamespace(returncode=code, stdout="", stderr="" if code == 0 else "bsdtar: hata")
        return run

    state.urlopen, state.make_run = urlopen, make_run
    state.go = lambda **kw: se.ensure_corecycler(
        project, kw.pop("run", make_run()), state.logs.append, urlopen=kw.pop("urlopen", urlopen), tmpdir=tmp, **kw)
    return state


# ------------------------------------------------------------------ sabitler
def test_corecycler_constants_are_pinned_and_well_formed():
    assert re.fullmatch(r"[0-9A-F]{64}", se.COREYCLER_SHA256)
    assert se.COREYCLER_URL.startswith("https://github.com/sp00n/CoreCycler/releases/download/")
    assert se.COREYCLER_URL.endswith(se.COREYCLER_DIRNAME + ".7z")
    assert se.COREYCLER_VERSION in se.COREYCLER_DIRNAME and se.COREYCLER_VERSION in se.COREYCLER_URL


def test_pinned_folder_name_is_found_by_find_corecycler(tmp_path):
    populate(tmp_path)
    assert se.find_corecycler(tmp_path) == tmp_path / se.COREYCLER_DIRNAME


# ------------------------------------------------------------------ yardımcılar
def test_corecycler_complete_needs_programs_and_enough_files(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "COREYCLER_MIN_FILES", 5)
    populate(tmp_path, complete=False)
    assert not se.corecycler_complete(tmp_path / se.COREYCLER_DIRNAME)          # programlar eksik
    populate(tmp_path / "b", files=1)
    assert not se.corecycler_complete(tmp_path / "b" / se.COREYCLER_DIRNAME)    # dosya çok az
    populate(tmp_path / "c")
    assert se.corecycler_complete(tmp_path / "c" / se.COREYCLER_DIRNAME)


def test_windows_tar_only_trusts_system32(tmp_path):
    assert se.windows_tar({}) is None
    sysroot = tmp_path / "Windows"
    assert se.windows_tar({"SystemRoot": str(sysroot)}) is None                # dosya yok
    (sysroot / "System32").mkdir(parents=True)
    (sysroot / "System32" / "tar.exe").write_bytes(b"")
    assert se.windows_tar({"SystemRoot": str(sysroot)}) == str(sysroot / "System32" / "tar.exe")


def test_find_7zip_checks_path_then_program_files(tmp_path):
    assert se.find_7zip(lambda n: None, {}) is None
    exe = tmp_path / "7-Zip" / "7z.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    assert se.find_7zip(lambda n: None, {"ProgramFiles": str(tmp_path)}) == str(exe)
    on_path = tmp_path / "bin" / "7z.exe"
    on_path.parent.mkdir()
    on_path.write_bytes(b"")
    assert se.find_7zip(lambda n: str(on_path) if n == "7z" else None, {"ProgramFiles": str(tmp_path)}) == str(on_path)


# ------------------------------------------------------------------ açma
def test_extract_uses_windows_tar_first_with_exact_arguments(env, tmp_path):
    dest = tmp_path / "hedef"
    dest.mkdir()
    archive = tmp_path / "a.7z"
    assert se.extract_7z(archive, dest, env.make_run(), env.logs.append) is True
    assert env.runs == [["TAR.EXE", "-xf", str(archive), "-C", str(dest)]]


def test_extract_falls_back_to_7zip_when_tar_fails_and_cleans_partial_output(env, tmp_path, monkeypatch):
    monkeypatch.setattr(se, "find_7zip", lambda *a, **k: "7Z.EXE")
    dest = tmp_path / "hedef"
    dest.mkdir()

    def run(cmd, **kw):
        env.runs.append(cmd)
        if cmd[0] == "TAR.EXE":
            (dest / "yarim.bin").write_bytes(b"x")                                  # tar yarım iş bıraktı
            return SimpleNamespace(returncode=1, stdout="", stderr="tar: BCJ2 desteklenmiyor")
        assert not (dest / "yarim.bin").exists()                                     # 7-Zip temiz klasörle başlar
        populate(dest)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert se.extract_7z(tmp_path / "a.7z", dest, run, env.logs.append) is True
    assert [c[0] for c in env.runs] == ["TAR.EXE", "7Z.EXE"]
    assert env.runs[1] == ["7Z.EXE", "x", "-y", f"-o{dest}", str(tmp_path / "a.7z")]
    assert any("BCJ2" in l for l in env.logs)                                        # nedeni kullanıcıya gösterilir


def test_tar_exit_code_1_is_accepted_when_only_unreadable_filenames_were_skipped(env, tmp_path):
    """Gerçek olay (Türkçe Windows): tar.exe ASCII olmayan adlı 5 önemsiz dosyayı atlayıp çıkış kodu 1 verdi, kullanıcıda
    7-Zip olduğu için kurulum yedekle tamamlandı. Gerekli her şey açılmışsa 7-Zip'e gerek kalmamalı."""
    dest = tmp_path / "hedef"
    dest.mkdir()

    def run(cmd, **kw):
        env.runs.append(cmd)
        populate(dest)
        return SimpleNamespace(returncode=1, stdout="", stderr="tar.exe: Archive entry has empty or unreadable filename ... skipping.")

    assert se.extract_7z(tmp_path / "a.7z", dest, run, env.logs.append) is True
    assert [c[0] for c in env.runs] == ["TAR.EXE"]                                # 7-Zip denenmedi bile
    assert any("atladı" in l and "devam ediliyor" in l for l in env.logs)


def test_tar_exit_code_1_with_missing_required_files_still_falls_back(env, tmp_path, monkeypatch):
    monkeypatch.setattr(se, "find_7zip", lambda *a, **k: "7Z.EXE")
    dest = tmp_path / "hedef"
    dest.mkdir()

    def run(cmd, **kw):
        env.runs.append(cmd)
        populate(dest, complete=(cmd[0] != "TAR.EXE"))                            # tar eksik bıraktı, 7-Zip tam açtı
        return SimpleNamespace(returncode=1 if cmd[0] == "TAR.EXE" else 0, stdout="", stderr="tar: hata")

    assert se.extract_7z(tmp_path / "a.7z", dest, run, env.logs.append) is True
    assert [c[0] for c in env.runs] == ["TAR.EXE", "7Z.EXE"]


def test_the_pinned_minimum_matches_the_ascii_named_files_of_the_real_archive():
    """Gerçek arşiv: 447 dosya, 5'i ASCII olmayan adlı => 442. Bu sabit değişirse ayrıca doğrulanmalı."""
    assert se.COREYCLER_MIN_FILES == 442


def test_extract_rejects_an_incomplete_result_even_if_exit_code_is_zero(env, tmp_path):
    dest = tmp_path / "hedef"
    dest.mkdir()
    assert se.extract_7z(tmp_path / "a.7z", dest, env.make_run(complete=False), env.logs.append) is False
    assert list(dest.iterdir()) == []


def test_extract_without_any_extractor_explains_what_to_install(env, tmp_path, monkeypatch):
    monkeypatch.setattr(se, "windows_tar", lambda *a, **k: None)
    dest = tmp_path / "hedef"
    dest.mkdir()
    assert se.extract_7z(tmp_path / "a.7z", dest, env.make_run(), env.logs.append) is False
    assert env.runs == [] and any("7-Zip" in l for l in env.logs)


def test_extract_survives_a_missing_executable(env, tmp_path):
    dest = tmp_path / "hedef"
    dest.mkdir()

    def run(cmd, **kw):
        raise FileNotFoundError("tar.exe")

    assert se.extract_7z(tmp_path / "a.7z", dest, run, env.logs.append) is False


# ------------------------------------------------------------------ ensure_corecycler
def test_existing_corecycler_is_reused_without_any_download(env):
    populate(env.project)
    got = env.go(ask=lambda q: pytest.fail("sormamalıydı"), urlopen=lambda *a, **k: pytest.fail("indirmemeliydi"))
    assert got == env.project / se.COREYCLER_DIRNAME


def test_download_verify_extract_and_move_into_place(env):
    got = env.go()
    assert got == env.project / se.COREYCLER_DIRNAME
    assert se.find_corecycler(env.project) == got
    assert env.urls == [se.COREYCLER_URL]
    assert not (env.project / se.COREYCLER_STAGING).exists()                        # geçici klasör silindi
    assert not (env.tmp / (se.COREYCLER_DIRNAME + ".7z")).exists()                  # indirilen arşiv silindi
    assert [p.name for p in env.project.iterdir()] == [se.COREYCLER_DIRNAME]
    assert any("SHA-256" in l for l in env.logs) and any("kuruldu" in l for l in env.logs)


def test_user_is_asked_first_and_told_about_the_license(env):
    questions = []
    assert env.go(ask=lambda q: questions.append(q) or True) is not None
    assert len(questions) == 1
    text = "\n".join(env.logs)
    assert "CC BY-NC-SA" in text and se.COREYCLER_URL in text and "45 MB" in text


def test_declining_downloads_nothing(env):
    assert env.go(ask=lambda q: False) is None
    assert env.urls == [] and env.runs == [] and list(env.project.iterdir()) == []


def test_hash_mismatch_refuses_to_extract(env, monkeypatch):
    monkeypatch.setattr(se, "COREYCLER_SHA256", "0" * 64)
    assert env.go() is None
    assert env.runs == []                                                           # doğrulanmayan dosya açılmaz
    assert list(env.project.iterdir()) == [] and list(env.tmp.iterdir()) == []


def test_download_failure_leaves_nothing_behind(env):
    def broken(url, timeout=None):
        raise OSError("bağlantı yok")

    assert env.go(urlopen=broken) is None
    assert env.runs == [] and list(env.project.iterdir()) == [] and list(env.tmp.iterdir()) == []


def test_extraction_failure_cleans_up_and_mentions_antivirus(env):
    assert env.go(run=env.make_run(extracts=False, code=1)) is None
    assert list(env.project.iterdir()) == [] and list(env.tmp.iterdir()) == []
    assert any("Antivirüs" in l for l in env.logs)


def snapshot(folder: Path):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


def test_incomplete_folder_is_moved_aside_never_deleted_and_reinstalled(env):
    """Antivirüs bir dosyayı silmişse klasör "eksik" görünür: eskisi SİLİNMEDEN kenara alınır, yenisi kurulur."""
    target = env.project / se.COREYCLER_DIRNAME
    populate(env.project, complete=False)
    old_files = snapshot(target)
    assert env.go() == target and se.corecycler_complete(target)
    asides = [p for p in env.project.iterdir() if ".eksik-" in p.name]
    assert len(asides) == 1 and snapshot(asides[0]) == old_files                # eski içerik aynen duruyor
    assert any("kenara alındı" in l for l in env.logs)
    assert se.find_corecycler(env.project) == target                             # eksik kopya aday sayılmaz


def test_incomplete_folder_is_untouched_if_the_user_declines(env):
    populate(env.project, complete=False)
    before = snapshot(env.project)
    assert env.go(ask=lambda q: False, urlopen=lambda *a, **k: pytest.fail("indirmemeliydi")) is None
    assert snapshot(env.project) == before
    assert any("eksik görünüyor" in l for l in env.logs)


def test_incomplete_folder_is_untouched_if_the_download_fails(env):
    populate(env.project, complete=False)
    before = snapshot(env.project)

    def broken(url, timeout=None):
        raise OSError("bağlantı yok")

    assert env.go(urlopen=broken) is None
    assert snapshot(env.project) == before                                       # indirme olmadan taşınmaz


def test_failed_extraction_puts_the_moved_aside_folder_back(env):
    target = env.project / se.COREYCLER_DIRNAME
    populate(env.project, complete=False)
    before = snapshot(env.project)
    assert env.go(run=env.make_run(extracts=False, code=1)) is None
    assert snapshot(env.project) == before and target.exists()                   # her şey eski haline döndü


def test_stale_staging_folder_from_a_previous_attempt_is_replaced(env):
    stale = env.project / se.COREYCLER_STAGING
    stale.mkdir()
    (stale / "eski.txt").write_text("x")
    assert env.go() == env.project / se.COREYCLER_DIRNAME
    assert not stale.exists()


def test_low_disk_space_stops_before_downloading(env, monkeypatch):
    monkeypatch.setattr(se.shutil, "disk_usage", lambda p: Usage(10**9, 0, 10 * 1024 * 1024))
    assert env.go(urlopen=lambda *a, **k: pytest.fail("indirmemeliydi")) is None
    assert any("boş yer" in l for l in env.logs)


# ------------------------------------------------------------------ main() akışı
class Combined:
    """Hem psutil denetimini hem arşiv açmayı yanıtlayan subprocess.run taklidi."""
    def __init__(self, extract):
        self.extract = extract

    def __call__(self, cmd, **kw):
        if "import psutil" in " ".join(cmd):
            return SimpleNamespace(returncode=0, stdout="7.0\n", stderr="")
        return self.extract(cmd, **kw)


def seed_example(project: Path):
    (project / "config.example.toml").write_text((ROOT / "config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")


def test_main_downloads_corecycler_and_writes_its_path_into_config(env):
    seed_example(env.project)
    logs = []
    rc = se.main(str(env.project), logs.append, run=Combined(env.make_run()), yes=True, no_pawnio=True,
                 urlopen=env.urlopen)
    assert rc == 0
    cfg = (env.project / "config.toml").read_text(encoding="utf-8")
    assert str(env.project / se.COREYCLER_DIRNAME) in cfg and "C:\\Tools\\CoreCycler" not in cfg
    assert any("[TAMAM] CoreCycler" in l for l in logs)


def test_main_no_corecycler_flag_skips_the_step(env):
    seed_example(env.project)
    logs = []
    rc = se.main(str(env.project), logs.append, run=Combined(env.make_run()), yes=True, no_pawnio=True,
                 no_corecycler=True, urlopen=lambda *a, **k: pytest.fail("indirmemeliydi"))
    assert rc == 0 and env.runs == []
    assert any("[EKSİK] CoreCycler" in l for l in logs)


def test_main_asks_before_downloading_unless_yes(env):
    seed_example(env.project)
    asked = []
    rc = se.main(str(env.project), lambda m: None, run=Combined(env.make_run()), no_pawnio=True,
                 ask=lambda q: asked.append(q) or False, urlopen=env.urlopen)
    assert rc == 0 and len(asked) == 1 and env.urls == []
    asked.clear()
    se.main(str(env.project), lambda m: None, run=Combined(env.make_run()), no_pawnio=True, yes=True,
            ask=lambda q: asked.append(q) or False, urlopen=env.urlopen)
    assert asked == [] and env.urls == [se.COREYCLER_URL]                           # --yes: sorulmaz


def test_main_does_not_download_when_corecycler_is_already_next_to_the_project(env):
    seed_example(env.project)
    populate(env.project.parent)                                                    # kardeş klasörde var
    rc = se.main(str(env.project), lambda m: None, run=Combined(env.make_run()), yes=True, no_pawnio=True,
                 urlopen=lambda *a, **k: pytest.fail("indirmemeliydi"))
    assert rc == 0 and env.runs == []


# ------------------------------------------------------------------ config.toml onarımı
def cfg_text(path: str) -> str:
    return f"[search]\nfloor = 45\n\n[paths]\ncorecycler_dir = '{path}'\ndata_dir = \"data\"\n"


def test_stale_corecycler_dir_in_an_existing_config_is_repaired_and_the_rest_is_kept(env):
    """Gerçek olay: ilk çalıştırmada CoreCycler yoktu, config örnek yolla üretildi; sonra CoreCycler kuruldu ama
    config'teki yol eski kaldı ve araç FileNotFoundError ile düştü."""
    populate(env.project)
    cc = env.project / se.COREYCLER_DIRNAME
    (env.project / "config.toml").write_text(cfg_text(r"C:\Tools\CoreCycler"), encoding="utf-8")
    logs = []
    assert se.ensure_config(env.project, cc, logs.append) == "updated"
    text = (env.project / "config.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["paths"]["corecycler_dir"] == str(cc)
    assert "floor = 45" in text and 'data_dir = "data"' in text                  # diğer ayarlara dokunulmadı
    assert any("güncellendi" in l for l in logs)


def test_valid_corecycler_dir_in_an_existing_config_is_never_changed(env, tmp_path):
    populate(env.project)
    other = tmp_path / "baska"
    populate(other)
    mine = other / se.COREYCLER_DIRNAME
    original = cfg_text(str(mine))
    (env.project / "config.toml").write_text(original, encoding="utf-8")
    assert se.ensure_config(env.project, env.project / se.COREYCLER_DIRNAME, lambda s: None) == "exists"
    assert (env.project / "config.toml").read_text(encoding="utf-8") == original


def test_invalid_path_with_no_corecycler_available_warns_but_changes_nothing(env):
    original = cfg_text(r"C:\Tools\CoreCycler")
    (env.project / "config.toml").write_text(original, encoding="utf-8")
    logs = []
    assert se.ensure_config(env.project, None, logs.append) == "exists"
    assert (env.project / "config.toml").read_text(encoding="utf-8") == original
    assert any("UYARI" in l and "corecycler_dir" in l for l in logs)


def test_config_without_a_corecycler_dir_line_is_left_alone(env):
    populate(env.project)
    (env.project / "config.toml").write_text("# benim ayarlarim\n", encoding="utf-8")
    assert se.ensure_config(env.project, env.project / se.COREYCLER_DIRNAME, lambda s: None) == "exists"
    assert (env.project / "config.toml").read_text(encoding="utf-8") == "# benim ayarlarim\n"


def test_main_downloads_corecycler_and_repairs_the_stale_config_in_one_run(env):
    seed_example(env.project)
    (env.project / "config.toml").write_text(cfg_text(r"C:\Tools\CoreCycler"), encoding="utf-8")
    logs = []
    rc = se.main(str(env.project), logs.append, run=Combined(env.make_run()), yes=True, no_pawnio=True,
                 urlopen=env.urlopen)
    assert rc == 0
    text = (env.project / "config.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["paths"]["corecycler_dir"] == str(env.project / se.COREYCLER_DIRNAME)
    assert any("güncellendi" in l for l in logs)


def test_main_repairs_config_for_an_incomplete_folder_after_reinstalling(env):
    seed_example(env.project)
    populate(env.project, complete=False)                                        # antivirüs bir dosyayı silmiş
    rc = se.main(str(env.project), lambda m: None, run=Combined(env.make_run()), yes=True, no_pawnio=True,
                 urlopen=env.urlopen)
    assert rc == 0
    cc = env.project / se.COREYCLER_DIRNAME
    assert se.corecycler_complete(cc)
    assert tomllib.loads((env.project / "config.toml").read_text(encoding="utf-8"))["paths"]["corecycler_dir"] == str(cc)
