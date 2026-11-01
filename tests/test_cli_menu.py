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
