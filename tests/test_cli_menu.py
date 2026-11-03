from pbo_tuner import __main__ as cli


def test_no_command_opens_menu_instead_of_error(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "doctor" in out and "Çıkış" in out


def test_menu_runs_selected_command_then_exits(monkeypatch, capsys):
    answers = iter(["5", "0"])             # 5 = status, 0 = çıkış
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    calls = []
    monkeypatch.setattr(cli, "main", lambda argv=None: calls.append(argv) or 0)
    assert cli.menu([]) == 0
    assert calls == [["status"]]


def test_menu_passes_config_through(monkeypatch):
    answers = iter(["1", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    calls = []
    monkeypatch.setattr(cli, "main", lambda argv=None: calls.append(argv) or 0)
    cli.menu(["--config", "x.toml"])
    assert calls == [["--config", "x.toml", "doctor"]]


def test_run_reports_missing_tool_files_clearly_before_starting(tmp_path, monkeypatch, capsys):
    """Gerçek olay: gerekli programlar yerinde değildi; kullanıcı ham bir hata izi gördü. Artık başlamadan anlaşılır
    bir hata verilir ve hangi dosyaların eksik olduğu yazılır."""
    from types import SimpleNamespace
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[paths]\ndata_dir = '{tmp_path / 'data'}'\n", encoding="utf-8")

    class FakeStress:
        def check_files(self):
            return [r"C:\Tools\CoreCycler\helpers\WriteConsoleToWriteFileWrapper.exe"]

    smu = SimpleNamespace(exe=r"C:\Tools\CoreCycler\tools\ryzen-smu-cli\ryzen-smu-cli.exe")
    hw = SimpleNamespace(stress=FakeStress(), smu=smu)
    started = []
    monkeypatch.setattr(cli, "make_real_hardware", lambda cfg, log=None: hw)
    monkeypatch.setattr(cli, "is_admin", lambda: True)
    monkeypatch.setattr(cli, "Tuner", lambda *a, **k: started.append(1))
    assert cli.main(["--config", str(cfg), "run", "--yes"]) == 4
    out = capsys.readouterr().out
    assert not started
    assert "ARAÇ HATASI" in out and "ryzen-smu-cli.exe" in out and "WriteConsoleToWriteFile" in out
    assert "corecycler_dir" in out and "doctor" in out and "kur.bat" in out


def test_doctor_corecycler_dir_check_needs_an_existing_folder(tmp_path):
    """Gerçek olay: örnek yol (C:\\Tools\\CoreCycler) yok olduğu halde doctor "[TAMAM] config: corecycler_dir" diyordu."""
    assert cli.corecycler_dir_ok(str(tmp_path)) is True
    assert cli.corecycler_dir_ok(str(tmp_path / "yok")) is False
    assert cli.corecycler_dir_ok("") is False
    f = tmp_path / "dosya.txt"
    f.write_text("x")
    assert cli.corecycler_dir_ok(str(f)) is False                      # klasör değil, dosya
