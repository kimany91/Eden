# Eden

Assistant de mixage automatique de voix rap pour projets **FL Studio**.
Objectif : sélectionner un projet `.flp`, laisser Eden analyser et mixer, écouter,
ajuster, puis exporter un WAV final — sans jamais modifier le projet original.

## État actuel (v0.1.0)

| Phase | État |
|---|---|
| 1. Audit et architecture | ✅ [docs/01-audit-architecture.md](docs/01-audit-architecture.md) |
| 2. Inspection en lecture seule | ✅ testée sur projets de test (FL 20.8) — à valider sur tes projets |
| 3. Pilotage de FL Studio et récupération du son | ✅ implémenté et testé avec un simulateur — à valider avec ton FL Studio (`eden fl-probe`) |
| 4. Moteur de mixage + export WAV | ⏳ |
| 5. Interface et installateur | ✅ interface animée (QML), installateur Windows construit et testé automatiquement — reste : lecteur A/B, réglages de mixage |
| 6. Tests et amélioration | ⏳ |

Plan détaillé et critères de validation : [docs/02-plan-developpement.md](docs/02-plan-developpement.md).

**Ce qu'Eden fait aujourd'hui** : lit un `.flp` (canaux, Mixer, routages, effets et VST
présents, playlist, tempo), retrouve les fichiers audio même si le projet a été déplacé,
identifie les voix (lead, doublages, backs, ad-libs) et l'instru avec les raisons de
chaque choix, liste les traitements déjà appliqués sur le chemin de chaque voix, et
produit un rapport.

Ensuite, **Eden pilote FL Studio lui-même** : il crée des copies de travail du projet
(certaines pistes coupées, chemins audio réparés), ouvre FL Studio en arrière-plan pour
rendre chaque groupe de pistes avec tous ses effets, puis vérifie que la somme des pistes
récupérées redonne exactement le mix d'origine. Ces pistes alimenteront le moteur de
mixage d'Eden. **Ton mastering reste dans FL Studio** : Eden sait déjà repasser un mix
dans ton propre Master FL (il le vérifie à chaque rendu). **Le moteur de mixage et
l'export du WAV final ne sont pas encore faits.**

## Installation (Windows)

1. Télécharge **`Eden-Setup-x.y.z.exe`** (page *Releases* du dépôt, ou l'artefact du
   dernier passage de « Installateur Windows » dans l'onglet *Actions*).
2. Double-clique dessus : l'installation se fait sans droits administrateur, crée les
   raccourcis Menu Démarrer et Bureau (icône : l'arbre jaune d'Eden) et lance Eden.
3. Dans Eden : glisse ton projet `.flp`, l'analyse démarre ; clique ensuite sur
   « Récupérer le son depuis FL Studio ». La première fois, Eden apprend tout seul à
   piloter ton FL Studio (FL doit être fermé).

Aucune ligne de commande, et Python n'est pas nécessaire. Les mises à jour s'installent
ensuite automatiquement à la fermeture d'Eden.

Chaque installateur est vérifié automatiquement sur une machine Windows avant d'être
publié : construction, démarrage de l'application, installation silencieuse,
raccourcis, démarrage de la version installée, désinstallation.

## Utilisation avancée (développeurs)

```powershell
pip install -e ".[gui]"
eden inspect "C:\...\Mon son.flp"      # rapport dans le terminal
eden fl-probe "C:\...\Mon son.flp"     # test du pilotage de FL Studio
eden render "C:\...\Mon son.flp"       # rendu de toutes les pistes
```

Eden ne modifie jamais le projet : il le lit une fois, vérifie son empreinte SHA-256 avant
et après, et range ses propres fichiers (copies, rendus, rapports) dans
`%LOCALAPPDATA%\Eden\`, jamais dans le dossier du projet. La désinstallation ne
supprime pas ces fichiers.

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
