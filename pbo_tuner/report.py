"""Sonuç raporu: tablo, BIOS değerleri, JSON/CSV."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from .i18n import tr
from .state import RunState

WARNING_PREFIXES = ("UYARI", "WARNING")     # state.notes iki dilde de kaydedilmiş olabilir



def build_report(st: RunState, cfg) -> tuple:
    n = st.n_cores
    per_ccd = n // 2 if n > 8 else n      # 12 çekirdek = 6+6, 16 = 8+8; 8 ve altı tek CCD
    final = st.final or {c: (st.searches[c].final or 0) for c in range(n)}
    rows = []
    for c in range(n):
        cs = st.searches[c]
        before, after = st.baseline_mhz.get(c), st.final_mhz.get(c)
        rows.append({
            "core": c, "ccd": c // per_ccd, "co": -final.get(c, 0),
            "search_result": -(cs.final or 0) if cs.final is not None else None,
            "stable_boundary": -cs.stable, "crashes": cs.crashes, "note": cs.note,
            "mhz_before": int(before) if before else None, "mhz_after": int(after) if after else None,
            "mhz_delta": int(after - before) if (before and after) else None,
        })

    def fmt(v, width=6):
        return f"{v:>{width}}" if v is not None else " " * (width - 1) + "-"

    lines = []
    lines.append(tr("PBO AutoTuner sonuç raporu"))
    lines.append(tr("Tarih: {date}   Aşama: {stage}   Toplam çökme: {crashes}",
                    date=time.strftime('%Y-%m-%d %H:%M'), stage=st.stage, crashes=st.total_crashes))
    lines.append("")
    lines.append(tr("Çekirdek  CCD   Nihai CO   Arama sonucu   Çökme   MHz önce   MHz sonra   Fark"))
    lines.append("-" * 78)
    for r in rows:
        co = f"{r['co']:+d}" if r["co"] else "0"
        lines.append(f"{r['core']:>7}  {r['ccd']:>3}   {co:>8}   {fmt(r['search_result'], 12)}   "
                     f"{r['crashes']:>5}   {fmt(r['mhz_before'], 8)}   {fmt(r['mhz_after'], 9)}   "
                     f"{fmt(r['mhz_delta'], 4)}")
    lines.append("")
    if st.extend:
        lines.append(tr("Uzatma yapıldı: çekirdekler {cores} tabandan (-{base} civarı) -{floor}'a kadar yeniden arandı. "
                        "Uzatmadan önceki değerler: {before}",
                        cores=st.extend["cores"], base=min(st.extend["base"][c] for c in st.extend["cores"]),
                        floor=st.extend["floor"],
                        before=", ".join(f"{c}:-{st.extend['base'][c]}" for c in st.extend["cores"])))
        lines.append("")
    if st.lowload:
        ll = st.lowload
        changed = [(c, a0, st.final.get(c, 0)) for c, a0 in sorted(ll["initial"].items()) if st.final.get(c, 0) != a0]
        lines.append(tr("Düşük yük testi (çekirdek başına ~{sec} sn, aralıklı hafif yük): ", sec=ll["seconds"])
                     + (tr("tüm çekirdekler geçti.") if not changed else
                        tr("geri çekilenler: ") + ", ".join(
                            tr("çekirdek {c}: -{a0} -> -{a1}", c=c, a0=a0, a1=a1) for c, a0, a1 in changed)))
        idle = {"passed": tr("geçti ({min} dk, yük yok)", min=ll["idle_seconds"] // 60),
                "failed": tr("KALDI (WHEA)"),
                "crash": tr("SİSTEM ÇÖKTÜ (boşta kararsızlık; CO'lar derin olabilir)"), "skipped": tr("atlandı"),
                None: tr("yapılmadı")}[ll["idle_result"]]
        lines.append(tr("Boşta bekleme testi: {result}", result=idle))
        lines.append(tr("(Boşta kararsızlık nadir ve rastgeledir; kısa bir bekleme onu kesin olarak elemez.)"))
        lines.append("")
    lines.append(tr("BIOS'a girmek için:"))
    lines.append("  Advanced > AMD Overclocking > Precision Boost Overdrive > Curve Optimizer > Per Core")
    lines.append(tr("  Her çekirdek için Sign = Negative, Magnitude = aşağıdaki değer (BIOS çekirdek numarası 0'dan başlar,"))
    lines.append(tr("  Ryzen Master 1'den başlar)."))
    for r in rows:
        lines.append(f"    Core {r['core']:>2}: " + (f"Negative {-r['co']}" if r['co'] < 0 else tr("0 (stok)")))
    lines.append("")
    vals = ",".join(str(r["co"]) for r in rows)
    lines.append(tr("BIOS'a girmeden geçici uygulamak için (yeniden başlatınca silinir):"))
    lines.append(tr("  python -m pbo_tuner apply          # veya: ryzen-smu-cli.exe --offset {vals}", vals=vals))
    lines.append("")
    warns = [n for n in st.notes if n.startswith(WARNING_PREFIXES)]
    if warns:
        lines.append(tr("UYARILAR:"))
        lines += [f"  {w}" for w in warns]
    lines.append("")
    lines.append(tr("Not: Bu değerler kısa/orta süreli testlerle bulundu. BIOS'a girdikten sonra gerçek kullanımda"))
    lines.append(tr("(oyun, boşta, uyku/uyanma) birkaç gün dene; sporadik çökme olursa ilgili çekirdeği 2-3 geri çek."))
    lines.append(tr("Etkin MHz değerleri Windows sayaçlarından yaklaşık ölçümdür."))
    return "\n".join(lines), {"cores": rows, "total_crashes": st.total_crashes, "stage": st.stage,
                              "offsets": [r["co"] for r in rows]}


def write_report(st: RunState, cfg) -> Path:
    text, data = build_report(st, cfg)
    out = Path(cfg.data_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(text, encoding="utf-8")
    (out / "results.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    with open(out / "bios_values.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["core", "sign", "magnitude"])
        for r in data["cores"]:
            w.writerow([r["core"], "Negative" if r["co"] < 0 else "-", -r["co"]])
    return out / "report.txt"
