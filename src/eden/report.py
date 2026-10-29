"""Human-readable (French) rendering of an inspection report."""

from __future__ import annotations

from eden.project.classify import ROLE_LABELS_FR
from eden.project.inspector import InspectionReport, SourceAnalysis
from eden.project.plugins import CATEGORY_LABELS_FR

_SAMPLE_STATUS_FR = {
    "found": "trouvé",
    "found_elsewhere": "retrouvé ailleurs",
    "missing": "introuvable",
    "unreadable": "illisible",
}

# What the report and the interface say of an effect FL does not play (ExistingEffect.inactive_reason).
INACTIVE_LABELS_FR = {
    "off": "désactivé",
    "mix_zero": "inaudible (mix à 0 %)",
    "insert_muted": "inaudible (insert coupé)",
    "no_output": "inaudible (insert sans sortie vers le Master)",
}


def _t(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def _pct(raw: int | None, ref: int) -> str:
    return "?" if raw is None else f"{raw / ref * 100:.0f} %"


def _source_lines(s: SourceAnalysis) -> list[str]:
    lines = [f"### {s.label} — {s.role.label} (confiance {s.role.confidence})"]
    if s.kind == "instrument":
        lines.append(f"- Instrument virtuel : {s.plugin}")
    if s.sample:
        status = _SAMPLE_STATUS_FR.get(s.sample.status, s.sample.status)
        lines.append(f"- Fichier : `{s.sample.stored_path}` ({status})")
        if s.sample.resolved_path and s.sample.status == "found_elsewhere":
            lines.append(f"  - retrouvé ici : `{s.sample.resolved_path}`")
        if s.sample.audio:
            a = s.sample.audio
            lines.append(
                f"  - {a.sample_rate} Hz, {'mono' if a.channels == 1 else f'{a.channels} canaux'}, "
                f"{a.subtype}, {_t(a.duration_s)}"
            )
        if s.sample.note:
            lines.append(f"  - {s.sample.note}")
    path = " → ".join("Master" if i == 0 else f"Insert {i}" for i in s.signal_path)
    lines.append(f"- Routage : {path}{'' if s.reaches_master else ' (n’atteint pas le Master)'}")
    if s.clip_count:
        lines.append(
            f"- Playlist : {s.clip_count} clip(s), de {_t(s.first_seconds)} à {_t(s.last_seconds)}"
        )
    else:
        lines.append("- Playlist : aucun clip trouvé dans les arrangements")
    if s.existing_effects:
        lines.append("- Effets déjà présents sur le chemin du signal :")
        for fx in s.existing_effects:
            state = "" if fx.active else f" — {INACTIVE_LABELS_FR[fx.inactive_reason]}"
            lines.append(
                f"  - {fx.insert_label} / slot {fx.slot + 1} : {fx.plugin} "
                f"[{CATEGORY_LABELS_FR.get(fx.category, fx.category)}]{state}"
            )
    else:
        lines.append("- Aucun effet de Mixer sur le chemin du signal")
    lines.append("- Indices : " + ("; ".join(s.role.reasons) or "aucun"))
    return lines


def render_markdown(r: InspectionReport) -> str:
    p = r.project
    out = [f"# Rapport d'inspection Eden — {r.file.path.replace(chr(92), '/').split('/')[-1]}", ""]
    out.append("Analyse en lecture seule : le projet FL Studio n'a pas été modifié "
               f"(empreinte SHA-256 `{r.file.sha256[:16]}…` vérifiée avant et après).")
    out.append("")
    out.append("## Projet")
    out.append(f"- FL Studio : {p.fl_version or 'inconnue'}")
    out.append(f"- Tempo : {p.tempo_bpm:g} BPM" if p.tempo_bpm else "- Tempo : inconnu")
    if p.time_signature:
        out.append(f"- Mesure : {p.time_signature[0]}/{p.time_signature[1]}")
    out.append(f"- Résolution : {p.ppq} PPQ")
    for label, value in (("Titre", p.title), ("Artiste", p.artists), ("Genre", p.genre),
                         ("Créé le", p.created)):
        if value:
            out.append(f"- {label} : {value}")
    if p.time_spent_hours is not None:
        out.append(f"- Temps passé : {p.time_spent_hours:g} h")
    out.append(f"- Fin du dernier clip : {_t(r.project_end_seconds)}")
    out.append(f"- Canaux : {len(p.channels)} ; inserts utilisés : {len(r.used_inserts)} ; "
               f"arrangements : {len(p.arrangements)} ; patterns : {len(p.patterns)}")
    out.append("")

    vocals = r.vocal_sources
    others = [s for s in r.sources if not s.role.is_vocal]
    out.append(f"## Voix détectées ({len(vocals)})")
    out.append("")
    for s in vocals:
        out.extend(_source_lines(s))
        out.append("")
    if not vocals:
        out.append("_Aucune voix reconnue automatiquement._")
        out.append("")
    out.append(f"## Autres sources ({len(others)})")
    out.append("")
    for s in others:
        out.extend(_source_lines(s))
        out.append("")

    out.append("## Mixer")
    out.append("")
    out.append("| Insert | Nom | Volume | Pan | Effets | Sorties |")
    out.append("|---|---|---|---|---|---|")
    for ins in p.inserts:
        if ins.index not in r.used_inserts and ins.is_default:
            continue
        fx = ", ".join(
            s.plugin.label + ("" if s.enabled is not False else " (off)") for s in ins.slots
        ) or "—"
        if ins.effects_enabled is False and ins.slots:
            fx += " **(effets bypassés)**"
        routes = ", ".join(
            "Master" if rt.target == 0 else f"Insert {rt.target}"
            for rt in ins.routes if rt.audible
        ) or "—"
        state = "" if ins.enabled is not False else " (désactivé)"
        pan = "?" if ins.pan_raw is None else f"{ins.pan_raw / 64:+.0f}"
        out.append(f"| {ins.index} | {ins.label}{state} | {_pct(ins.volume_raw, 12800)} | {pan} "
                   f"| {fx} | {routes} |")
    out.append("")
    out.append("Volume : 100 % = position par défaut du fader (0 dB). Pan : −100 (gauche) à +100 (droite). "
               "Les envois réglés à 0 ne sont pas listés.")
    out.append("")

    autom = [p.channel(i) for i in p.automation_channels]
    if autom:
        out.append("## Automations")
        for ch in autom:
            if ch is not None:
                out.append(f"- {ch.label} (cible non décodée pour l'instant)")
        out.append("")

    if r.warnings:
        out.append("## Avertissements")
        out.extend(f"- {w}" for w in r.warnings)
        out.append("")
    out.append("## Limites de cette analyse")
    out.extend(f"- {l}" for l in r.limitations)
    out.append("")
    out.append("## Rôles possibles")
    out.append(", ".join(ROLE_LABELS_FR.values()))
    return "\n".join(out) + "\n"
