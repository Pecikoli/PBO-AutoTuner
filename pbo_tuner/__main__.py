"""Komut satırı.  python -m pbo_tuner <komut>"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__, i18n
from .config import Config, ConfigError, load_config, quick_preset
from .hw import ToolError, WheaReader, detect_topology, is_admin, make_real_hardware, psutil
from .i18n import mark, tr
from .report import build_report, write_report
from .state import STAGE_DONE, StateStore
from .tuner import Halted, Tuner, prepare_lowload, search_params

TASK_NAME = "PBO AutoTuner Resume"
CONFIRM_WORDS = ("EVET", "YES")      # iki dilde de kabul edilir; ekranda dile göre biri istenir

BANNER = mark("""
================================================================================
 PBO AutoTuner - UYARI
 * Bu araç işlemcinin voltaj/frekans eğrisini (Curve Optimizer) CANLI değiştirir ve
   bilerek kararsız ayarlara iner. Çökme, mavi ekran, kendiliğinden yeniden başlatma
   BEKLENEN davranıştır. Çalışma durumu diske kaydedilir ve devam eder.
 * Çalışırken önemli dosyalarını kaydet/kapat. Windows kurulumunun bozulma riskine karşı
   bir sistem geri yükleme noktası oluşturman önerilir.
 * Anakartta BIOS'ta Curve Optimizer = Auto/0 olmalı (araç test sırasında kendi değerlerini yazar).
 * Sistem DONARSA (yeniden başlamaz) reset tuşuna bas; araç kaldığı yerden devam eder.
 * Garanti/hasar sorumluluğu sana aittir. PBO/undervolt garantiyi etkileyebilir.
================================================================================
""")


def confirmed(prompt: str) -> bool:
    return input(prompt).strip() in CONFIRM_WORDS


# ----------------------------------------------------------------------------- yardımcı
def make_logger(cfg: Config):
    path = cfg.data_path / "tuner.log"
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d')} {line}\n")
        except OSError:
            pass

    return log


def load(args) -> Config:
    cfg_path = args.config
    if cfg_path is None and Path("config.toml").exists():
        cfg_path = "config.toml"
    cfg = load_config(cfg_path)
    base = Path(cfg_path).resolve().parent if cfg_path else Path(__file__).resolve().parent.parent
    if not Path(cfg.data_dir).is_absolute():
        cfg.data_dir = str((base / cfg.data_dir).resolve())
    if getattr(args, "simulate", False):
        cfg.data_dir += "_sim"           # gerçek çalışma durumuna asla karışmasın
    if getattr(args, "quick", False):
        quick_preset(cfg)
    return cfg


def store_for(cfg: Config) -> StateStore:
    return StateStore(cfg.data_path / "state.json")


def get_hw(cfg: Config, args, log):
    if getattr(args, "simulate", False):
        import random
        from .sim import SimCPU
        rng = random.Random(args.seed)
        limits = [rng.randint(8, 45) for _ in range(16)]
        log(tr("[SİMÜLASYON] gizli çekirdek limitleri: {limits}", limits=limits))
        sim = SimCPU(limits, seed=args.seed, crash_prob=0.5)
        return sim.hardware(), sim
    return make_real_hardware(cfg, log), None


def disable_quickedit() -> None:
    """Konsola tıklamak çıktıyı dondurur (QuickEdit). Uzun çalışmada tuner'ı bekletmesin diye kapat."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value | 0x80) & ~0x40)   # EXTENDED_FLAGS aç, QUICK_EDIT kapat
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- komutlar
def cmd_run(args) -> int:
    cfg = load(args)
    log = make_logger(cfg)
    store = store_for(cfg)

    if args.fresh and store.exists():
        bak = store.path.with_suffix(f".bak{int(time.time())}")
        store.path.rename(bak)
        log(tr("Önceki durum yedeklendi: {name}", name=bak.name))

    if args.auto_resume:
        st = store.load(search_params(cfg)) if store.exists() else None
        if st is None or st.stage == STAGE_DONE:
            return 0                      # yapılacak iş yok; sessizce çık
        if st.halted:
            log(tr("Otomatik devam atlandı: araç güvenlik için durdurulmuştu. `run --force` ile elle başlatın."))
            return 3
        log(tr("Otomatik devam: {sec} sn sonra başlıyor (Ctrl+C ile iptal)...", sec=cfg.resume_delay_seconds))
        try:
            time.sleep(cfg.resume_delay_seconds)
        except KeyboardInterrupt:
            return 130
    elif not args.simulate and not args.yes and not store.exists():
        print(tr(BANNER))
        if not confirmed(tr("Devam etmek için EVET yaz: ")):
            print(tr("İptal edildi."))
            return 1

    if not args.simulate and not is_admin():
        print(tr("HATA: Yönetici olarak çalıştırın (SMU erişimi için gerekli)."))
        return 2
    disable_quickedit()

    try:
        hw, sim = get_hw(cfg, args, log)
        if sim is not None:
            from .sim import run_with_reboots
            st = run_with_reboots(cfg, sim, store, log=log, force_on_halt=args.force)
            if st is None:
                return 3
        else:
            st = Tuner(cfg, hw, store, log=log, force=args.force).run()
    except Halted as e:
        log(tr("DURDURULDU: {e}", e=e))
        return 3
    except ToolError as e:
        log(tr("ARAÇ HATASI: {e}", e=e))
        log(tr("`python -m pbo_tuner doctor` ile ortamı kontrol edin."))
        return 4
    except KeyboardInterrupt:
        log(tr("Kullanıcı tarafından durduruldu. İlerleme kaydedildi; `run` ile devam edebilirsiniz."))
        return 130

    path = write_report(st, cfg)
    print()
    print(path.read_text(encoding="utf-8"))
    log(tr("Rapor yazıldı: {path}", path=path))
    if not args.simulate:
        remove_autostart(quiet=True)
    return 0


def cmd_lowload(args) -> int:
    """Bitmiş çalışmanın nihai CO değerleriyle düşük yük + boşta bekleme testi."""
    import argparse as _ap
    cfg = load(args)
    if args.seconds:
        cfg.lowload_seconds = args.seconds
    if args.idle_minutes is not None:
        cfg.idle_minutes = args.idle_minutes
    cfg.validate()
    store = store_for(cfg)
    st = store.load(search_params(cfg)) if store.exists() else None
    if st is None or st.stage != STAGE_DONE or not st.final:
        print(tr("Düşük yük testi için önce normal çalışmanın bitmiş olması gerekir."))
        return 1
    n = len(st.final)
    est = (n * (cfg.lowload_seconds + 12) + cfg.idle_minutes * 60) // 60
    print(tr("Test edilecek CO değerleri: ") + ", ".join(f"{c}:-{a}" for c, a in sorted(st.final.items())))
    print(tr("Plan: her çekirdekte ~{sec} sn hafif + aralıklı yük (tüm CO'lar uygulanmış), sonra "
             "{idle} dk boşta bekleme. Yaklaşık {est} dk.", sec=cfg.lowload_seconds, idle=cfg.idle_minutes, est=est))
    print(tr("Kalan çekirdek 2 geri çekilip yeniden denenir. Boşta beklerken bilgisayara dokunma; uyku modunu kapat."))
    if not args.yes and not confirmed(tr("Devam etmek için EVET yaz: ")):
        print(tr("İptal edildi."))
        return 1
    try:
        prepare_lowload(cfg, store)
    except ToolError as e:
        print(tr("Hata: {e}", e=e))
        return 1
    ns = _ap.Namespace(config=args.config, quick=False, fresh=False, force=False, yes=True,
                       auto_resume=False, simulate=False, seed=1)
    return cmd_run(ns)


def cmd_status(args) -> int:
    cfg = load(args)
    store = store_for(cfg)
    st = store.load(search_params(cfg)) if store.exists() else None
    if st is None:
        print(tr("Kayıtlı çalışma yok."))
        return 0
    print(tr("Aşama: {stage}   çökme: {crashes}   durduruldu: {halted}   bekleyen test: {pending}",
             stage=st.stage, crashes=st.total_crashes, halted=st.halted, pending=st.pending))
    print(tr("Çekirdek  faz       kararlı  kararsız  aday  nihai  çökme"))
    for c, cs in st.searches.items():
        print(f"{c:>7}   {cs.phase:<8} {-cs.stable:>8} {('-' + str(cs.unstable)) if cs.unstable else '-':>9} "
              f"{('-' + str(cs.candidate)) if cs.candidate else '-':>5} "
              f"{('-' + str(cs.final)) if cs.final is not None else '-':>6} {cs.crashes:>6}")
    return 0


def cmd_report(args) -> int:
    cfg = load(args)
    st = store_for(cfg).load(search_params(cfg))
    if st is None:
        print(tr("Kayıtlı çalışma yok."))
        return 1
    text, _ = build_report(st, cfg)
    print(text)
    write_report(st, cfg)
    return 0


def cmd_apply(args) -> int:
    cfg = load(args)
    st = store_for(cfg).load(search_params(cfg))
    if st is None or not st.final:
        print(tr("Uygulanacak nihai değer yok (arama + doğrulama bitmeli)."))
        return 1
    if st.stage != STAGE_DONE and not args.yes:
        print(tr("Uyarı: çalışma bitmedi (aşama: {stage}). Yine de uygulamak için --yes ekleyin.", stage=st.stage))
        return 1
    hw = make_real_hardware(cfg)
    values = [-st.final.get(c, 0) for c in range(hw.n_cores)]
    hw.smu.set_offsets(values)
    print(tr("Uygulandı (geçici, yeniden başlatınca silinir): {values}", values=values))
    return 0


def cmd_reset(args) -> int:
    cfg = load(args)
    hw = make_real_hardware(cfg)
    hw.smu.set_offsets([0] * hw.n_cores)
    print(tr("Tüm çekirdeklerin CO değeri 0'a çekildi (geçici)."))
    return 0


# ----------------------------------------------------------------------------- otomatik devam
def _bat_path() -> Path:
    return Path(__file__).resolve().parent.parent / "resume.bat"


def install_autostart(cfg_path: str | None) -> int:
    if os.name != "nt":
        print(tr("Yalnızca Windows."))
        return 1
    import subprocess
    root = Path(__file__).resolve().parent.parent
    cfg_arg = f' --config "{Path(cfg_path).resolve()}"' if cfg_path else ""
    bat = _bat_path()
    bat.write_text(f'@echo off\r\ncd /d "{root}"\r\n"{sys.executable}" -m pbo_tuner run --auto-resume{cfg_arg}\r\nif errorlevel 1 pause\r\n')
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/RL", "HIGHEST",
                        "/DELAY", "0000:30", "/F", "/TR", f'"{bat}"'], capture_output=True, text=True)
    if r.returncode != 0:
        print(tr("Görev oluşturulamadı (yönetici olarak çalıştırın):"), r.stderr or r.stdout)
        return 1
    print(tr("Oturum açılışında otomatik devam görevi kuruldu: '{name}'.", name=TASK_NAME))
    print(tr("ÖNEMLİ: çökmeden sonra kendiliğinden devam için Windows'un otomatik oturum açması gerekir"))
    print(tr("(Sysinternals Autologon: https://learn.microsoft.com/sysinternals/downloads/autologon)."))
    return 0


def remove_autostart(quiet: bool = False) -> int:
    if os.name != "nt":
        return 0
    import subprocess
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    if not quiet:
        print(tr("Görev silindi.") if r.returncode == 0 else tr("Görev bulunamadı/silinemedi."))
    return 0


# ----------------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    cfg = load(args)
    ok_all = True

    def check(name: str, ok: bool, detail: str = "") -> bool:
        nonlocal ok_all
        ok_all &= ok
        print(f"[{tr('TAMAM' if ok else 'HATA'):^5}] {name}" + (f" - {detail}" if detail else ""))
        return ok

    print(tr("PBO AutoTuner {version} ortam kontrolü", version=__version__) + "\n")
    check(tr("Windows"), os.name == "nt", sys.platform)
    check(tr("Yönetici hakları"), is_admin())
    check(tr("psutil kurulu"), psutil is not None, "pip install psutil" if psutil is None else "")
    if os.name != "nt" or psutil is None:
        return 1
    check(tr("config: corecycler_dir"), bool(cfg.corecycler_dir),
          cfg.corecycler_dir or tr("config.toml [paths] içine yazın"))
    if not cfg.corecycler_dir:
        return 1

    n, smt = detect_topology(cfg.cores, cfg.smt)
    check(tr("Çekirdek topolojisi"), n > 0,
          tr("{n} çekirdek, SMT {state}", n=n, state=tr("açık") if smt else tr("kapalı")))

    hw = make_real_hardware(cfg)
    missing = hw.stress.check_files()
    check(tr("y-cruncher + log sarmalayıcı dosyaları"), not missing, ", ".join(missing))
    smu_exe = Path(hw.smu.exe)
    check("ryzen-smu-cli.exe", smu_exe.exists(), str(smu_exe))
    if missing or not smu_exe.exists():
        return 1

    try:
        cur = hw.smu.get_offsets()
        check(tr("CO okuma (PawnIO + ryzen-smu-cli)"), True, tr("mevcut değerler: {cur}", cur=cur))
        if any(cur):
            print(tr("       Not: BIOS'ta CO ayarlı. Araç test sırasında kendi değerlerini yazar; BIOS'ta 0/Auto önerilir."))
        hw.smu.set_offsets(cur)       # mevcut değerleri aynen geri yaz (değişiklik yok) + geri okuma doğrulaması
        check(tr("CO yazma + geri okuma doğrulaması"), True, tr("(mevcut değerler aynen yazıldı)"))
    except ToolError as e:
        check(tr("CO okuma/yazma"), False, str(e))
        print(tr("       PawnIO yüklü mü? https://pawnio.eu  | CoreCycler 0.11+ sürümünü kullandığınızdan emin olun."))
        return 1

    try:
        ev = WheaReader().events_since(datetime.now(timezone.utc) - timedelta(days=30))
        check(tr("WHEA olay günlüğü okuma"), True, tr("son 30 günde {n} WHEA olayı", n=len(ev)))
        if ev:
            print(tr("       Uyarı: geçmişte WHEA olayları var; bu normal olabilir ama araç yalnızca test sırasındakileri sayar."))
    except Exception as e:  # noqa: BLE001
        check(tr("WHEA olay günlüğü okuma"), False, str(e))

    print("\n" + tr("y-cruncher ön testi (çekirdek 0, ~15 sn, mevcut CO ile)..."))
    try:
        res = hw.stress.run(hw.cpus_for_core(0, cfg.threads_per_core), 15, "doctor")
        check(tr("y-cruncher çalıştı ve hata bildirmedi"), res.passed, res.reason)
        logs = sorted((cfg.data_path / "stress").glob("doctor_*.log"))
        if logs:
            tail = logs[-1].read_bytes().decode("latin-1", errors="ignore").strip().splitlines()[-6:]
            print(tr("       log sonu:"))
            for ln in tail:
                print("         " + ln)
        else:
            check(tr("y-cruncher log dosyası oluştu"), False,
                  tr("log yok: sarmalayıcı çalışmıyor olabilir (Defender/AV?)"))
    except ToolError as e:
        check("y-cruncher", False, str(e))

    print("\n" + tr("Boost ölçümü deneniyor (çekirdek 0)..."))
    mhz = hw.boost.measure(hw.cpus_for_core(0)[0])
    check(tr("Etkin frekans ölçümü (isteğe bağlı)"), mhz is not None,
          f"{mhz} MHz" if mhz else tr("ölçülemedi; rapor MHz'siz olur"))

    print("\n" + (tr("Her şey hazır. `python -m pbo_tuner run` ile başlayabilirsin.") if ok_all
                  else tr("Yukarıdaki HATA satırlarını düzeltip tekrar çalıştırın.")))
    return 0 if ok_all else 1


MENU = [
    (mark("Ortam kontrolü (doctor)  <- ÖNCE BUNU ÇALIŞTIR"), ["doctor"]),
    (mark("Hızlı deneme (run --quick, ~2 saat, kaba sonuç)"), ["run", "--quick"]),
    (mark("Asıl çalışma / kaldığı yerden devam (run)"), ["run"]),
    (mark("Sıfırdan başla (run --fresh)"), ["run", "--fresh"]),
    (mark("Durumu göster (status)"), ["status"]),
    (mark("Raporu göster (report)"), ["report"]),
    (mark("Nihai değerleri geçici uygula (apply)"), ["apply"]),
    (mark("Tüm CO değerlerini 0'a çek (reset)"), ["reset"]),
    (mark("Çökme sonrası otomatik devam kur"), ["install-autostart"]),
    (mark("Otomatik devamı kaldır"), ["remove-autostart"]),
    (mark("Düşük yük / boşta kararlılık testi (lowload)"), ["lowload"]),
]


def menu(base: list) -> int:
    """Komutsuz açılınca (ör. .bat'a çift tıklanınca) gösterilen basit menü."""
    while True:
        print("\nPBO AutoTuner", __version__)
        if os.name == "nt" and not is_admin():
            print(tr("!! Yönetici değilsin. doctor/run için pencereyi 'Yönetici olarak çalıştır' ile aç."))
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}) {tr(label)}")
        print("  0) " + tr("Çıkış"))
        try:
            choice = input(tr("Seçim: ")).strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice in ("0", "q", ""):
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
            print(tr("Geçersiz seçim."))
            continue
        code = main(base + MENU[int(choice) - 1][1])
        print("\n" + tr("(komut bitti, çıkış kodu {code})", code=code))


# ----------------------------------------------------------------------------- main
def _argv_value(argv: list, flag: str):
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pbo_tuner",
                                 description=tr("AMD Ryzen çekirdek başı Curve Optimizer otomatik ayarlayıcı"))
    ap.add_argument("--config", help=tr("config.toml yolu (varsayılan: ./config.toml)"))
    ap.add_argument("--lang", choices=i18n.SETTINGS,
                    help=tr("arayüz dili: auto (sistem dili), tr veya en (config.toml [ui] language ile de seçilir)"))
    sub = ap.add_subparsers(dest="cmd")   # komut verilmezse menü açılır

    r = sub.add_parser("run", help=tr("aramayı başlat / kaldığı yerden devam et"))
    r.add_argument("--quick", action="store_true", help=tr("kısa testler (kaba sonuç)"))
    r.add_argument("--fresh", action="store_true", help=tr("eski durumu yedekleyip sıfırdan başla"))
    r.add_argument("--force", action="store_true", help=tr("çökme döngüsü korumasını sıfırlayıp devam et"))
    r.add_argument("--yes", action="store_true", help=tr("uyarı onayını atla"))
    r.add_argument("--auto-resume", action="store_true", help=tr("(görev zamanlayıcı için) iş yoksa sessizce çık"))
    r.add_argument("--simulate", action="store_true", help=tr("sahte işlemciyle dene (donanıma dokunmaz)"))
    r.add_argument("--seed", type=int, default=1, help=tr("simülasyon tohumu"))
    r.set_defaults(fn=cmd_run)

    for name, fn, h in (("doctor", cmd_doctor, tr("ortam/araç kontrolü")), ("status", cmd_status, tr("durumu göster")),
                        ("report", cmd_report, tr("raporu yeniden üret")),
                        ("reset", cmd_reset, tr("tüm CO'ları 0'a çek (geçici)"))):
        sp = sub.add_parser(name, help=h)
        sp.set_defaults(fn=fn)
    lw = sub.add_parser("lowload", help=tr("nihai CO değerleriyle düşük yük + boşta bekleme testi"))
    lw.add_argument("--seconds", type=int, help=tr("çekirdek başına süre (varsayılan config: 180)"))
    lw.add_argument("--idle-minutes", type=int, help=tr("boşta bekleme süresi, dk (varsayılan config: 30, 0 = atla)"))
    lw.add_argument("--yes", action="store_true")
    lw.set_defaults(fn=cmd_lowload)
    ap_apply = sub.add_parser("apply", help=tr("nihai değerleri geçici uygula (BIOS'a girmeden)"))
    ap_apply.add_argument("--yes", action="store_true")
    ap_apply.set_defaults(fn=cmd_apply)
    sub.add_parser("install-autostart", help=tr("çökme sonrası otomatik devam görevi kur")).set_defaults(
        fn=lambda a: install_autostart(a.config or ("config.toml" if Path("config.toml").exists() else None)))
    sub.add_parser("remove-autostart", help=tr("otomatik devam görevini sil")).set_defaults(
        fn=lambda a: remove_autostart())
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.init(argv, _argv_value(argv, "--config") or i18n.default_config_path())   # parser kurulmadan önce
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd is None:
        base = ["--config", args.config] if args.config else []
        if args.lang:
            base += ["--lang", args.lang]
        return menu(base)
    try:
        return args.fn(args)
    except ConfigError as e:
        print(tr("Ayar hatası: {e}", e=e))
        return 2
    except ToolError as e:
        print(tr("Araç hatası: {e}", e=e))
        return 4


if __name__ == "__main__":
    sys.exit(main())
