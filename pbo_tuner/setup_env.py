"""Kurulum yardımcısı (kur.bat tarafından çağrılır): psutil, python_path.txt, config.toml, CoreCycler/PawnIO denetimi.

Yalnızca standart kütüphane kullanır (psutil henüz kurulu olmayabilir). Python'un kendisini kur.bat bulur/kurar.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import i18n
from .i18n import tr

MIN_PY = (3, 11)
PSUTIL_SPEC = "psutil>=5.9"
# PawnIO (namazso; GPL-2.0-or-later lisanslı çekirdek sürücüsü; ryzen-smu-cli donanım erişimi için kullanır).
# Sabit sürüm ve SHA-256, winget manifestindeki değerlerdir (namazso.PawnIO 2.2.0). Sessiz kurulum: -install -silent.
PAWNIO_VERSION = "2.2.0"
PAWNIO_URL = "https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe"
PAWNIO_SHA256 = "1F519A22E47187F70A1379A48CA604981C4FCF694F4E65B734AAA74A9FBA3032"
PAWNIO_WINGET_ID = "namazso.PawnIO"
REBOOT_REQUIRED = 3010            # ERROR_SUCCESS_REBOOT_REQUIRED
COREKEYS = ("tools/ryzen-smu-cli/ryzen-smu-cli.exe", "helpers/WriteConsoleToWriteFileWrapper.exe")

# CoreCycler (sp00n; CC BY-NC-SA 4.0): resmi sürüm https://github.com/sp00n/CoreCycler/releases/tag/v0.11.0.3
# Arşiv BCJ2 süzgeci kullanır: Python'un standart kütüphanesi ve py7zr bunu AÇAMAZ; Windows'un tar.exe'si
# (libarchive) ve 7-Zip açabilir. Arşivde tek üst klasör var (aşağıdaki ad) ve 447 dosya bulunur.
COREYCLER_VERSION = "0.11.0.3"
COREYCLER_URL = "https://github.com/sp00n/CoreCycler/releases/download/v0.11.0.3/CoreCycler-v0.11.0.3.7z"
COREYCLER_SHA256 = "721ED2948B51A2FC7C60289ECB7CBF62057B22D54C4BA5DC70AC5A107FCC1A63"
COREYCLER_DIRNAME = "CoreCycler-v0.11.0.3"
COREYCLER_DOWNLOAD_MB = 45
COREYCLER_EXTRACTED_MB = 370
COREYCLER_MIN_FILES = 300          # yarım açılmayı yakalamak için alt sınır (gerçek arşivde 447)
COREYCLER_STAGING = ".corecycler-extract"


def python_ok(version_info=sys.version_info) -> bool:
    return tuple(version_info[:2]) >= MIN_PY


def psutil_importable(python: str = sys.executable, run: Callable = subprocess.run) -> bool:
    r = run([python, "-c", "import psutil; print(psutil.__version__)"], capture_output=True, text=True)
    return r.returncode == 0


def ensure_psutil(python: str = sys.executable, run: Callable = subprocess.run,
                  log: Callable[[str], None] = print) -> bool:
    """psutil yoksa kurar. Sırayla: normal pip; pip yoksa ensurepip ile pip; yetki hatasında --user."""
    if psutil_importable(python, run):
        log(tr("psutil zaten kurulu."))
        return True
    log(tr("psutil kuruluyor (pip)..."))
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    attempts = [
        ("pip install", [pip + [PSUTIL_SPEC]]),
        ("ensurepip + pip install", [[python, "-m", "ensurepip", "--upgrade"], pip + [PSUTIL_SPEC]]),
        ("pip install --user", [pip + ["--user", PSUTIL_SPEC]]),
    ]
    for name, cmds in attempts:
        ok = True
        for cmd in cmds:
            if run(cmd).returncode != 0:
                ok = False
                break
        if ok and psutil_importable(python, run):
            log(tr("psutil kuruldu ({name}).", name=name))
            return True
        log(tr("  '{name}' başarısız, sıradaki yöntem deneniyor...", name=name))
    return False


def write_python_path(project: Path, python: str = sys.executable) -> Path:
    """run_as_admin.bat bu dosyadaki Python'u kullanır: psutil'in kurulduğu Python ile çalışma garanti olur."""
    p = project / "python_path.txt"
    p.write_text(python + "\n", encoding="utf-8")
    return p


def find_corecycler(project: Path) -> Optional[Path]:
    """Proje klasörünün içinde veya yanında CoreCycler* klasörü arar (araçları eksiksiz olan en yeni ad)."""
    cands = []
    for base in (project, project.parent):
        try:
            cands += [d for d in base.iterdir() if d.is_dir() and d.name.lower().startswith("corecycler")]
        except OSError:
            pass
    for d in sorted(cands, key=lambda d: d.name, reverse=True):
        if all((d / rel).exists() for rel in COREKEYS):
            return d
    return None


def _toml_string(path: str) -> str:
    if "'" not in path:
        return f"'{path}'"                                   # TOML düz dizgisi: ters eğik çizgi kaçışsız
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ensure_config(project: Path, corecycler: Optional[Path], log: Callable[[str], None] = print) -> str:
    """config.toml yoksa config.example.toml'dan üretir (CoreCycler yolu bulunduysa yazar). Var olanı ASLA ezmez."""
    cfg, example = project / "config.toml", project / "config.example.toml"
    if cfg.exists():
        log(tr("config.toml zaten var, dokunulmadı."))
        return "exists"
    if not example.exists():
        log(tr("UYARI: config.example.toml bulunamadı; config.toml oluşturulamadı."))
        return "missing-example"
    text = example.read_text(encoding="utf-8")
    if corecycler:
        text = re.sub(r"(?m)^corecycler_dir\s*=.*$", lambda m: f"corecycler_dir = {_toml_string(str(corecycler))}", text, count=1)
        log(tr("config.toml oluşturuldu, CoreCycler yolu: {path}", path=corecycler))
        status = "created"
    else:
        log(tr("config.toml oluşturuldu ama CoreCycler klasörü bulunamadı: dosyadaki corecycler_dir satırını elle düzenleyin."))
        status = "created-no-corecycler"
    cfg.write_text(text, encoding="utf-8")
    return status


def pawnio_version() -> Optional[str]:
    """Kurulu PawnIO sürümü (Uninstall kaydındaki DisplayVersion). Yoksa veya Windows dışındaysa None."""
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
                             0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        try:
            return str(winreg.QueryValueEx(key, "DisplayVersion")[0])
        finally:
            winreg.CloseKey(key)
    except OSError:
        return None


def pawnio_detected() -> Optional[bool]:
    """PawnIO kurulu görünüyor mu? Kesin değildir (doctor gerçek erişimi sınar). Windows dışında None."""
    if os.name != "nt":
        return None
    if pawnio_version() is not None:
        return True
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\PawnIO"))
        return True
    except OSError:
        pass
    pf = os.environ.get("ProgramFiles")
    return bool(pf and (Path(pf) / "PawnIO").exists())


def is_admin() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def download_verified(url: str, dest: Path, sha256: str, urlopen: Optional[Callable] = None,
                      log: Callable[[str], None] = print) -> bool:
    """Sabit adresten indirir ve SHA-256'yı doğrular; uyuşmazsa dosyayı siler ve False döner."""
    urlopen = urlopen or urllib.request.urlopen
    try:
        with urlopen(url, timeout=120) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as e:  # noqa: BLE001
        log(tr("  indirme başarısız: {e}", e=e))
        dest.unlink(missing_ok=True)
        return False
    got = sha256_of(dest)
    if got != sha256:
        log(tr("  UYARI: SHA-256 uyuşmuyor (beklenen {expected}, gelen {got}). Dosya silindi, kurulmayacak.",
               expected=sha256, got=got))
        dest.unlink(missing_ok=True)
        return False
    log(tr("  SHA-256 doğrulandı."))
    return True


def download_pawnio(dest: Path, urlopen: Callable = urllib.request.urlopen,
                    log: Callable[[str], None] = print) -> bool:
    log(tr("PawnIO {version} indiriliyor: {url}", version=PAWNIO_VERSION, url=PAWNIO_URL))
    return download_verified(PAWNIO_URL, dest, PAWNIO_SHA256, urlopen, log)


def run_pawnio_installer(path: Path, run: Callable, admin: bool) -> int:
    """Sessiz kurulum. Yönetici değilsek UAC isteyecek şekilde yükseltir ve bitmesini bekler."""
    if admin:
        return run([str(path), "-install", "-silent"]).returncode
    quoted = str(path).replace("'", "''")
    ps = (f"$p = Start-Process -FilePath '{quoted}' -ArgumentList '-install','-silent' -Verb RunAs -Wait -PassThru; "
          f"exit $p.ExitCode")
    return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]).returncode


def ensure_pawnio(run: Callable = subprocess.run, log: Callable[[str], None] = print,
                  ask: Optional[Callable[[str], bool]] = None, urlopen: Callable = urllib.request.urlopen,
                  admin: Optional[bool] = None, which: Callable = shutil.which,
                  tmpdir: Optional[Path] = None) -> str:
    """PawnIO yoksa kurar. Dönüş: 'present' | 'installed' | 'reboot' | 'declined' | 'failed' | 'unsupported'.
    Sırayla: winget (namazso.PawnIO); olmazsa GitHub'dan sabit sürüm + SHA-256 doğrulaması. Kurmadan önce onay sorar."""
    if os.name != "nt":
        log(tr("PawnIO yalnızca Windows'ta gerekir; atlandı."))
        return "unsupported"
    ver = pawnio_version()
    if ver or pawnio_detected():
        log(tr("PawnIO zaten kurulu{ver}.", ver=tr(" (sürüm {v})", v=ver) if ver else ""))
        return "present"
    log(tr("PawnIO kurulu görünmüyor. Bu, ryzen-smu-cli'nin işlemciye erişmek için kullandığı imzalı bir çekirdek sürücüsüdür"))
    log(tr("(namazso, GPL lisanslı, imzalı sürücü: https://pawnio.eu). Kurulum için UAC (yönetici) onayı istenecek."))
    if ask is not None and not ask(tr("PawnIO sürücüsü kurulsun mu?")):
        log(tr("PawnIO kurulumu atlandı. Sonra elle kurabilirsiniz: https://pawnio.eu"))
        return "declined"
    code = None
    if which("winget"):
        log(tr("winget ile kuruluyor..."))
        code = run(["winget", "install", "-e", "--id", PAWNIO_WINGET_ID, "--silent",
                    "--accept-package-agreements", "--accept-source-agreements"]).returncode
        if pawnio_detected():
            log(tr("PawnIO kuruldu (winget)."))
            return "reboot" if code == REBOOT_REQUIRED else "installed"
        log(tr("  winget ile kurulum doğrulanamadı (çıkış kodu {code}); doğrudan indirme denenecek.", code=code))
    tmp = Path(tmpdir) if tmpdir else Path(tempfile.gettempdir())
    exe = tmp / "PawnIO_setup.exe"
    if not download_pawnio(exe, urlopen, log):
        return "failed"
    try:
        code = run_pawnio_installer(exe, run, is_admin() if admin is None else admin)
    finally:
        exe.unlink(missing_ok=True)
    if code == REBOOT_REQUIRED:
        log(tr("PawnIO kuruldu; Windows yeniden başlatma isteyebilir. Sorun görürseniz bilgisayarı yeniden başlatın."))
        return "reboot"
    if code == 0 and pawnio_detected():
        log(tr("PawnIO kuruldu."))
        return "installed"
    log(tr("PawnIO kurulumu doğrulanamadı (çıkış kodu {code}). UAC penceresini reddetmiş olabilirsiniz; "
           "elle kurun: https://pawnio.eu", code=code))
    return "failed"


# ----------------------------------------------------------------------------- CoreCycler
def corecycler_complete(folder: Path) -> bool:
    """Açılmış CoreCycler klasörü eksiksiz görünüyor mu (gereken programlar var ve dosya sayısı makul)?"""
    if not all((folder / rel).exists() for rel in COREKEYS):
        return False
    return sum(len(files) for _, _, files in os.walk(folder)) >= COREYCLER_MIN_FILES


def windows_tar(env=os.environ) -> Optional[str]:
    """Windows'un kendi tar.exe'si (libarchive; .7z açabilir). PATH'teki tar Git'in GNU tar'ı olabilir ve .7z
    açamaz, bu yüzden yalnızca System32'dekine güvenilir."""
    root = env.get("SystemRoot") or env.get("windir")
    p = Path(root) / "System32" / "tar.exe" if root else None
    return str(p) if p and p.exists() else None


def find_7zip(which: Callable = shutil.which, env=os.environ) -> Optional[str]:
    cands = [which("7z"), which("7za")]
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        pf = env.get(var)
        if pf:
            cands.append(str(Path(pf) / "7-Zip" / "7z.exe"))
    return next((c for c in cands if c and Path(c).exists()), None)


def _clear_dir(folder: Path) -> None:
    for child in folder.iterdir():
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)


def extract_7z(archive: Path, dest: Path, run: Callable = subprocess.run,
               log: Callable[[str], None] = print) -> bool:
    """Arşivi `dest` (boş, önceden oluşturulmuş klasör) içine açar ve sonucu doğrular. Sırayla: Windows tar.exe,
    kuruluysa 7-Zip. Yarım kalan açmayı bir sonraki denemeden önce temizler."""
    attempts = []
    tar = windows_tar()
    if tar:
        attempts.append(("tar.exe", [tar, "-xf", str(archive), "-C", str(dest)]))
    sevenzip = find_7zip()
    if sevenzip:
        attempts.append(("7-Zip", [sevenzip, "x", "-y", f"-o{dest}", str(archive)]))
    if not attempts:
        log(tr("  Arşivi açacak program bulunamadı (Windows tar.exe veya 7-Zip). 7-Zip kurup tekrar deneyin: https://www.7-zip.org"))
        return False
    for name, cmd in attempts:
        log(tr("  {name} ile açılıyor...", name=name))
        try:
            r = run(cmd, capture_output=True, text=True)
            code, err = r.returncode, (r.stderr or "").strip().splitlines()
        except OSError as e:
            code, err = -1, [str(e)]
        if code == 0 and corecycler_complete(dest / COREYCLER_DIRNAME):
            return True
        log(tr("  {name} ile açma başarısız (çıkış kodu {code}){detail}", name=name, code=code,
               detail=(": " + err[0]) if err else ""))
        _clear_dir(dest)
    return False


def ensure_corecycler(project: Path, run: Callable = subprocess.run, log: Callable[[str], None] = print,
                      ask: Optional[Callable[[str], bool]] = None, urlopen: Optional[Callable] = None,
                      tmpdir: Optional[Path] = None) -> Optional[Path]:
    """CoreCycler yoksa resmi GitHub sürümünden indirir (SHA-256 doğrulaması) ve proje klasörüne açar.
    Dönüş: klasör yolu; indirilmediyse/başarısızsa None. Var olan hiçbir klasöre dokunmaz."""
    found = find_corecycler(project)
    if found:
        return found
    target = project / COREYCLER_DIRNAME
    if target.exists():
        log(tr("{path} klasörü var ama eksik görünüyor; dokunulmadı. Silip kur.bat'ı yeniden çalıştırın veya CoreCycler'ı elle kurun.",
               path=target))
        return None
    log(tr("CoreCycler bulunamadı. Resmi GitHub sürümünden indirilebilir ({url}; ~{dl} MB, açılınca ~{ex} MB)."
           , url=COREYCLER_URL, dl=COREYCLER_DOWNLOAD_MB, ex=COREYCLER_EXTRACTED_MB))
    log(tr("(sp00n; CC BY-NC-SA 4.0 lisanslı: yalnızca ticari olmayan kullanım. Bu araç onu repoya koymaz, doğrudan buradan indirir.)"))
    if ask is not None and not ask(tr("CoreCycler indirilip kurulsun mu?")):
        log(tr("CoreCycler indirmesi atlandı. Elle indirin: https://github.com/sp00n/CoreCycler/releases"))
        return None
    if shutil.disk_usage(project).free < (COREYCLER_EXTRACTED_MB + COREYCLER_DOWNLOAD_MB + 200) * 1024 * 1024:
        log(tr("Diskte yeterli boş yer yok (en az ~{mb} MB gerekir); CoreCycler indirilmedi.",
               mb=COREYCLER_EXTRACTED_MB + COREYCLER_DOWNLOAD_MB + 200))
        return None
    archive = (Path(tmpdir) if tmpdir else Path(tempfile.gettempdir())) / f"{COREYCLER_DIRNAME}.7z"
    stage = project / COREYCLER_STAGING
    try:
        log(tr("CoreCycler {version} indiriliyor (~{dl} MB)...", version=COREYCLER_VERSION, dl=COREYCLER_DOWNLOAD_MB))
        if not download_verified(COREYCLER_URL, archive, COREYCLER_SHA256, urlopen, log):
            return None
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        log(tr("Açılıyor (~{mb} MB, bir iki dakika sürebilir)...", mb=COREYCLER_EXTRACTED_MB))
        if not extract_7z(archive, stage, run, log):
            log(tr("CoreCycler açılamadı. Antivirüs dosyaları silmiş olabilir (y-cruncher / ryzen-smu-cli); "
                   "istisna ekleyip tekrar deneyin ya da CoreCycler'ı elle kurun: https://github.com/sp00n/CoreCycler/releases"))
            return None
        os.replace(stage / COREYCLER_DIRNAME, target)
        log(tr("CoreCycler kuruldu: {path}", path=target))
        return target
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)


def ask_yes_no(question: str) -> bool:
    """Etkileşimli onay. Giriş yoksa (EOF) güvenli tarafta kalıp hayır sayar."""
    try:
        ans = input(f"{question} {tr('[E/h]')} ").strip().lower()
    except EOFError:
        return False
    return ans in ("", "e", "evet", "y", "yes")


def main(project_dir: Optional[str] = None, log: Callable[[str], None] = print,
         run: Callable = subprocess.run, yes: bool = False, no_pawnio: bool = False,
         ask: Optional[Callable[[str], bool]] = None, urlopen: Optional[Callable] = None,
         no_corecycler: bool = False) -> int:
    urlopen = urlopen or urllib.request.urlopen
    project = Path(project_dir) if project_dir else Path(__file__).resolve().parent.parent
    log(f"Python {sys.version.split()[0]}  ({sys.executable})")
    if not python_ok():
        log(tr("HATA: Python {major}.{minor} veya üzeri gerekli.", major=MIN_PY[0], minor=MIN_PY[1]))
        return 1
    if not ensure_psutil(sys.executable, run, log):
        log(tr("HATA: psutil kurulamadı. Elle deneyin:  python -m pip install psutil   (internet bağlantısını kontrol edin)"))
        return 1
    write_python_path(project)
    cc = find_corecycler(project)
    if cc is None and not no_corecycler:
        cc = ensure_corecycler(project, run, log, ask=(None if yes else (ask or ask_yes_no)), urlopen=urlopen)
    ensure_config(project, cc, log)
    log("")
    pawn = "skipped"
    if no_pawnio:
        log(tr("PawnIO adımı atlandı (--no-pawnio)."))
    else:
        pawn = ensure_pawnio(run, log, ask=(None if yes else (ask or ask_yes_no)), urlopen=urlopen)
    log("")
    log(tr("Kontroller:"))
    log(f"  [{tr('TAMAM') if cc else tr('EKSİK')}] CoreCycler" + (f": {cc}" if cc else
        tr(": indirip proje klasörüne açın (CoreCycler 0.11.x): https://github.com/sp00n/CoreCycler/releases")))
    pw = pawnio_detected()
    if pw is None:
        log(tr("  [?]     PawnIO: Windows dışında denetlenemez"))
    else:
        log(f"  [{tr('TAMAM') if pw else tr('EKSİK?')}] " + tr("PawnIO sürücüsü") + ("" if pw else
            tr(": algılanamadı (bu kontrol kesin değil). https://pawnio.eu adresinden kurun.")))
    if pawn == "reboot":
        log(tr("  NOT: PawnIO kurulumundan sonra yeniden başlatma gerekebilir; doctor hata verirse bilgisayarı yeniden başlatın."))
    log("")
    log(tr("Sonraki adım: run_as_admin.bat dosyasına sağ tık > Yönetici olarak çalıştır > menüden 1 (doctor)."))
    return 0


if __name__ == "__main__":
    i18n.init(sys.argv[1:], str(Path(__file__).resolve().parent.parent / "config.toml"))   # parser kurulmadan önce
    ap = argparse.ArgumentParser(prog="pbo_tuner.setup_env", description=tr("PBO AutoTuner kurulum yardımcısı"))
    ap.add_argument("--yes", action="store_true", help=tr("sormadan PawnIO'yu da kur ve CoreCycler'ı da indir"))
    ap.add_argument("--no-pawnio", action="store_true", help=tr("PawnIO adımını atla"))
    ap.add_argument("--no-corecycler", action="store_true", help=tr("CoreCycler'ı indirme adımını atla"))
    ap.add_argument("--lang", choices=i18n.SETTINGS, help=tr("arayüz dili: auto (sistem dili), tr veya en"))
    a = ap.parse_args()
    sys.exit(main(yes=a.yes, no_pawnio=a.no_pawnio, no_corecycler=a.no_corecycler))
