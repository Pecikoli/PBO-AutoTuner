"""Windows adaptörlerinin saf (platformdan bağımsız) kısımları: ayrıştırıcılar ve komut üreticiler."""
from datetime import datetime, timezone

import pytest

from pbo_tuner.hw import (RyzenSmuCli, SmuVerifyError, ToolError, build_wevtutil_args, build_ycruncher_config,
                          find_ycruncher_error, parse_offsets_output, parse_wevtutil_xml, Hardware)


def test_parse_offsets_terse_with_banner_lines():
    out = "[ZenStates-Core] init\nCurrent PBO offsets:\n-20,-15,0,-30,-5,-5,-10,-12,-1,0,0,-3,-4,-25,-26,-27\n\n"
    assert parse_offsets_output(out, 16) == [-20, -15, 0, -30, -5, -5, -10, -12, -1, 0, 0, -3, -4, -25, -26, -27]


def test_parse_offsets_rejects_wrong_count_and_absurd_values():
    with pytest.raises(ToolError):
        parse_offsets_output("-1,-1,-1", 16)
    with pytest.raises(ToolError):
        parse_offsets_output(",".join(["-99"] * 16), 16)
    with pytest.raises(ToolError):
        parse_offsets_output("", 16)


def test_ycruncher_config_matches_corecycler_format():
    cfg = build_ycruncher_config([12], 20, ["SFTv4", "FFTv4", "N63"])
    assert 'Action : "StressTest"' in cfg
    assert "LogicalCores : [12]" in cfg
    assert "TotalMemory : 13418572" in cfg
    assert "SecondsPerTest : 20" in cfg and 'StopOnError : "false"' in cfg
    assert '"SFTv4"' in cfg and '"N63"' in cfg
    cfg2 = build_ycruncher_config([2, 3], 20, ["N63"])
    assert "LogicalCores : [2 3]" in cfg2 and "TotalMemory : 26567600" in cfg2
    cfg_all = build_ycruncher_config(list(range(32)), 20, ["N63"])
    assert f"TotalMemory : {32 * 13418572}" in cfg_all


def test_ycruncher_error_detection():
    ok_log = "Running Stress Test...\nPassed  FFTv4  Speed 1.2\nPassed  N63\n"
    bad_log = ok_log + "\nError(s) encountered on logical core 12\nFailed  SFTv4\nErrors encountered. Stopping test...\n"
    exc_log = "Exception Encountered: Hardware failure\n"
    assert find_ycruncher_error(ok_log) is None
    assert "Error(s)" in find_ycruncher_error(bad_log)
    assert find_ycruncher_error(exc_log).startswith("Exception Encountered")


def test_wevtutil_query_uses_utc_and_whea_provider():
    since = datetime(2026, 10, 30, 14, 5, 7, tzinfo=timezone.utc)
    args = build_wevtutil_args(since)
    assert args[:3] == ["wevtutil", "qe", "System"]
    q = args[3]
    assert "Microsoft-Windows-WHEA-Logger" in q and "2026-10-30T14:05:07.000Z" in q
    assert "EventID=18" in q and "EventID=19" in q and "EventID=17" not in q   # PCIe hataları sayılmaz


WHEA_XML = """<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>
<Provider Name='Microsoft-Windows-WHEA-Logger' Guid='{c26c4f3c}'/><EventID>19</EventID><Level>3</Level>
<TimeCreated SystemTime='2026-10-30T14:06:00.123456700Z'/></System>
<EventData><Data Name='ErrorSource'>1</Data><Data Name='ApicId'>12</Data><Data Name='MCABank'>5</Data></EventData></Event>
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><EventID>18</EventID>
<TimeCreated SystemTime='2026-10-30T14:07:00.000000000Z'/></System>
<EventData><Data>0</Data><Data>30</Data></EventData></Event>"""


def test_parse_wevtutil_xml_extracts_apic_ids():
    ev = parse_wevtutil_xml(WHEA_XML)
    assert [e["event_id"] for e in ev] == [19, 18]
    assert ev[0]["apic_id"] == 12 and ev[1]["apic_id"] == 30      # adlı ve konumsal (Properties[1])
    assert parse_wevtutil_xml("") == []


class FakeCli:
    """ryzen-smu-cli taklidi: --offset yazar, --get-offsets-terse okur."""
    def __init__(self, n=16, drop_writes=False, fail_first=0):
        self.state, self.drop, self.fail_first, self.calls = [0] * n, drop_writes, fail_first, []

    def __call__(self, args, timeout):
        self.calls.append(args[1:])
        if self.fail_first > 0:
            self.fail_first -= 1
            return 1, "", "ZenStates-Core hatası"
        if args[1] == "--get-offsets-terse":
            return 0, "Current PBO offsets:\n" + ",".join(map(str, self.state)) + "\n", ""
        if args[1] == "--offset":
            if not self.drop:
                self.state = [int(x) for x in args[2].split(",")]
            return 0, "Set: " + args[2] + "\n", ""
        return 1, "", "bilinmeyen"


def test_smu_set_verifies_by_readback(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    fake = FakeCli()
    cli = RyzenSmuCli("x.exe", 16, runner=fake)
    vals = [-10] * 8 + [0] * 8
    cli.set_offsets(vals)
    assert fake.state == vals
    assert cli.get_offsets() == vals


def test_smu_set_detects_silent_failure(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cli = RyzenSmuCli("x.exe", 16, runner=FakeCli(drop_writes=True))
    with pytest.raises(SmuVerifyError):
        cli.set_offsets([-5] * 16)


def test_smu_retries_transient_zenstates_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cli = RyzenSmuCli("x.exe", 16, runner=FakeCli(fail_first=3))
    assert cli.get_offsets() == [0] * 16


def test_smu_gives_up_after_tries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    cli = RyzenSmuCli("x.exe", 16, tries=3, runner=FakeCli(fail_first=99))
    with pytest.raises(ToolError):
        cli.get_offsets()


def test_smu_rejects_out_of_range_values():
    cli = RyzenSmuCli("x.exe", 16, runner=FakeCli())
    with pytest.raises(ValueError):
        cli.set_offsets([-51] + [0] * 15)
    with pytest.raises(ValueError):
        cli.set_offsets([0] * 15)


def test_core_to_cpu_mapping_smt_and_no_smt():
    hw = Hardware(smu=None, stress=None, boost=None, n_cores=16, smt=True, boot_time=lambda: 0)
    assert hw.cpus_for_core(0) == [0] and hw.cpus_for_core(5) == [10]
    assert hw.cpus_for_core(5, 2) == [10, 11]
    assert hw.all_cpus() == list(range(32))
    hw2 = Hardware(smu=None, stress=None, boost=None, n_cores=16, smt=False, boot_time=lambda: 0)
    assert hw2.cpus_for_core(5) == [5] and hw2.all_cpus() == list(range(16))


def test_whea_relevance_filters_other_cores():
    from pbo_tuner.hw import whea_relevant
    ev = [{"apic_id": 12}, {"apic_id": 13}, {"apic_id": 4}, {"apic_id": None}]
    # çekirdek 6 = CPU 12 (SMT kardeşi 13)
    got = whea_relevant(ev, [12], smt=True)
    assert [e["apic_id"] for e in got] == [12, 13, None]
    assert [e["apic_id"] for e in whea_relevant(ev, [12], smt=False)] == [12, None]
    assert len(whea_relevant(ev, list(range(32)), smt=True, all_cores=True)) == 4


# ----------------------------------------------------------------------------- eksik program dosyası
def test_missing_ryzen_smu_cli_gives_a_clear_tool_error_instead_of_a_traceback():
    """Gerçek olay: corecycler_dir yanlıştı, subprocess FileNotFoundError ([WinError 2]) ham hata izi bastı."""
    from pbo_tuner.hw import RyzenSmuCli, ToolError

    calls = []

    def runner(args, timeout):
        calls.append(args)
        raise FileNotFoundError(2, "Sistem belirtilen dosyayı bulamıyor")

    smu = RyzenSmuCli(r"C:\Tools\CoreCycler\tools\ryzen-smu-cli\ryzen-smu-cli.exe", 4, runner=runner)
    with pytest.raises(ToolError) as e:
        smu.set_offsets([0, 0, 0, 0])
    text = str(e.value)
    assert "ryzen-smu-cli.exe" in text and "corecycler_dir" in text and "doctor" in text
    assert len(calls) == 1                                              # yok olan dosya için tekrar denenmez


def test_permission_error_is_also_reported_as_tool_error():
    from pbo_tuner.hw import RyzenSmuCli, ToolError

    def runner(args, timeout):
        raise PermissionError(13, "Erişim engellendi")

    with pytest.raises(ToolError, match="başlatılamadı"):
        RyzenSmuCli("x.exe", 4, runner=runner).get_offsets()
