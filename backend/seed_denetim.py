#!/usr/bin/env python3
"""Denetim raporu seed'i — JSON verisini `audit_*` tablolarına yükler (IDEMPOTENT).

Kaynak JSON'lar `backend/seed_data/` altındadır ve v4 raporundan (2026-07-25)
yapısal olarak çıkarılmıştır. Yeni bir denetim yapıldığında aynı biçimde bir
JSON eklenip bu script tekrar çalıştırılır.

Idempotent: aynı `code` ile var olan bulgu SİLİNMEZ — yalnız rapor metni alanları
(başlık/kanıt/çözüm/kriter) tazelenir. **Kullanıcının girdiği alanlara dokunulmaz**
(`status`, `auto_enabled`, `closure_note`, `verification_output`, `prompt_override`)
— aksi halde seed'i yeniden koşmak "düzeldi" bilgisini siler.

Kullanım:
    python seed_denetim.py                    # canlı DB
    python seed_denetim.py --dry-run          # yalnız ne yapacağını yazar
    DATABASE_URL=...sprenses_test python seed_denetim.py   # test DB
"""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal  # noqa: E402
from app.models.audit_tracker import (  # noqa: E402
    AuditDimension,
    AuditFinding,
    AuditReport,
)

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data")

# Seed'in TAZELEDİĞİ alanlar (rapor metni). Diğer her şey kullanıcıya aittir.
_REFRESHABLE = (
    "title", "dimension_no", "risk", "effort", "category",
    "evidence", "solution", "closure_criteria", "source_section",
    "score_impact", "automatable",
)


def _load(name: str):
    with open(os.path.join(SEED_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Denetim raporu seed'i")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="report.json")
    args = parser.parse_args()

    meta = _load(args.report)
    dimensions = _load(meta["dimensions_file"])
    findings = _load(meta["findings_file"])

    db = SessionLocal()
    try:
        report = db.query(AuditReport).filter(AuditReport.key == meta["key"]).first()
        if not report:
            report = AuditReport(
                key=meta["key"],
                title=meta["title"],
                report_date=date.fromisoformat(meta["report_date"]),
                doc_path=meta.get("doc_path"),
                baseline_score=meta.get("baseline_score"),
                target_score=meta.get("target_score"),
                notes=meta.get("notes"),
                is_active=True,
            )
            db.add(report)
            db.flush()
            print(f"+ Rapor oluşturuldu: {report.key}")
        else:
            print(f"= Rapor mevcut: {report.key} (id={report.id})")

        # ── Boyutlar ──
        added = updated = 0
        for d in dimensions:
            row = (
                db.query(AuditDimension)
                .filter(
                    AuditDimension.report_id == report.id,
                    AuditDimension.no == d["no"],
                )
                .first()
            )
            if row:
                row.name = d["name"]
                row.score_prev = d.get("score_v3")
                row.score_baseline = d["score_v4"]
                row.score_target = d["score_target"]
                row.layer = d["layer"]
                row.reason = d.get("reason")
                updated += 1
            else:
                db.add(AuditDimension(
                    report_id=report.id,
                    no=d["no"],
                    name=d["name"],
                    score_prev=d.get("score_v3"),
                    score_baseline=d["score_v4"],
                    score_target=d["score_target"],
                    layer=d["layer"],
                    reason=d.get("reason"),
                ))
                added += 1
        print(f"  Boyutlar: {added} eklendi, {updated} güncellendi")

        # ── Bulgular ──
        f_added = f_refreshed = f_skipped = 0
        seen = set()
        for item in findings:
            code = item["finding_code"]
            if code in seen:
                print(f"  ! Yinelenen kod atlandı: {code}")
                continue
            seen.add(code)

            row = (
                db.query(AuditFinding)
                .filter(
                    AuditFinding.report_id == report.id,
                    AuditFinding.code == code,
                )
                .first()
            )
            if row:
                # Yalnız rapor metnini tazele — kullanıcı alanlarına DOKUNMA
                for field in _REFRESHABLE:
                    src = item.get(field if field != "title" else "title")
                    if src is not None:
                        setattr(row, field, src)
                f_refreshed += 1
            else:
                db.add(AuditFinding(
                    report_id=report.id,
                    code=code,
                    title=item["title"],
                    dimension_no=item["dimension_no"],
                    risk=item["risk"],
                    effort=item["effort"],
                    category=item["category"],
                    status=item.get("status", "acik"),
                    evidence=item.get("evidence"),
                    solution=item.get("solution"),
                    closure_criteria=item.get("closure_criteria"),
                    source_section=item.get("source_section"),
                    score_impact=item.get("score_impact", 0.2),
                    automatable=item.get("automatable", False),
                    # Otomasyon kuyruğu kullanıcı kararıdır — seed hiçbir maddeyi
                    # kendiliğinden kuyruğa sokmaz (istenmeyen otonom koşu olmasın).
                    auto_enabled=False,
                ))
                f_added += 1
        print(f"  Bulgular: {f_added} eklendi, {f_refreshed} tazelendi, {f_skipped} atlandı")

        if args.dry_run:
            db.rollback()
            print("[KURU ÇALIŞMA] Değişiklik yazılmadı.")
            return 0

        db.commit()

        # Özet
        from app.services import audit_tracker_service as svc
        board = svc.scoreboard(db, report)
        print()
        print(f"Genel not : {board['current_score']} / 100 "
              f"(denetim anı {board['baseline_score']} · hedef {board['target_score']})")
        print(f"Bulgular  : {board['counts']['toplam']} toplam · "
              f"{board['counts']['acik']} açık · {board['counts']['kapali']} kapalı · "
              f"{board['counts']['kismen']} kısmen")
        print(f"Kritik açık: {board['counts']['kritik_acik']} · "
              f"Yüksek açık: {board['counts']['yuksek_acik']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
