# Eden

Assistant de mixage automatique de voix rap pour projets **FL Studio**.
Objectif : sélectionner un projet `.flp`, laisser Eden analyser et mixer, écouter,
ajuster, puis exporter un WAV final — sans jamais modifier le projet original.

## État actuel (v1.2.2)

| Phase | État |
|---|---|
| 1. Audit et architecture | ✅ [docs/01-audit-architecture.md](docs/01-audit-architecture.md) |
| 2. Inspection en lecture seule | ✅ testée sur projets de test (FL 20.8) — à valider sur tes projets |
| 3. Pilotage de FL Studio et récupération du son | ✅ implémenté et testé avec un simulateur — à valider avec ton FL Studio (`eden fl-probe`) |
| 4. Mixage et mastering Eden, export WAV | ✅ moteur v2 (tonalité, chaîne vocale pro, espace, stéréo, basses, master fort pour les plateformes) testé avec voix de test et simulateur FL — à valider à l'écoute ([docs/mixage.md](docs/mixage.md)) |
| 5. Interface et installateur | ✅ interface animée (QML), jardin 3D pendant le travail, écoute avant / après, installateur Windows construit et testé automatiquement — reste : réglages par traitement |
| 6. Tests et amélioration | ⏳ |

Plan détaillé et critères de validation : [docs/02-plan-developpement.md](docs/02-plan-developpement.md).

**Ce qu'Eden fait aujourd'hui** : lit un `.flp` (canaux, Mixer, routages, effets et VST
présents, playlist, tempo), retrouve les fichiers audio même si le projet a été déplacé,
identifie les voix (lead, doublages, backs, ad-libs) et l'instru avec les raisons de
chaque choix, liste les traitements déjà appliqués sur le chemin de chaque voix, et
produit un rapport. Une prod téléchargée d'un seul fichier (sur YouTube par exemple) est
reconnue comme l'instru complète quel que soit son nom : elle est déjà mixée et
masterisée, Eden ne retouche pas son mix et ne l'écrase pas une deuxième fois au master.

Ensuite, **Eden pilote FL Studio lui-même** : c'est FL Studio qui joue chaque partie du
morceau (voix seule, instru, chaque groupe) avec **tous tes effets** — Auto-Tune, delays
réglés au millimètre, échos, automations — et Eden récupère ce son exact. Eden ne recrée
aucun effet. Pour que FL joue une partie seule, Eden lui donne une copie temporaire du
projet où les autres pistes sont coupées ; cette copie est effacée dès que FL a fini.
Eden vérifie ensuite que la somme des parties redonne exactement le mix d'origine, et que
les fins d'écho ou de reverb ne sont pas coupées. Chaque voix qui porte une reverb ou un
delay FL est aussi rendue **sans** eux : Eden travaille la voix sèche comme un ingénieur
du son et remet tes effets tels quels par-dessus.

Enfin, **Eden mixe et masterise** : tonalité et tempo du morceau, notes du 808, chaîne
vocale complète (coupe-bas réglé sur la note la plus grave, résonances, de-esser en deux
passes, compression en deux étages puis parallèle, saturation, air ou recul des aigus),
niveau de la voix suivi phrase par phrase au-dessus de l'instru, espace (ambiance, plate,
delay sur le tempo, jet d'écho en fin de phrase) seulement pour les voix qui n'en ont pas,
placement stéréo des doublages, chœurs et ad-libs, place pour les paroles dans l'instru,
kick / 808, puis un master fort et propre pour les plateformes (−9 LUFS, crête réelle à
−3 dBTP, ou −2 dBTP quand le morceau s'arrête plus bas). Chaque décision est expliquée ; tu règles l'intensité (0 % = ton mix d'origine
avant le Master, à l'identique), tu gardes chaque version et tu exportes le WAV final.
Détails : [docs/mixage.md](docs/mixage.md).

**Pendant qu'Eden travaille**, toute la fenêtre devient un jardin en 3D : un arbre aux
feuilles jaunes du logo pousse avec le travail réellement fait. La graine germe pendant
l'analyse, la tige et la première branche avec ses feuilles poussent pendant que FL Studio
joue tes pistes, la couronne se remplit pendant le mix et s'achève avec le master. En bas,
un journal dit en français chaque étape et chaque décision. La caméra tourne lentement
autour de l'arbre ; fais glisser pour tourner toi-même, molette pour zoomer. À la fin, une
pomme pousse et tombe, la caméra la suit, puis la page du résultat s'ouvre : **écoute avant
/ après** (le même instant dans les deux versions ; « même volume » baisse la plus forte
pour juger le mix et pas le volume ; espace, A et B au clavier), réglages et export.
L'arbre est généré une fois et dessiné par la carte graphique (quelques appels de dessin
pour tout le jardin), sans calcul par image côté Python.

## Installation (Windows)

1. Télécharge **`Eden-Setup-x.y.z.exe`** sur la page de la dernière version :
   <https://github.com/kimany91/Eden/releases/latest>.
2. Double-clique dessus : l'installation se fait sans droits administrateur, crée les
   raccourcis Menu Démarrer et Bureau (icône : l'arbre jaune d'Eden) et lance Eden.
   L'installateur n'est pas signé (la signature de code Windows est payante) : si Windows
   affiche « Windows a protégé votre ordinateur », clique sur « Informations
   complémentaires » puis « Exécuter quand même ».
3. Dans Eden : la première fois, choisis le dossier où tu enregistres tes projets FL Studio
   (celui de FL, `Documents\Image-Line\FL Studio\Projects`, est proposé s'il existe) ; Eden
   s'en souvient et te montre tous tes projets, les plus récents en premier. Clique sur un
   projet (FL Studio fermé) : Eden fait tout d'une traite, analyse, son de FL Studio, mix,
   master, sans ouvrir de fenêtre par-dessus. La première fois, il apprend tout seul à
   piloter ton FL Studio. Il ne s'arrête que si quelque chose bloque (FL Studio introuvable,
   une erreur), et dit pourquoi.

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
eden mix "C:\...\Mon son.flp" --export "C:\...\Mon son - Eden.wav"
```

Eden ne modifie jamais le projet : il le lit une fois, vérifie son empreinte SHA-256 avant
et après, et range ses propres fichiers (sons rendus par FL, rapports) dans
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
