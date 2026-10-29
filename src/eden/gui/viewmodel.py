"""Plain-data views of Eden's results for the QML interface (no Qt here)."""

from __future__ import annotations

from pathlib import Path

from eden.project.inspector import InspectionReport, SourceAnalysis
from eden.project.plugins import CATEGORY_LABELS_FR
from eden.render.pipeline import RenderResult
from eden.render.plan import RenderPlan

CONTROL_JOBS = [
    ("controle-master", "Contrôle : réinjection dans le Master (effets contournés)"),
    ("controle-eden-0", "Contrôle : mix d'origine repassé dans ton Master"),
]


def _time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def source_view(s: SourceAnalysis) -> dict:
    file_name, file_status, file_info = "", "", ""
    if s.sample:
        file_name = Path(s.sample.stored_path.replace("\\", "/")).name
        file_status = s.sample.status
        if s.sample.audio:
            a = s.sample.audio
            file_info = (f"{a.sample_rate / 1000:g} kHz · "
                         f"{'mono' if a.channels == 1 else 'stéréo' if a.channels == 2 else f'{a.channels} canaux'}"
                         f" · {_time(a.duration_s)}")
    return {
        "channel": s.channel,
        "label": s.label,
        "role": s.role.label,
        "roleKey": s.role.role,
        "confidence": s.role.confidence,
        "reasons": s.role.reasons,
        "insert": s.insert_label or "Master",
        "reachesMaster": s.reaches_master,
        "instrument": s.plugin or "",
        "file": file_name,
        "fileStatus": file_status,
        "fileInfo": file_info,
        "clips": s.clip_count,
        "span": f"{_time(s.first_seconds)} → {_time(s.last_seconds)}" if s.clip_count else "",
        "effects": [
            {"name": fx.plugin, "category": CATEGORY_LABELS_FR.get(fx.category, fx.category),
             "categoryKey": fx.category, "active": fx.active, "where": fx.insert_label}
            for fx in s.existing_effects
        ],
    }


def report_view(r: InspectionReport) -> dict:
    p = r.project
    return {
        "name": Path(r.file.path).stem,
        "path": r.file.path,
        "flVersion": p.fl_version or "inconnue",
        "tempo": f"{p.tempo_bpm:g} BPM" if p.tempo_bpm else "—",
        "timeSignature": f"{p.time_signature[0]}/{p.time_signature[1]}" if p.time_signature else "—",
        "duration": _time(r.project_end_seconds),
        "title": p.title or "",
        "artists": p.artists or "",
        "voices": [source_view(s) for s in r.vocal_sources],
        "others": [source_view(s) for s in r.sources if not s.role.is_vocal],
        "masterEffects": [{"name": fx.plugin,
                           "category": CATEGORY_LABELS_FR.get(fx.category, fx.category),
                           "active": fx.active} for fx in r.master_effects],
        "insertCount": len(r.used_inserts),
        "warnings": r.warnings,
        "limitations": r.limitations,
    }


def render_rows(plan: RenderPlan) -> list[dict]:
    """Rows shown while FL Studio renders, in the order the pipeline reports steps."""
    rows = [{"name": j.name, "description": j.description, "kind": j.kind, "status": "pending",
             "detail": ""} for j in plan.jobs]
    rows.append({"name": "verification", "description": "Vérification : la somme des pistes "
                 "reproduit-elle le mix ?", "kind": "check", "status": "pending", "detail": ""})
    rows.extend({"name": n, "description": d, "kind": "control", "status": "pending", "detail": ""}
                for n, d in CONTROL_JOBS)
    return rows


def mark_step(rows: list[dict], index: int) -> list[dict]:
    rows = [dict(r) for r in rows]
    for i, row in enumerate(rows):
        if i < index and row["status"] in ("pending", "running"):
            row["status"] = "done"
        elif i == index:
            row["status"] = "running"
    return rows


def _master_message(result: RenderResult) -> str:
    mt, cal = result.master_test, result.calibration
    if mt is not None:
        if mt.passed:
            return (f"Ton Master FL est conservé : ton mix repassé dedans redonne exactement "
                    f"ton morceau (écart {mt.residual_db:.0f} dB)")
        return (f"Ton mix repassé dans le Master FL ne redonne pas exactement le morceau "
                f"(écart {mt.residual_db:.0f} dB)")
    if cal is not None:
        return cal.message
    return "Contrôle du Master non effectué (les pistes doivent d'abord être validées)"


def render_view(rows: list[dict], result: RenderResult) -> tuple[list[dict], dict]:
    by_name = {j.job.name: j for j in result.jobs}
    out = []
    for row in rows:
        row = dict(row)
        jr = by_name.get(row["name"])
        if jr is not None:
            row["status"] = jr.status
            if jr.check:
                row["detail"] = f"{jr.check.duration_s:.1f} s · crête {jr.check.peak_db:.1f} dBFS"
            if jr.error:
                row["detail"] = jr.error
        elif row["name"] == "verification":
            nt = result.null_test
            row["status"] = "done" if nt and nt.passed else "failed" if nt else "skipped"
            row["detail"] = nt.message if nt else ""
        else:
            row["status"] = "skipped"
        out.append(row)
    summary = {
        "ok": result.ok,
        "stemsOk": result.stems_ok,
        "masterOk": result.master_ok,
        "nullMessage": result.null_test.message if result.null_test else
        "Aucune piste à comparer",
        "masterMessage": _master_message(result),
        "folder": result.folder,
        "warnings": result.warnings,
        "stemCount": len([j for j in result.jobs if j.job.kind == "stem"]),
        "vocalCount": len([j for j in result.jobs if j.job.kind == "vocal"]),
    }
    return out, summary
