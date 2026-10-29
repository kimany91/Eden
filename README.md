# Eden

Assistant de mixage automatique de voix rap pour projets **FL Studio**.
Objectif : sélectionner un projet `.flp`, laisser Eden analyser et mixer, écouter,
ajuster, puis exporter un WAV final — sans jamais modifier le projet original.

## État actuel (v0.1.0)

| Phase | État |
|---|---|
| 1. Audit et architecture | ✅ [docs/01-audit-architecture.md](docs/01-audit-architecture.md) |
| 2. Inspection en lecture seule | ✅ testée sur projets de test (FL 20.8) — à valider sur tes projets |
| 3. Rendu FL Studio et stems | ⏳ |
| 4. Moteur de mixage + export WAV | ⏳ |
| 5. Interface complète, installateur | ⏳ (une première fenêtre d'inspection existe) |
| 6. Tests et amélioration | ⏳ |

Plan détaillé et critères de validation : [docs/02-plan-developpement.md](docs/02-plan-developpement.md).

**Ce qu'Eden fait aujourd'hui** : lit un `.flp` (canaux, Mixer, routages, effets et VST
présents, playlist, tempo), retrouve les fichiers audio même si le projet a été déplacé,
identifie les voix (lead, doublages, backs, ad-libs) et l'instru avec les raisons de
chaque choix, liste les traitements déjà appliqués sur le chemin de chaque voix, et
produit un rapport. **Il ne mixe pas encore et n'exporte pas encore de WAV.**

## Installation (Windows, depuis le code source)

Prérequis : [Python 3.12](https://www.python.org/downloads/windows/) (cocher « Add to PATH »).

```powershell
git clone https://github.com/kimany91/eden.git
cd eden
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[gui]"
```

## Utilisation

```powershell
eden                                   # ouvre l'interface
eden inspect "C:\...\Mon son.flp"      # rapport dans le terminal
eden inspect "C:\...\Mon son.flp" --markdown rapport.md --json rapport.json
eden update                            # rechercher une mise à jour maintenant
```

Eden ne modifie jamais le projet : il le lit une fois, vérifie son empreinte SHA-256 avant
et après, et range ses propres fichiers (copie du projet, rapports) dans
`%LOCALAPPDATA%\Eden\projects\`, jamais dans le dossier du projet.

## Mises à jour automatiques

Voir [docs/mises-a-jour.md](docs/mises-a-jour.md) : vérification quotidienne en
arrière-plan, téléchargement vérifié par SHA-256, installation à la fermeture d'Eden.

## Développement

```bash
pip install -e ".[gui,dev]"
python tools/fetch_test_assets.py   # vrai projet FL 20.8 pour les tests (non versionné)
python -m pytest
```

Notes sur le format `.flp` : [docs/format-flp.md](docs/format-flp.md).
