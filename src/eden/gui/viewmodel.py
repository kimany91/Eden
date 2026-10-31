"""Plain-data views of Eden's results for the QML interface (no Qt here)."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from eden.mix.export import SAMPLE_RATES, ExportResult
from eden.project.classify import ROLE_LABELS_FR
from eden.project.inspector import InspectionReport, SourceAnalysis
from eden.project.library import ProjectEntry
from eden.project.plugins import CATEGORY_LABELS_FR
from eden.render.pipeline import RenderResult
from eden.render.plan import RenderPlan
from eden.report import INACTIVE_LABELS_FR

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
             "categoryKey": fx.category, "active": fx.active, "where": fx.insert_label,
             "inactive": "" if fx.active else INACTIVE_LABELS_FR[fx.inactive_reason]}
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
        "idleChannels": [ch.label for i in r.idle_channels if (ch := p.channel(i)) is not None],
        "warnings": r.warnings,
        "limitations": r.limitations,
    }


def render_rows(plan: RenderPlan) -> list[dict]:
    """Rows shown while FL Studio renders, in the order the pipeline reports steps."""
    rows = [{"name": j.name, "description": j.description, "kind": j.kind, "status": "pending",
             "detail": ""} for j in plan.jobs]
    rows.append({"name": "verification", "description": "Vérification : la somme des pistes "
                 "reproduit-elle le mix ?", "kind": "check", "status": "pending", "detail": ""})
    return rows


def mark_step(rows: list[dict], index: int) -> list[dict]:
    """FL Studio renders the parts together, in any order: before it starts (``index`` -1) they are all
    under way, then each one is done as it comes (``index``); the last row, the verification, runs once
    they all are."""
    rows = [dict(r) for r in rows]
    last = len(rows) - 1
    for i, row in enumerate(rows[:last]):
        if index < 0 and row["status"] == "pending":
            row["status"] = "running"
        elif index in (i, last) and row["status"] in ("pending", "running"):
            row["status"] = "done"
    if index == last:
        rows[last]["status"] = "running"
    return rows


def rendered_share(rows: list[dict]) -> float:
    """How much of FL Studio's renders is done."""
    return sum(r["status"] == "done" for r in rows) / len(rows) if rows else 0.0


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
    if result.ok:
        verdict = ("Chaque partie a été jouée par FL Studio avec tes effets, puis vérifiée par Eden : tout est bon."
                   if not result.warnings else
                   "Chaque partie a été jouée par FL Studio avec tes effets et vérifiée par Eden, avec des points "
                   "à vérifier (voir ci-dessous).")
    elif result.complete:
        verdict = ("La somme des pistes ne redonne pas ton morceau (voir ci-dessous) : relance la récupération, "
                   "ou mixe quand même (ce qu'Eden n'a pas pu séparer reste tel quel).")
    else:
        verdict = ("Le son récupéré n'a pas passé ses vérifications (voir ci-dessous) : le mixage attend une "
                   "nouvelle récupération.")
    summary = {
        "ok": result.ok,
        "complete": result.complete,
        "verdict": verdict,
        "nullMessage": result.null_test.message if result.null_test else
        "Aucune piste à comparer",
        "folder": result.folder,
        "warnings": result.warnings,
        "stemCount": len([j for j in result.jobs if j.job.kind == "stem"]),
        "vocalCount": len([j for j in result.jobs if j.job.kind == "vocal"]),
    }
    return out, summary


def _db(value: float | None, unit: str) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.1f} {unit}"


def _finite(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _local_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


FL_SPACE_FR = {
    "tracked": "Reverb / delay FL Studio gardés tels quels (rendus à part)",
    "untracked": "Reverb / delay FL Studio dans la voix : compression prudente, rien ajouté",
    "printed": "Prise déjà produite (effets enregistrés dedans) : respirations et de-esser seulement, "
               "son laissé tel quel",
}
MIX_ROLE_LABELS_FR = {**ROLE_LABELS_FR, "residual": "Reste du mix"}  # listed when Eden carved it


def _song_lines(song: dict) -> list[str]:
    lines = []
    if song.get("key"):
        lines.append(f"Tonalité : {song['key']} (confiance {song.get('key_confidence') or '?'})")
    if abs(song.get("tuning_cents") or 0) >= 10:
        lines.append(f"Accordage du beat : La = {440 * 2 ** (song['tuning_cents'] / 1200):.0f} Hz "
                     f"({song['tuning_cents']:+.0f} cents)")
    if song.get("tempo_bpm"):
        lines.append(f"Tempo : {song['tempo_bpm']:g} BPM, noire ressentie {song['felt_quarter_ms']:.0f} ms")
    if song.get("bass_root"):
        bass = f"808 / basse : note principale {song['bass_root']}"
        if song.get("bass_out_of_scale"):
            bass += f" ; hors gamme : {', '.join(song['bass_out_of_scale'])}"
        lines.append(bass)
    if song.get("kick_overlap"):
        lines.append(f"Kick et 808 ensemble sur {song['kick_overlap'] * 100:.0f} % des kicks")
    return lines


def reduction_text(kind: str, measured: dict) -> str:
    """For a compressor or a de-esser: the gain reduction it really applied, as measured while
    applying it (mean over the moments it reduces, and maximum); empty for the other steps."""
    if kind not in ("compressor", "deesser") or "reduction_max_db" not in measured:
        return ""
    return (f"Réduction mesurée : {measured['reduction_mean_db']:.1f} dB en moyenne quand il agit, "
            f"{measured['reduction_max_db']:.1f} dB au plus")


def _treatment_view(t: dict) -> dict:
    return {"label": t["label"], "reason": t["reason"],
            "measured": reduction_text(t.get("kind", ""), t.get("measured") or {})}


def mix_view(version: dict) -> dict:
    """A saved mix version (as stored in version.json) for the mix page. Versions saved before
    Eden 0.4.0 have no song, master or checks: those lines are left empty."""
    parts = []
    changed = False
    for p in version["parts"]:
        changes = [*p.get("space", [])]
        if p.get("placement"):
            changes.append(p["placement"])
        changed = changed or bool(p["treatments"] or changes)
        notes = [*changes]
        if p.get("fl_space") in FL_SPACE_FR:
            notes.append(FL_SPACE_FR[p["fl_space"]])
        after = p["loudness_after"]
        parts.append({
            "label": p["label"],
            "role": MIX_ROLE_LABELS_FR.get(p["role"], p["role"]),
            "roleKey": p["role"],
            "treatments": [_treatment_view(t) for t in p["treatments"]],
            "notes": notes,
            "change": f"{_db(p['loudness_before'], 'LUFS')} → {_db(after, 'LUFS')}"
            if p["treatments"] and after is not None and after == after else "",
        })
    o, f, c = version["original"], version["final"], version.get("checks")
    return {
        "id": version["id"],
        "date": _local_date(version["created_at"]),
        "intensity": round(version["intensity"] * 100),
        "finalWav": version["final_wav"],
        "song": _song_lines(version.get("song", {})),
        "parts": parts,
        "untouched": not changed,
        "master": [_treatment_view(t) for t in version.get("master", [])],
        "checks": [
            f"Plage de volume {c['loudness_range_lu']:.1f} LU",
            f"Crête / volume {c['plr_db']:.1f} dB",
            f"Perte en mono {-c['mono_loss_db']:.1f} dB",
        ] if c else [],
        "platforms": [{"name": pf["name"], "gain": f"{pf['gain_db']:+.1f} dB",
                       "heard": _db(pf["heard_lufs"], "LUFS")} for pf in (c or {}).get("platforms", [])],
        "original": {"lufs": _db(o["loudness_lufs"], "LUFS"), "truePeak": _db(o["true_peak_db"], "dBTP")},
        "final": {"lufs": _db(f["loudness_lufs"], "LUFS"), "truePeak": _db(f["true_peak_db"], "dBTP"),
                  "sampleRate": f["sample_rate"]},
        # what the before / after player compares (versions saved before Eden 1.1 do not name the original)
        "originalWav": version.get("original_wav", ""),
        "loudness": {"original": _finite(o["loudness_lufs"]), "final": _finite(f["loudness_lufs"])},
        "warnings": version.get("warnings", []),
    }


# -- the journal shown under the growing tree: (text, kind) lines, kind is
# stage | step | detail | done | warn | error ------------------------------------------------------

def _names(items: list[str], most: int = 6) -> str:
    shown = ", ".join(items[:most])
    return shown + (f" et {len(items) - most} autre(s)" if len(items) > most else "")


def analysis_lines(report: dict) -> list[tuple[str, str]]:
    """What the analysis found, from ``report_view``."""
    lines = [(f"Projet « {report['name']} » : FL Studio {report['flVersion']}, {report['tempo']}, "
              f"mesure {report['timeSignature']}, durée {report['duration']}, "
              f"{report['insertCount']} pistes de Mixer utilisées", "done")]
    for v in report["voices"]:
        effects = [fx["name"] for fx in v["effects"] if fx["active"]]
        lines.append((f"Voix trouvée : « {v['label']} » → {v['role']}"
                      + (f" ; effets : {_names(effects)}" if effects else " ; sans effet"), "detail"))
    if not report["voices"]:
        lines.append(("Aucune voix reconnue dans le projet", "warn"))
    others = [f"« {o['label']} » ({o['role']})" for o in report["others"]]
    if others:
        lines.append(("Instru : " + _names(others), "detail"))
    idle = report.get("idleChannels", [])
    if idle:
        lines.append((f"{len(idle)} canal(aux) du Channel Rack ne joue(nt) nulle part dans le morceau, ignoré(s) "
                      f"même si un fichier manque : {_names([f'« {n} »' for n in idle])}", "detail"))
    master = [fx["name"] for fx in report["masterEffects"] if fx["active"]]
    if master:
        lines.append((f"Effets de ton Master FL : {_names(master)} ; ils restent pour ton écoute dans FL, "
                      "Eden fait son propre mastering", "detail"))
    lines += [(w, "warn") for w in report["warnings"]]
    return lines


def render_lines(rows: list[dict], summary: dict) -> list[tuple[str, str]]:
    """What FL Studio rendered, from ``render_view``."""
    lines = []
    for row in rows:
        if row["name"] == "verification":
            continue
        kind = "error" if row["status"] == "failed" else "done"
        lines.append((f"{row['description']} : " + (row["detail"] or row["status"]), kind))
    lines.append((summary["nullMessage"], "done" if summary["ok"] else "error"))
    lines += [(w, "warn") for w in summary["warnings"]]
    return lines


def mix_lines(view: dict) -> list[tuple[str, str]]:
    """The result of a mix, from ``mix_view``."""
    o, f = view["original"], view["final"]
    lines = [(f"Ton morceau d'origine : {o['lufs']}, crête réelle {o['truePeak']}", "detail"),
             (f"Avec Eden : {f['lufs']}, crête réelle {f['truePeak']}", "done")]
    return lines + [(w, "warn") for w in view["warnings"]]


def versions_view(versions: list[dict]) -> list[dict]:
    return [{"id": v["id"], "date": _local_date(v["created_at"]),
             "intensity": round(v["intensity"] * 100),
             "lufs": _db(v["final"]["loudness_lufs"], "LUFS")} for v in versions]


def saved_when(modified: float, now: float) -> str:
    """When a project was last saved, as the home page says it ("Aujourd'hui à 14:02", "Il y a 3 jours")."""
    saved, today = datetime.fromtimestamp(modified), datetime.fromtimestamp(now)
    days = (today.date() - saved.date()).days
    if days <= 0:
        return f"Aujourd'hui à {saved:%H:%M}"
    if days == 1:
        return f"Hier à {saved:%H:%M}"
    if days < 7:
        return f"Il y a {days} jours"
    return f"{saved:%d/%m/%Y}"


def project_rows(entries: list[ProjectEntry], now: float) -> list[dict]:
    """The projects of the home page, with their subfolder (less a last folder named as the project:
    FL Studio gives each project its own)."""
    rows = []
    for e in entries:
        folder = Path(e.folder)
        if folder.name == e.name:
            folder = folder.parent
        rows.append({"name": e.name, "path": str(e.path), "folder": "" if str(folder) == "." else folder.as_posix(),
                     "saved": saved_when(e.modified, now)})
    return rows


def sample_rate_choices() -> list[dict]:
    """The sample rates the export accepts besides FL Studio's own, with French labels ("44,1 kHz")."""
    return [{"label": f"{rate / 1000:g} kHz".replace(".", ","), "value": rate} for rate in SAMPLE_RATES]


def export_message(result: ExportResult) -> str:
    depth = "32 bits flottant" if result.bit_depth == 32 else f"{result.bit_depth} bits"
    extras = [x for x, on in (("fréquence convertie", result.resampled),
                              ("avec dither", result.dithered)) if on]
    details = f"{result.sample_rate / 1000:g} kHz, {depth}" + (", " + ", ".join(extras) if extras else "")
    if math.isfinite(result.true_peak_dbtp):
        details += f", crête {_db(result.true_peak_dbtp, 'dBTP')}"
    return f"WAV exporté : {result.path} ({details})"
