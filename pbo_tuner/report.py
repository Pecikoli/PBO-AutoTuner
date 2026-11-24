"""Sonuç raporu: tablo, BIOS değerleri, JSON/CSV."""

from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

from .i18n import tr
from .state import RunState, STAGE_DONE

WARNING_PREFIXES = ("UYARI", "WARNING")     # state.notes iki dilde de kaydedilmiş olabilir
_NOTE_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")     # RunState.note() her nota tarih ekler


def is_warning(note: str) -> bool:
    """Not bir uyarı mı? (başındaki tarih damgası yok sayılır; Türkçe ve İngilizce kayıtlar tanınır)"""
    return _NOTE_STAMP.sub("", note, count=1).startswith(WARNING_PREFIXES)


VERIFIED, PARTIAL, NOT_VERIFIED = "verified", "partial", "not_verified"
IDLE_MIN_MINUTES = 60          # bundan kısa boşta testi "doğrulandı" demeye yetmez (boşta kararsızlık nadirdir)


def verdict(st: RunState) -> tuple:
    """(outcome, [neden metinleri]). DOĞRULANDI yalnızca TÜM aşamalar bitmiş, tüm çekirdek, düşük yük ve yeterince
    uzun boşta testi geçmişse verilir. Hata varsa DOĞRULANMADI (hangi aşama olduğu yazılır); testler hiç
    yapılmadıysa (hata değil, eksik) KISMEN DOĞRULANDI."""
    bad, part = [], []
    if st.stage != STAGE_DONE:
        bad.append(tr("çalışma bitmedi (aşama: {stage})", stage=st.stage))
    if st.allcore_ok is False:
        bad.append(tr("tüm çekirdek testi (aşama: allcore) geri çekilmelere rağmen geçmedi"))
    ll = st.lowload
    if ll is None:
        part.append(tr("düşük yük ve boşta testleri yapılmadı (`lowload` komutu)"))
    else:
        res, rounds = ll.get("idle_result"), ll.get("idle_rounds", 0)
        if res in ("crash", "failed"):
            what = tr("sistem çöktü") if res == "crash" else tr("WHEA hatası verdi")
            bad.append(tr("boşta bekleme testi (aşama: idle) {what}; giderilemedi ({n} geri çekme turu denendi)",
                          what=what, n=rounds))
        elif res in ("skipped", None):
            part.append(tr("boşta bekleme testi yapılmadı"))
        elif ll["idle_seconds"] < IDLE_MIN_MINUTES * 60:
            part.append(tr("boşta bekleme testi kısa ({min} dk < {need} dk); boşta kararsızlığı elemek için yetmez",
                           min=ll["idle_seconds"] // 60, need=IDLE_MIN_MINUTES))
    if bad:
        return NOT_VERIFIED, bad + part
    return (PARTIAL, part) if part else (VERIFIED, [])


def verdict_text(v: str) -> str:
    return {VERIFIED: tr("DOĞRULANDI"), PARTIAL: tr("KISMEN DOĞRULANDI"), NOT_VERIFIED: tr("DOĞRULANMADI")}[v]


def lowload_changes(st: RunState) -> list:
    """Düşük yük / boşta testinin geri çektiği çekirdekler: [(çekirdek, önce, sonra)].
    MHz'e göre kırpma bu testten ÖNCE çalışır ve bir geri çekme değildir. Eski sürümle bitmiş bir çalışmada `lowload`
    önce kırptığı için `initial` kırpmadan önceki değeri taşıyabilir (gerçek rapor: 'çekirdek 4: -48 -> -28' düşük yük
    geri çekmesi diye yazıldı, oysa test o çekirdekte hiç kalmamıştı); o durumda başlangıç, kırpmanın seçtiği değerdir."""
    ll = st.lowload
    if not ll:
        return []
    trim = st.trim or {"from": {}, "chosen": {}}
    out = []
    for c, a0 in sorted(ll["initial"].items()):
        if c in trim["chosen"] and trim["from"].get(c) == a0:
            a0 = trim["chosen"][c]
        a1 = st.final.get(c, 0)
        if a1 != a0:
            out.append((c, a0, a1))
    return out


def build_report(st: RunState, cfg) -> tuple:
    n = st.n_cores
    per_ccd = n // 2 if n > 8 else n      # 12 çekirdek = 6+6, 16 = 8+8; 8 ve altı tek CCD
    final = st.final or {c: (st.searches[c].final or 0) for c in range(n)}
    capped = set(st.capped_cores())
    outcome, reasons = verdict(st)
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
            "limit": "unknown" if c in capped else "found",
        })

    def fmt(v, width=6):
        return f"{v:>{width}}" if v is not None else " " * (width - 1) + "-"

    lines = []
    lines.append(tr("PBO AutoTuner sonuç raporu"))
    lines.append(tr("SONUÇ: {verdict}", verdict=verdict_text(outcome)))
    lines += [f"  - {x}" for x in reasons]
    lines.append(tr("Tarih: {date}   Aşama: {stage}   Toplam çökme: {crashes}",
                    date=time.strftime('%Y-%m-%d %H:%M'), stage=st.stage, crashes=st.total_crashes))
    lines.append("")
    lines.append(tr("Çekirdek  CCD   Nihai CO   Arama sonucu   Çökme   MHz önce   MHz sonra   Fark   Sınır"))
    lines.append("-" * 88)
    for r in rows:
        co = f"{r['co']:+d}" if r["co"] else "0"
        lines.append(f"{r['core']:>7}  {r['ccd']:>3}   {co:>8}   {fmt(r['search_result'], 12)}   "
                     f"{r['crashes']:>5}   {fmt(r['mhz_before'], 8)}   {fmt(r['mhz_after'], 9)}   "
                     f"{fmt(r['mhz_delta'], 4)}   "
                     + (tr("bilinmiyor") if r["limit"] == "unknown" else tr("bulundu")))
    lines.append("")
    if capped:
        lines.append(tr("Sınır 'bilinmiyor' (çekirdek {cores}): çekirdek aramada araç sınırına (-{floor}) kadar hiç hata "
                        "vermeden indi; gerçek sınırı bu araçla ölçülemez. 'Nihai CO' bu çekirdeklerde bulunan sınır "
                        "değil, seçilen güvenli değerdir.", cores=sorted(capped),
                        floor=st.search_floor(min(capped))))
        lines.append("")
    if st.trim and st.trim["from"]:
        t = st.trim
        lines.append(tr("MHz'e göre kırpma (tek çekirdek boost ölçümü; çok çekirdekli yükte verim farkını ölçmez):"))
        for c in t["cores"]:
            lv = " ".join(f"-{a}:{int(m)}" if m else f"-{a}:?" for a, m in sorted(t["measured"].get(c, {}).items(), reverse=True))
            if c in t["chosen"]:
                a0, a1 = t["from"][c], t["chosen"][c]
                lines.append("  " + tr("çekirdek {c}: ", c=c) + (tr("-{a0} bırakıldı", a0=a0) if a0 == a1
                                                               else tr("-{a0} -> -{a1}", a0=a0, a1=a1)) + f"   [{lv}]")
            else:
                lines.append("  " + tr("çekirdek {c}: ölçülemedi, -{a0} bırakıldı", c=c, a0=t["from"][c]) + f"   [{lv}]")
        lines.append("")
    if st.extend:
        lines.append(tr("Uzatma yapıldı: çekirdekler {cores} tabandan (-{base} civarı) -{floor}'a kadar yeniden arandı. "
                        "Uzatmadan önceki değerler: {before}",
                        cores=st.extend["cores"], base=min(st.extend["base"][c] for c in st.extend["cores"]),
                        floor=st.extend["floor"],
                        before=", ".join(f"{c}:-{st.extend['base'][c]}" for c in st.extend["cores"])))
        lines.append("")
    if st.allcore_rounds or st.allcore_targeted:
        parts = []
        if st.allcore_rounds:
            parts.append(tr("{n} genel tur (hepsi geri çekildi)", n=st.allcore_rounds))
        if st.allcore_targeted:
            parts.append(tr("{n} hedefli tur (WHEA APIC ID'si çekirdeği gösterdi, yalnızca o geri çekildi)",
                            n=st.allcore_targeted))
        lines.append(tr("Tüm çekirdek testi geri çekmeleri: ") + "; ".join(parts) + ".")
        lines.append("")
    if st.lowload:
        ll = st.lowload
        changed = lowload_changes(st)
        lines.append(tr("Düşük yük testi (çekirdek başına ~{sec} sn, aralıklı hafif yük): ", sec=ll["seconds"])
                     + (tr("tüm çekirdekler geçti.") if not changed else
                        tr("geri çekilenler: ") + ", ".join(
                            tr("çekirdek {c}: -{a0} -> -{a1}", c=c, a0=a0, a1=a1) for c, a0, a1 in changed)))
        idle = {"passed": tr("geçti ({min} dk, yük yok)", min=ll["idle_seconds"] // 60),
                "failed": tr("KALDI (WHEA)"),
                "crash": tr("SİSTEM ÇÖKTÜ (boşta kararsızlık; CO'lar derin olabilir)"), "skipped": tr("atlandı"),
                None: tr("yapılmadı")}[ll["idle_result"]]
        lines.append(tr("Boşta bekleme testi: {result}", result=idle))
        for h in ll.get("idle_history", []):
            src = {"whea": tr("WHEA APIC {apic} -> çekirdek {cores}", apic=h["apic"], cores=h["cores"]),
                   "unknown": tr("çekirdek belirlenemedi (WHEA kaydı yok: donma-reset olabilir)"),
                   "unavailable": tr("çekirdek belirlenemedi (WHEA okunamadı)")}[h["source"]]
            moves = (", ".join(f"{c}: -{a0} -> -{a1}" for c, a0, a1 in h["backed_off"])
                     if h["backed_off"] else tr("yok"))
            lines.append("  " + tr("{n}. boşta testi: {result}; {src}; geri çekilen: {moves}",
                                   n=h["round"], result=tr("çöktü") if h["result"] == "crash" else tr("kaldı"),
                                   src=src, moves=moves))
        lines.append(tr("(Boşta kararsızlık nadir ve rastgeledir; kısa bir bekleme onu kesin olarak elemez.)"))
        lines.append("")
    if outcome == NOT_VERIFIED:
        lines.append(tr("!! DOĞRULANMADI: aşağıdaki değerleri BIOS'a GİRMEYİN. Önce yukarıdaki nedeni giderin "
                        "(ör. `lowload` komutuyla yeniden deneyin). Değerler yalnızca bilgi içindir."))
    elif outcome == PARTIAL:
        lines.append(tr("Dikkat: sonuç KISMEN doğrulandı (yukarıdaki eksikler); BIOS'a girdikten sonra gerçek kullanımda dene."))
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
    warns = [n for n in st.notes if is_warning(n)]
    if warns:
        lines.append(tr("UYARILAR:"))
        lines += [f"  {w}" for w in warns]
    lines.append("")
    lines.append(tr("Not: Bu değerler kısa/orta süreli testlerle bulundu. BIOS'a girdikten sonra gerçek kullanımda"))
    lines.append(tr("(oyun, boşta, uyku/uyanma) birkaç gün dene; sporadik çökme olursa ilgili çekirdeği 2-3 geri çek."))
    lines.append(tr("Etkin MHz değerleri Windows sayaçlarından yaklaşık ölçümdür."))
    return "\n".join(lines), {"cores": rows, "total_crashes": st.total_crashes, "stage": st.stage,
                              "offsets": [r["co"] for r in rows], "verdict": outcome, "verdict_reasons": reasons}


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
