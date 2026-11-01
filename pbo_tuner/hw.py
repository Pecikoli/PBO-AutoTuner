"""Windows donanım adaptörleri.

Bu dosyadaki *saf* fonksiyonlar (çıktı ayrıştırma, config üretme, wevtutil sorgusu) her
platformda test edilir. Windows'a özgü kısımlar (süreç başlatma, affinity, PowerShell) yalnızca
gerçek çalıştırmada kullanılır.

Üç dış araç kullanılır; hepsi CoreCycler paketinden gelir (kendi SMU kodu yazılmaz):
  - tools/ryzen-smu-cli/ryzen-smu-cli.exe   : CO oku/yaz  (PawnIO sürücüsü gerekir)
  - test_programs/y-cruncher/...            : stres testi
  - helpers/WriteConsoleToWriteFileWrapper  : y-cruncher konsol çıktısını log dosyasına alır
Komut satırları CoreCycler'ın kendi kullandığı biçimin birebir aynısıdır.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .i18n import tr

try:
    import psutil
except ImportError:  # doctor komutu bunu açıkça söyler
    psutil = None

# y-cruncher başına iş parçacığı belleği (CoreCycler varsayılanı: 1 iş parçacığı için ~12.8 MiB)
YC_MEMORY_PER_THREAD = 13418572
MAX_ABS_CO = 50  # ryzen-smu-cli -50'den derini uygulamaz (gerçek makinede -55 yazılınca -50 geri okundu)


class ToolError(Exception):
    """Dış araç çalışmadı/yanlış çalıştı. Kararsızlık DEĞİL; kurulum sorunu. Çalışmayı durdurur."""


class SmuVerifyError(ToolError):
    """CO yazıldı ama geri okunan değer farklı."""


@dataclass
class StressResult:
    passed: bool
    reason: str = ""
    elapsed: float = 0.0
    whea: list = field(default_factory=list)


# =====================================================================================
# Saf ayrıştırıcılar / üreticiler (testlenebilir)
# =====================================================================================

def parse_offsets_output(text: str, n_cores: int) -> list:
    """`ryzen-smu-cli --get-offsets-terse` çıktısı: son satır "-1,-1,-1,..." biçimindedir."""
    lines = [ln.strip().strip('"\'\t ') for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        raise ToolError(tr("ryzen-smu-cli boş çıktı verdi"))
    values = [int(tok) for tok in lines[-1].split(",") if re.fullmatch(r"\s*-?\d+\s*", tok)]
    if len(values) != n_cores:
        raise ToolError(tr("{n} CO değeri bekleniyordu, {got} geldi: {line!r}", n=n_cores, got=len(values), line=lines[-1]))
    if any(abs(v) > MAX_ABS_CO for v in values):
        raise ToolError(tr("mantıksız CO değeri okundu (|değer| > {max}): {values}", max=MAX_ABS_CO, values=values))
    return values


def yc_memory(n_threads: int) -> int:
    """CoreCycler varsayılanları: 1 iş parçacığı 13418572, 2 iş parçacığı 26567600 bayt; fazlası için doğrusal."""
    return {1: 13418572, 2: 26567600}.get(n_threads, YC_MEMORY_PER_THREAD * n_threads)


def build_ycruncher_config(cpus: list, seconds_per_test: int, tests: list) -> str:
    """CoreCycler'ın yazdığı stres testi config'inin aynısı. StopOnError=false: hatayı log'dan okuruz."""
    cores = " ".join(str(c) for c in cpus)
    mem = yc_memory(len(cpus))
    test_lines = "\n".join(f'            "{t}"' for t in tests)
    return (
        "{\n"
        '    Action : "StressTest"\n'
        "    StressTest : {\n"
        '        AllocateLocally : "true"\n'
        f"        LogicalCores : [{cores}]\n"
        f"        TotalMemory : {mem}\n"
        f"        SecondsPerTest : {seconds_per_test}\n"
        "        SecondsTotal : 0\n"
        '        StopOnError : "false"\n'
        "        Tests : [\n"
        f"{test_lines}\n"
        "        ]\n"
        "    }\n"
        "}\n"
    )


_YC_ERROR_RE = re.compile(r"error\(s\)|Exception Encountered", re.IGNORECASE)


def find_ycruncher_error(log_text: str) -> Optional[str]:
    """CoreCycler y-cruncher için `.*error\\(s\\).*` satırını arar; biz ayrıca 'Exception Encountered'."""
    hit = None
    for line in log_text.splitlines():
        if _YC_ERROR_RE.search(line):
            hit = line.strip()
    return hit


WHEA_CPU_EVENT_IDS = (18, 19)   # 18: ölümcül makine denetimi (MCE), 19: düzeltilmiş makine denetimi.
                                # 17/47 gibi PCIe düzeltilmiş hataları çekirdek kararsızlığı DEĞİLDİR.


def build_wevtutil_args(since: datetime) -> list:
    ts = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    ids = " or ".join(f"EventID={i}" for i in WHEA_CPU_EVENT_IDS)
    q = ("*[System[Provider[@Name='Microsoft-Windows-WHEA-Logger'] and "
         f"({ids}) and "
         f"TimeCreated[@SystemTime>='{ts}']]]")
    return ["wevtutil", "qe", "System", f"/q:{q}", "/f:xml"]


def make_cpu_to_apic(n_cores: int, smt: bool) -> Callable[[int], int]:
    """Windows mantıksal CPU numarası -> APIC ID. Her CCD APIC alanında 8 çekirdeklik yer ayırır; 6+6 gibi dolu olmayan
    iki CCD'li işlemcilerde ikinci CCD'nin APIC ID'leri boşluklu başlar (CoreCycler: 5900X'te çekirdek 6 = APIC 16/17).
    8+8, 8 ve 6 çekirdekli (tek CCD) işlemcilerde eşleme birebirdir. Boşluk kuralı bu araçta DOĞRULANMADI."""
    per_ccd = n_cores // 2 if n_cores > 8 else n_cores

    def f(cpu: int) -> int:
        core, sib = (cpu // 2, cpu % 2) if smt else (cpu, 0)
        ccd, idx = divmod(core, per_ccd)
        slot = ccd * 8 + idx
        return 2 * slot + sib if smt else slot

    return f


def whea_relevant(events: list, cpus: list, smt: bool, all_cores: bool = False,
                  cpu_to_apic: Optional[Callable[[int], int]] = None) -> list:
    """Sadece test edilen çekirdeğe ait (APIC ID eşleşen) olayları tut. APIC ID okunamadıysa temkinli sayılır
    (olay tutulur). Tüm-çekirdek testinde hepsi tutulur."""
    if all_cores:
        return list(events)
    wanted = {cpu_to_apic(c) if cpu_to_apic else c for c in cpus}
    keep = []
    for e in events:
        a = e.get("apic_id")
        if a is None or a in wanted or (smt and (a ^ 1) in wanted):
            keep.append(e)
    return keep


def parse_wevtutil_xml(text: str) -> list:
    """wevtutil çıktısı kök elemansız <Event> dizisidir; sarıp ayrıştırırız."""
    text = text.strip()
    if not text:
        return []
    text = re.sub(r"^<\?xml[^>]*\?>", "", text)
    root = ET.fromstring(f"<Events>{text}</Events>")
    out = []
    for ev in root:
        def find(path):
            for el in ev.iter():
                if el.tag.split("}")[-1] == path:
                    return el
            return None
        tc, eid = find("TimeCreated"), find("EventID")
        data = [(d.get("Name"), (d.text or "").strip()) for d in ev.iter() if d.tag.split("}")[-1] == "Data"]
        apic = None
        for name, val in data:
            if name and name.lower() == "apicid" and val.isdigit():
                apic = int(val)
        if apic is None and len(data) > 1 and data[1][1].isdigit():
            apic = int(data[1][1])  # CoreCycler: Properties[1] = APIC ID
        out.append({"time": tc.get("SystemTime") if tc is not None else "",
                    "event_id": int(eid.text) if eid is not None and (eid.text or "").isdigit() else None,
                    "apic_id": apic, "data": [v for _, v in data]})
    return out


# =====================================================================================
# ryzen-smu-cli
# =====================================================================================

class RyzenSmuCli:
    """CO'yu okur/yazar. Yazımdan sonra geri okuyup doğrular; farklıysa hata verir."""

    def __init__(self, exe: str, n_cores: int, timeout: float = 10.0, tries: int = 5,
                 runner: Optional[Callable] = None):
        self.exe, self.n_cores, self.timeout, self.tries = exe, n_cores, timeout, tries
        self._runner = runner or self._subprocess_runner

    @staticmethod
    def _subprocess_runner(args: list, timeout: float):
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    def _run(self, args: list) -> str:
        last = ""
        for attempt in range(1, self.tries + 1):
            try:
                code, out, err = self._runner([self.exe] + args, self.timeout)
            except subprocess.TimeoutExpired:
                last = tr("{sec:.0f} sn içinde bitmedi", sec=self.timeout)
            else:
                if code == 0 and not err.strip() and out.strip():
                    return out
                last = tr("çıkış kodu {code}; stderr={err!r}; stdout={out!r}", code=code, err=err.strip(), out=out.strip())
            time.sleep(0.5)  # ZenStates-Core ara sıra başarısız olur; CoreCycler da tekrar dener
        raise ToolError(tr("ryzen-smu-cli {args} başarısız ({tries} deneme): {last}",
                           args=" ".join(args), tries=self.tries, last=last))

    def get_offsets(self) -> list:
        return parse_offsets_output(self._run(["--get-offsets-terse"]), self.n_cores)

    def set_offsets(self, values: list) -> None:
        if len(values) != self.n_cores:
            raise ValueError(tr("{n} değer gerekli, {got} verildi", n=self.n_cores, got=len(values)))
        if any(not isinstance(v, int) or abs(v) > MAX_ABS_CO for v in values):
            raise ValueError(tr("geçersiz CO değerleri: {values}", values=values))
        arg = ",".join(str(v) for v in values)
        for attempt in range(2):
            self._run(["--offset", arg])
            if self.get_offsets() == list(values):
                return
        raise SmuVerifyError(tr("yazılan {written} ile geri okunan {read} farklı",
                                written=list(values), read=self.get_offsets()))


# =====================================================================================
# WHEA
# =====================================================================================

class WheaReader:
    def events_since(self, since: datetime) -> list:
        p = subprocess.run(build_wevtutil_args(since), capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            raise ToolError(tr("wevtutil başarısız: {err}", err=p.stderr.strip()))
        return parse_wevtutil_xml(p.stdout)


# =====================================================================================
# y-cruncher koşucusu
# =====================================================================================

class Pulser:
    """Stres sürecini kısa aralıklarla durdurup devam ettirir (suspend/resume): düşük ortalama yük ve sık
    boşta<->yük geçişi (voltaj/frekans geçişleri) oluşturur. Hedefler ve uyku dışarıdan verilir, böylece
    gerçek süreç olmadan test edilebilir."""

    def __init__(self, get_targets: Callable, on_ms: int, off_ms: int,
                 sleep: Callable = time.sleep, rng=None):
        import random
        import threading
        self.get_targets, self.on_ms, self.off_ms = get_targets, on_ms, off_ms
        self._sleep, self._rng = sleep, rng or random.Random()
        self._stop, self._thread, self.cycles = threading.Event(), None, 0

    def _jit(self, ms: int) -> float:
        return ms * self._rng.uniform(0.5, 1.5) / 1000.0     # her turda süreyi biraz değiştir

    def pulse_once(self) -> None:
        self._sleep(self._jit(self.on_ms))                    # çalışıyor
        suspended = []
        try:
            for t in self.get_targets():
                try:
                    t.suspend()
                    suspended.append(t)
                except Exception:  # noqa: BLE001
                    pass
            self._sleep(self._jit(self.off_ms))              # duruyor
        finally:
            for t in suspended:                               # ne olursa olsun devam ettir
                try:
                    t.resume()
                except Exception:  # noqa: BLE001
                    pass
        self.cycles += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.pulse_once()

    def start(self) -> None:
        import threading
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


class YCruncherRunner:
    GRACE = 8          # başlangıç/ısınma payı (sn)
    LOAD_WINDOW = 5    # CPU yükü ölçüm penceresi (sn)

    def __init__(self, cc_dir: str, work_dir: Path, mode: str, tests: list, seconds_per_test: int,
                 whea: Optional[WheaReader], whea_is_failure: bool = True, cpu_load_check: bool = True,
                 log: Callable[[str], None] = print, smt: bool = True, n_logical: int = 32,
                 light_mode: str = "19-ZN2 ~ Kagari", light_tests: Optional[list] = None,
                 pulse_on_ms: int = 300, pulse_off_ms: int = 700,
                 cpu_to_apic: Optional[Callable[[int], int]] = None):
        if psutil is None:
            raise ToolError(tr("psutil kurulu değil: pip install psutil"))
        cc = Path(cc_dir)
        self.wrapper = cc / "helpers" / "WriteConsoleToWriteFileWrapper.exe"
        bins = cc / "test_programs" / "y-cruncher" / "Binaries"
        self.exe = bins / f"{mode}.exe"
        self.light_exe = bins / f"{light_mode}.exe"
        self.work = Path(work_dir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.tests, self.sec = tests, seconds_per_test
        self.light_tests = light_tests or ["BKT", "BBP", "SNT"]
        self.pulse_on_ms, self.pulse_off_ms = pulse_on_ms, pulse_off_ms
        self.whea, self.whea_fail, self.load_check, self.log = whea, whea_is_failure, cpu_load_check, log
        self.smt, self.n_logical = smt, n_logical
        self.cpu_to_apic = cpu_to_apic

    def check_files(self) -> list:
        return [str(p) for p in (self.wrapper, self.exe, self.light_exe) if not p.exists()]

    # -- süreç ---------------------------------------------------------------------
    def _spawn(self, cpus: list, cfg_path: Path, log_path: Path, exe: Optional[Path] = None):
        exe = exe or self.exe
        # CoreCycler'ın 'commandWithLogging' biçimi (tırnaklar önemli: /dlllog:"...")
        cmdline = (f'"{self.wrapper}" "{exe}" priority:-1 config "{cfg_path}" '
                   f'/dlllog:"{log_path}"')
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINNOACTIVE: simge durumunda, odağı çalmaz
        me = psutil.Process()
        old = me.cpu_affinity()
        me.cpu_affinity(cpus)  # çocuk süreçler affinity'yi devralır
        try:
            return subprocess.Popen(cmdline, startupinfo=si, cwd=str(exe.parent),
                                    creationflags=subprocess.CREATE_NEW_CONSOLE)
        finally:
            me.cpu_affinity(old)

    @staticmethod
    def _kill_tree(proc) -> None:
        try:
            parent = psutil.Process(proc.pid)
            for ch in parent.children(recursive=True):
                try:
                    ch.kill()
                except psutil.Error:
                    pass
            parent.kill()
        except psutil.Error:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    @staticmethod
    def _tree_cpu_seconds(proc) -> float:
        total = 0.0
        try:
            root = psutil.Process(proc.pid)
            for p in [root] + root.children(recursive=True):
                try:
                    t = p.cpu_times()
                    total += t.user + t.system
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        return total

    @staticmethod
    def _read_log(path: Path) -> str:
        try:
            return path.read_bytes().decode("latin-1", errors="ignore")
        except OSError:
            return ""

    # -- boşta bekleme ---------------------------------------------------------------
    def _idle(self, seconds: int, label: str) -> StressResult:
        """Hiç yük bindirmeden bekler; yalnızca WHEA'yı izler. Asıl tespit: sistem çökerse devam mantığı yakalar."""
        t0 = time.time()
        since = datetime.now(timezone.utc)
        last = t0
        while True:
            time.sleep(1.0)
            now = time.time()
            if self.whea_fail and self.whea and now - last >= 30:
                last = now
                ev = whea_relevant(self.whea.events_since(since), [], self.smt, all_cores=True)
                if ev:
                    return StressResult(False, tr("WHEA hatası (boşta, {n} olay)", n=len(ev)), now - t0, ev)
            if now - t0 >= seconds:
                break
        if self.whea_fail and self.whea:
            ev = whea_relevant(self.whea.events_since(since), [], self.smt, all_cores=True)
            if ev:
                return StressResult(False, tr("WHEA hatası (boşta, {n} olay)", n=len(ev)), time.time() - t0, ev)
        return StressResult(True, "", time.time() - t0)

    # -- ana işlev -----------------------------------------------------------------
    def run(self, cpus: list, seconds: int, label: str, profile: str = "heavy") -> StressResult:
        """profile: 'heavy' (varsayılan, AVX-512 ağır yük), 'light' (hafif yük + aralıklı durdurma), 'idle' (yük yok)."""
        if profile == "idle":
            return self._idle(seconds, label)
        light = profile == "light"
        exe = self.light_exe if light else self.exe
        tests = self.light_tests if light else self.tests

        t0 = time.time()
        since = datetime.now(timezone.utc)
        stamp = f"{label}_{int(t0)}"
        cfg_path, log_path = self.work / f"{stamp}.cfg", self.work / f"{stamp}.log"
        cfg_path.write_text(build_ycruncher_config(cpus, self.sec, tests))
        deadline = t0 + seconds + self.GRACE
        expected_load = 0.5 * len(cpus)   # CPU-saniye / duvar-saniye
        all_cores = len(cpus) >= self.n_logical
        use_load_check = self.load_check and not light     # aralıklı durdurmada ortalama yük zaten düşük

        proc = self._spawn(cpus, cfg_path, log_path, exe)
        holder = {"proc": proc}
        started = time.time()
        last_load_t, last_load_cpu, low_windows, last_whea = started, self._tree_cpu_seconds(proc), 0, started

        pulser = None
        if light:
            exe_name = exe.name.lower()

            def targets():
                try:
                    root = psutil.Process(holder["proc"].pid)
                    return [p for p in root.children(recursive=True) if p.name().lower() == exe_name]
                except psutil.Error:
                    return []

            pulser = Pulser(targets, self.pulse_on_ms, self.pulse_off_ms)
            pulser.start()

        def fail(reason: str, whea=None) -> StressResult:
            return StressResult(False, reason, time.time() - t0, whea or [])

        try:
            while True:
                time.sleep(1.0)
                now = time.time()

                err = find_ycruncher_error(self._read_log(log_path))
                if err:
                    return fail(f"y-cruncher: {err}")

                if self.whea_fail and self.whea and now - last_whea >= 5:
                    last_whea = now
                    ev = whea_relevant(self.whea.events_since(since), cpus, self.smt, all_cores, self.cpu_to_apic)
                    if ev:
                        return fail(tr("WHEA hatası ({n} olay, APIC {apic})", n=len(ev), apic=[e['apic_id'] for e in ev]), ev)

                if proc.poll() is not None:
                    err = find_ycruncher_error(self._read_log(log_path))
                    if err:
                        return fail(f"y-cruncher: {err}")
                    if now - started < 3:
                        raise ToolError(tr("y-cruncher başlamadı (çıkış kodu {code}). `doctor` komutunu çalıştırın. Log: {log}",
                                           code=proc.returncode, log=log_path))
                    if proc.returncode not in (0, None):
                        return fail(tr("y-cruncher beklenmedik şekilde kapandı (çıkış kodu {code})", code=proc.returncode))
                    if now >= deadline:
                        break
                    proc = self._spawn(cpus, cfg_path, log_path, exe)  # bir döngü bitti, süre kaldı
                    holder["proc"] = proc
                    started = time.time()
                    last_load_t, last_load_cpu = started, self._tree_cpu_seconds(proc)
                    continue

                if use_load_check and now - started > self.GRACE and now - last_load_t >= self.LOAD_WINDOW:
                    cpu = self._tree_cpu_seconds(proc)
                    load = (cpu - last_load_cpu) / (now - last_load_t)
                    last_load_t, last_load_cpu = now, cpu
                    low_windows = low_windows + 1 if load < expected_load else 0
                    if low_windows >= 2:
                        return fail(tr("stres süreci CPU kullanmıyor (yük {load:.2f}, beklenen >= {expected:.2f})",
                                       load=load, expected=expected_load))

                if now >= deadline:
                    break
        finally:
            if pulser:
                pulser.stop()                # süreç dondurulmuş kalmasın
            self._kill_tree(proc)

        # Olay günlüğüne düşme gecikmesi için kısa bekle, son kez WHEA'ya bak
        if self.whea_fail and self.whea:
            time.sleep(2)
            ev = whea_relevant(self.whea.events_since(since), cpus, self.smt, all_cores, self.cpu_to_apic)
            if ev:
                return fail(tr("WHEA hatası ({n} olay, APIC {apic})", n=len(ev), apic=[e['apic_id'] for e in ev]), ev)
        err = find_ycruncher_error(self._read_log(log_path))
        if err:
            return fail(f"y-cruncher: {err}")
        return StressResult(True, "", time.time() - t0)

# =====================================================================================
# Etkin frekans ölçümü (yaklaşık; sadece rapor için)
# =====================================================================================

class BoostMeter:
    """Çekirdeğe hafif bir döngü bindirip WMI'dan etkin frekansı okur.
    Sınıf/özellik adları İngilizce'dir, Windows dili Türkçe olsa da çalışır.
    Sonuç yaklaşıktır (Task Manager'ın 'Hız' sütunuyla aynı kaynak)."""

    def measure(self, cpu: int, seconds: int = 7) -> Optional[float]:
        if psutil is None or os.name != "nt":
            return None
        me = psutil.Process()
        old = me.cpu_affinity()
        me.cpu_affinity([cpu])
        try:
            burner = subprocess.Popen([sys.executable, "-c", "while True: pass"])
        finally:
            me.cpu_affinity(old)
        try:
            time.sleep(1.5)
            n = max(3, seconds - 1)
            # Çift tırnak kullanma: komut satırı kaçışı sorunu çıkarmasın. Sınıf/özellik adları İngilizce.
            ps = (f"for($i=0;$i -lt {n};$i++){{ "
                  f"$o=Get-CimInstance -ClassName Win32_PerfFormattedData_Counters_ProcessorInformation "
                  f"| Where-Object {{ $_.Name -eq '0,{cpu}' }}; "
                  f"Write-Output ($o.PercentProcessorPerformance.ToString() + ',' + $o.ProcessorFrequency.ToString()); "
                  f"Start-Sleep -Milliseconds 700 }}")
            p = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=60)
            vals = []
            for line in p.stdout.splitlines():
                m = re.fullmatch(r"\s*(\d+),(\d+)\s*", line)
                if m and int(m.group(2)) > 0:
                    vals.append(int(m.group(1)) / 100.0 * int(m.group(2)))
            if len(vals) < 3:
                return None
            vals = sorted(vals[1:])
            return round(vals[len(vals) // 2], 0)
        except Exception:
            return None
        finally:
            burner.kill()


# =====================================================================================
# Birleşik donanım nesnesi
# =====================================================================================

@dataclass
class Hardware:
    smu: object
    stress: object
    boost: object
    n_cores: int
    smt: bool
    boot_time: Callable[[], float]
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep

    def cpus_for_core(self, core: int, threads: int = 1) -> list:
        if self.smt:
            base = 2 * core
            return [base] if threads == 1 else [base, base + 1]
        return [core]

    def all_cpus(self) -> list:
        return list(range(self.n_cores * (2 if self.smt else 1)))


def detect_topology(cfg_cores: int = 0, cfg_smt: Optional[bool] = None) -> tuple:
    if psutil is None:
        raise ToolError(tr("psutil kurulu değil: pip install psutil"))
    phys = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0
    cores = cfg_cores or phys
    smt = cfg_smt if cfg_smt is not None else (logical >= 2 * phys > 0)
    return cores, smt


def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def make_real_hardware(cfg, log: Callable[[str], None] = print) -> Hardware:
    if os.name != "nt":
        raise ToolError(tr("Gerçek donanım modu yalnızca Windows'ta çalışır (deneme için --simulate kullanın)."))
    if not cfg.corecycler_dir:
        raise ToolError(tr("config.toml içinde [paths] corecycler_dir ayarlanmamış."))
    from .generations import resolve_generation      # burada: generations, hw'yi içe aktarır (döngü olmasın)
    resolve_generation(cfg, log)
    cc = Path(cfg.corecycler_dir)
    n_cores, smt = detect_topology(cfg.cores, cfg.smt)
    smu = RyzenSmuCli(str(cc / "tools" / "ryzen-smu-cli" / "ryzen-smu-cli.exe"), n_cores)
    whea = WheaReader()
    stress = YCruncherRunner(str(cc), cfg.data_path / "stress", cfg.mode, cfg.tests, cfg.seconds_per_test,
                             whea, cfg.whea_is_failure, cfg.cpu_load_check, log, smt=smt,
                             n_logical=n_cores * (2 if smt else 1), light_mode=cfg.lowload_mode,
                             light_tests=cfg.lowload_tests, pulse_on_ms=cfg.lowload_pulse_on_ms,
                             pulse_off_ms=cfg.lowload_pulse_off_ms, cpu_to_apic=make_cpu_to_apic(n_cores, smt))
    return Hardware(smu=smu, stress=stress, boost=BoostMeter(), n_cores=n_cores, smt=smt,
                    boot_time=psutil.boot_time)
