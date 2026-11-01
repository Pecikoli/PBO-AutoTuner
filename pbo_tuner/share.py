"""Sonuç paylaşma: anonimleştirilmiş bir rapor hazırlar ve (kullanıcı onaylarsa) GitHub'da önceden doldurulmuş bir
"issue" sayfası açar.

İlkeler
-------
* Sunucu YOK, arka planda gönderim YOK. Kullanıcı raporun tamamını ekranda görür; GitHub sayfasında "Submit new
  issue"ya kendisi basar. Gönderilen rapor GitHub'da herkese açıktır.
* Kimlik toplanmaz: kullanıcı adı, bilgisayar adı ve klasör yolları rapordan çıkarılır (`redact`).
* Rapor her zaman İngilizce yazılır (bakımcı için tek biçim); ekrandaki açıklamalar arayüz dilindedir.
* CO değerleri o tek işlemciye özeldir; rapor "başkasına kopyalama" uyarısını taşır.
"""

from __future__ import annotations

import os
import platform
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from . import __version__
from .generations import GENERATIONS, classify, parse_identifier, read_cpu_identity
from .report import build_report, is_warning

REPO = "Pecikoli/PBO-AutoTuner"
NEW_ISSUE_URL = f"https://github.com/{REPO}/issues/new"
MAX_URL_LEN = 7000                  # GitHub çok uzun adresleri reddeder (~8 KB); güvenli pay bırakılır
DOCTOR_FILE = "doctor_last.txt"
SHARE_FILE = "share_report.txt"
WARNING_LIMIT = 8


# ----------------------------------------------------------------------------- doctor çıktısı
def save_doctor(cfg, lines: list) -> None:
    """`doctor` çıktısını (yalnızca [TAMAM]/[HATA] satırları) `data/doctor_last.txt`'ye yazar. Asla hata vermez."""
    try:
        cfg.data_path.mkdir(parents=True, exist_ok=True)
        text = f"# doctor, {time.strftime('%Y-%m-%d')}\n" + "\n".join(lines) + "\n"
        (cfg.data_path / DOCTOR_FILE).write_text(text, encoding="utf-8")
    except OSError:
        pass


def read_doctor(cfg) -> Optional[str]:
    try:
        return (cfg.data_path / DOCTOR_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


# ----------------------------------------------------------------------------- kişisel bilgi temizleme
def local_names(cfg=None) -> dict:
    """Rapordan çıkarılacak yerel adlar. Ortamdan okunur; testler kendi değerlerini verir."""
    try:
        import getpass
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = os.environ.get("USERNAME") or os.environ.get("USER")
    project = None
    if cfg is not None and getattr(cfg, "data_dir", None):
        project = str(Path(cfg.data_dir).resolve().parent)
    return {"home": str(Path.home()), "project": project, "user": user, "host": platform.node() or None}


def redact(text: str, home: Optional[str] = None, project: Optional[str] = None, user: Optional[str] = None,
           host: Optional[str] = None) -> str:
    """Yol, kullanıcı adı ve bilgisayar adını yer tutucularla değiştirir (büyük/küçük harf duyarsız)."""
    for value, placeholder in sorted(((project, "<project>"), (home, "<home>")), key=lambda p: -len(p[0] or "")):
        if value:
            text = re.sub(re.escape(value), placeholder, text, flags=re.I)
            text = re.sub(re.escape(value.replace("\\", "/")), placeholder, text, flags=re.I)
    text = re.sub(r"(?i)([A-Z]:[\\/]+Users[\\/]+)[^\\/\s'\"<>|]+", r"\1<user>", text)
    for value, placeholder in ((host, "<host>"), (user, "<user>")):         # önce bilgisayar adı: "ZEYNEP-PC" kullanıcı adını içerebilir
        if value and len(value) >= 3:
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", placeholder, text, flags=re.I)
    return text


# ----------------------------------------------------------------------------- bilgi toplama
def collect_info(cfg, st=None, identity_reader: Optional[Callable] = None) -> dict:
    """Ortam bilgisi. Okunamayan her şey sessizce None kalır (ör. Windows dışında CPU kimliği)."""
    info = {"tool_version": __version__, "windows": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "cpu_name": None, "cpu_identifier": None, "generation": None,
            "preset": None, "cores": getattr(st, "n_cores", None), "smt": None, "pawnio": None}
    try:
        ident, name = (identity_reader or read_cpu_identity)()
        info["cpu_name"], info["cpu_identifier"] = (name or None), (ident or None)
        fm = parse_identifier(ident)
        info["generation"] = classify(*fm) if fm else None
    except Exception:  # noqa: BLE001
        pass
    if info["generation"] in GENERATIONS:
        p = GENERATIONS[info["generation"]]
        info["preset"] = f"{p['mode']} / floor {p['floor']} / start_co {p['start_co']}"
    try:
        from .hw import detect_topology
        n, smt = detect_topology(cfg.cores, cfg.smt)
        info["cores"], info["smt"] = info["cores"] or n, smt
    except Exception:  # noqa: BLE001
        pass
    try:
        from .setup_env import pawnio_version
        info["pawnio"] = pawnio_version()
    except Exception:  # noqa: BLE001
        pass
    return info


# ----------------------------------------------------------------------------- rapor
def _v(value) -> str:
    return "unknown" if value is None else str(value)


def format_report(info: dict, st=None, rows: Optional[list] = None, doctor: Optional[str] = None,
                  include_values: bool = True) -> str:
    out = ["### PBO AutoTuner results report", "",
           f"- Tool version: {info['tool_version']}",
           f"- OS: {_v(info.get('windows'))} ({_v(info.get('machine'))})",
           f"- Python: {_v(info.get('python'))}",
           f"- CPU: {_v(info.get('cpu_name'))}",
           f"- CPU identifier: {_v(info.get('cpu_identifier'))} (detected generation: {_v(info.get('generation'))})",
           f"- Cores: {_v(info.get('cores'))}, SMT: {_v(info.get('smt'))}",
           f"- PawnIO: {_v(info.get('pawnio'))}",
           f"- Preset: {_v(info.get('preset'))}", ""]
    if st is None:
        out += ["### Run", "", "- No saved run yet (environment information only).", ""]
    else:
        out += ["### Run", "",
                f"- Stage: {st.stage}" + ("" if st.stage == "done" else " (unfinished: values are provisional)"),
                f"- Total crashes: {st.total_crashes}, halted: {st.halted}"]
        if st.lowload:
            idle = st.lowload.get("idle_result") or "not done"
            changed = sum(1 for c, a in st.lowload["initial"].items() if st.final.get(int(c), 0) != a)
            out.append(f"- Low-load test: idle result {idle}, cores backed off: {changed}")
        warns = [n for n in st.notes if is_warning(n)]
        out.append(f"- Warnings: {len(warns)}")
        out += [f"  - {w}" for w in warns[:WARNING_LIMIT]]
        out.append("")
        if include_values and rows:
            out += ["### Per-core results", "",
                    "| core | final CO | search result | crashes | boost diff (MHz) |", "|---|---|---|---|---|"]
            for r in rows:
                sr = "-" if r["search_result"] is None else r["search_result"]
                md = "-" if r["mhz_delta"] is None else r["mhz_delta"]
                out.append(f"| {r['core']} | {r['co']} | {sr} | {r['crashes']} | {md} |")
            out += ["", "_These values belong to this one chip (silicon lottery). Do not copy them to other processors._", ""]
        elif rows:
            out += ["### Per-core results", "", "_Omitted by the user._", ""]
    if doctor:
        out += ["### doctor output", "", "```", doctor, "```", ""]
    return "\n".join(out).rstrip() + "\n"


def make_title(info: dict) -> str:
    return f"[results] {info.get('cpu_name') or 'unknown CPU'} ({info.get('generation') or 'unknown'})"[:120]


def issue_url(title: str, body: str, labels: str = "results") -> str:
    return f"{NEW_ISSUE_URL}?title={quote(title, safe='')}&labels={quote(labels, safe='')}&body={quote(body, safe='')}"


def prepare(cfg, st=None, include_values: bool = True, identity_reader: Optional[Callable] = None,
            names: Optional[dict] = None) -> dict:
    """Her şeyi hazırlar: tam rapor (temizlenmiş), kısaltılmış rapor ve adres. Hiçbir şey göndermez."""
    info = collect_info(cfg, st, identity_reader)
    rows = None
    if st is not None:
        try:
            rows = build_report(st, cfg)[1]["cores"]
        except Exception:  # noqa: BLE001
            rows = None
    doctor = read_doctor(cfg)
    names = names if names is not None else local_names(cfg)
    clean = lambda t: redact(t, **names)          # noqa: E731
    full = clean(format_report(info, st, rows, doctor, include_values))
    title = make_title(info)
    url, trimmed = issue_url(title, full), False
    if len(url) > MAX_URL_LEN:
        short = clean(format_report(info, st, rows, None, include_values))
        short += ("\n_The doctor output was too long for the link: drag `share_report.txt` (saved in the data folder) "
                  "into this comment box._\n") if doctor else ""
        url, trimmed = issue_url(title, short), True
        if len(url) > MAX_URL_LEN:                 # tablo bile sığmadıysa yalnızca ortam bilgisi
            url = issue_url(title, clean(format_report(info, None, None, None, include_values))
                            + "\n_Report too long for the link: drag `share_report.txt` into this comment box._\n")
    return {"report": full, "url": url, "trimmed": trimmed, "title": title, "info": info}
