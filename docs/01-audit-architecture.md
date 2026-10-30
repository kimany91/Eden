# Eden — Audit technique et architecture

_Phase 1. Rédigé le 29/10/2026, version d'Eden 0.1.0._

Ce document sépare ce qui a été **vérifié** (testé dans ce dépôt) de ce qui est
**rapporté par des sources tierces et reste à vérifier** sur ton PC avec FL Studio.

---

## 1. Audit de l'environnement

| Élément | Constat |
|---|---|
| Dépôt | Vide au départ (aucun code existant). |
| Environnement de développement | Conteneur Linux dans le cloud. Python 3.13 (3.10–3.12 aussi disponibles), ffmpeg présent. |
| FL Studio | **Absent** : pas de Windows, pas de FL Studio, pas de plugins. Tout ce qui demande FL Studio doit être testé sur ton PC. |
| Projets réels | Aucun de tes projets n'est disponible. Le parseur a été validé sur un vrai projet sauvegardé par **FL Studio 20.8.4** (fichier de test public du projet PyFLP) et sur des projets synthétiques. |
| Réseau | PyPI et GitHub accessibles. Le site et la documentation d'Image-Line **ne sont pas accessibles** depuis cet environnement : les capacités de l'API de script de FL Studio citées plus bas viennent de mes connaissances et de sources communautaires, et sont marquées « à vérifier ». |

### Bibliothèque existante pour lire les .flp : PyFLP

PyFLP est le seul parseur open source connu. Testé ici :

- **ne fonctionne pas** avec Python 3.11 ni 3.13 (erreur à l'import des événements : sa dépendance `f-enum` n'est installée que pour Python ≤ 3.10) ;
- fonctionne avec Python 3.10, mais plante sur les routages du Mixer et les slots d'effets ;
- n'est plus maintenu (dernière version 2.2.1, 2023) et est sous licence **GPL-3.0**.

**Décision** : Eden a son propre lecteur `.flp` (`src/eden/flp/`), écrit pour Eden à
partir de la connaissance publique du format (identifiants d'événements documentés par
PyFLP), et vérifié valeur par valeur contre PyFLP sur le projet FL 20.8 réel. PyFLP n'est
**pas** une dépendance d'Eden.

---

## 2. Comment obtenir les informations d'un projet FL Studio

Aucune interface unique ne donne tout. Quatre voies existent :

### Voie A — Lecture directe du fichier .flp (hors FL Studio) — **implémentée**

Le `.flp` est un flux d'événements binaires (non documenté par Image-Line).

| Information | Accessible ? | Détail |
|---|---|---|
| Version de FL, tempo, mesure, titre, artiste, dates | ✅ vérifié | |
| Canaux (samplers, instruments, automations, layers) | ✅ vérifié | nom, type, activé, verrouillé, volume, pan, insert de destination |
| Chemins des fichiers audio | ✅ vérifié | y compris `%FLStudioFactoryData%` ; Eden retrouve les fichiers déplacés |
| Inserts du Mixer | ✅ vérifié | nom, volume, pan, activé, effets bypassés, polarité, inversion G/D |
| Routages entre inserts / bus | ✅ vérifié | avec niveau d'envoi |
| Plugins dans les slots | ✅ vérifié | nom, activé/désactivé, dry/wet ; pour les VST : nom, éditeur, chemin, VST2/VST3 |
| **Réglages** des plugins | ❌ | stockés en blocs binaires propres à chaque plugin (opaques) |
| Clips de playlist (position, longueur, piste) | ✅ vérifié | clips audio et clips de pattern |
| Notes des patterns → canaux joués | ✅ vérifié (structure) | |
| Clips d'automation | ⚠️ partiel | détectés et placés ; le paramètre ciblé n'est pas encore décodé |
| Marqueurs, signatures rythmiques | ✅ vérifié | |
| Automation de tempo | ❌ pas encore | les secondes supposent un tempo constant |
| **Le son** (effets, instruments virtuels, automations appliqués) | ❌ impossible | seul le moteur audio de FL Studio peut le produire |

Avantages : aucune dépendance à FL Studio, rapide, sans risque (lecture seule).
Limite : on connaît la **structure**, pas le **son** ni les réglages internes des plugins.

### Voie B — API Python de FL Studio (« MIDI Controller Scripting ») — **à vérifier sur ton PC**

FL Studio (depuis la 20.7) exécute des scripts Python à l'intérieur du logiciel, via les
modules `mixer`, `channels`, `plugins`, `playlist`, `arrangement`, `patterns`, `transport`,
`general`, `ui`. D'après la documentation communautaire :

- lecture en direct des noms, volumes, pans, routages du Mixer ;
- lecture des **noms et valeurs des paramètres de plugins** (`plugins.getParamName` /
  `getParamValue`), ce que la voie A ne peut pas faire ;
- **pas** de fonction d'export audio, ni d'ouverture de projet par script (à confirmer) ;
- le script ne communique avec l'extérieur que par **MIDI** : il faut un port MIDI
  virtuel (ex. loopMIDI sur Windows) ; des projets comme « Flapi » utilisent cette méthode ;
- certains appels sont signalés comme lents et peu fiables sur certains VST.

Usage prévu dans Eden (phase 3) : un script « passerelle » installé dans FL Studio qui
exporte les paramètres des plugins de la chaîne vocale. **Optionnel** : Eden doit
fonctionner sans.

### Voie C — Rendu audio par FL Studio — **indispensable pour préserver le son**

C'est la seule façon d'obtenir le son exact (effets, VST, instruments, automations,
bus). Deux modes :

**Choix retenu (demandé) : Eden pilote FL Studio lui-même, sans export manuel.**

- C'est FL Studio qui produit tout le son : Eden ne recrée aucun effet (un delay réglé,
  un Auto-Tune, un écho restent exactement ceux de FL).
- Pour que FL joue une partie seule, Eden écrit une **copie temporaire** du projet dans
  son espace (jamais l'original) : certaines pistes coupées, effets du Master contournés,
  chemins audio réparés. La copie est effacée dès que FL l'a rendue.
- Il lance FL Studio en ligne de commande sur chaque copie (`FL64.exe /R ...`, syntaxe
  rapportée par des utilisateurs) et récupère le WAV produit.
- Comme cette syntaxe n'est pas documentée de façon fiable, rien n'est supposé :
  `eden fl-probe` la teste sur ton PC et vérifie aussi que les coupures de pistes sont
  bien respectées par FL Studio (canaux, inserts, envois vers le Master) et qu'un slot
  d'effet désactivé l'est vraiment (une piste rendue seule avec et sans sa reverb ou son
  delay : l'écart entre les deux rendus doit dépasser −60 dB), avant d'activer le rendu
  automatique. Ce dernier test demande, dans le projet testé, une piste de la playlist qui
  passe par une reverb ou un delay actif dont FL a enregistré l'état activé/désactivé ; sans
  elle, il est noté « non vérifié sur ce projet ». Un slot peut ne rien changer pour une
  raison qui lui est propre (plugin réglé pour laisser passer le son, envoi ou retour
  presque tout en bas ; tout en bas, l'effet est inaudible et n'est pas essayé) : Eden
  essaie alors jusqu'à deux autres slots, de préférence sur un autre insert, et avec une
  autre piste quand il y en a une (le même slot n'est repris avec une autre piste que s'il
  n'en reste aucun autre ; 3 essais au plus, choix d'Eden), note chaque essai dans le compte
  rendu, et ne conclut que FL ne respecte pas un slot désactivé que si aucun essai ne change
  le rendu.
- Plan B si la ligne de commande ne marche pas sur ta version : export guidé
  (« Split mixer tracks ») surveillé par Eden.

### Voie D — Recréer le mix hors de FL à partir des fichiers bruts — **rejetée comme base**

Recharger les WAV bruts et les replacer sur la timeline perdrait les effets, les
instruments virtuels, les automations et les traitements de bus : contraire à
l'exigence « préserver le son ». Les fichiers bruts servent seulement à l'**analyse**
(ex. détecter une prise de voix, mesurer les sifflantes avant traitement).

---

## 3. Préserver le son et éviter les doubles traitements

Principe : **trois couches séparées et traçables**.

1. **Rendu du projet tel qu'il existe** (FL Studio, voie C) → stems par insert.
2. **Traitement additionnel Eden** (moteur de mixage) → appliqué aux stems.
3. **Finition** (niveau, crêtes, true peak) → sur la somme.

Règles :

- **Test de reconstruction (null test)** : la somme des stems rendus doit égaler le rendu
  du Master de FL (écart mesuré, seuil à définir, ex. < −60 dB). Si ce n'est pas le cas,
  Eden refuse de continuer et dit pourquoi (insert non routé au Master, effet aléatoire,
  envoi parallèle…). C'est la garantie que « mix Eden à 0 % = ton mix d'origine avant le
  Master ».
- **Choix des stems par analyse du graphe de routage** (déjà calculé en phase 2) : un
  insert envoyé dans un bus apparaît *aussi* dans le stem du bus. Eden additionne
  uniquement les inserts routés **directement** au Master pour reconstruire le mix, et
  traite un bus vocal comme un groupe si son traitement n'est pas linéaire (reverb,
  compression de bus).
- **Inventaire des traitements existants** (déjà fait en phase 2) : pour chaque voix,
  Eden liste les plugins sur tout le chemin jusqu'au Master avec leur catégorie (correction
  de hauteur, EQ, compression, de-esser, reverb, delay, saturation…) et leur état : actif,
  désactivé (son slot ou les effets de l'insert), ou inaudible (mix à 0 %, insert coupé,
  volume de l'insert à zéro, insert sans sortie vers le Master). Le moteur de mixage s'en
  sert : Eden n'ajoute jamais de correction de hauteur (celle de FL est déjà dans le rendu),
  et pas de reverb ni de delay supplémentaire sur une voix dont la chaîne FL en a déjà.
- **Master de FL — décision (révisée) : Eden fait le mastering.** Les pistes sont
  récupérées avant le Master (effets du Master contournés dans les copies) ; Eden mixe puis
  masterise lui-même (graves, bus, clip doux, limiteur true-peak, volume cible rap
  commercial). Les effets de ton Master FL servent à ton écoute dans FL Studio, pas au
  fichier final. La réinjection du mix dans le Master FL (première version) a été retirée.
- **Voix sèche** : pour une voix dont la chaîne contient une reverb ou un delay que FL joue
  vraiment (slot actif avec un dry/wet qui n'est pas à 0, insert et ses effets actifs,
  volume de l'insert au-dessus de zéro, insert qui atteint le Master), une copie est rendue
  avec ces effets contournés (slot désactivé dans les paramètres du Mixer, retours d'effets
  coupés). La différence voix complète − voix sèche est exactement ce que tes effets
  ajoutent : Eden traite la voix sèche et remet tes effets par-dessus. Avant de s'en servir,
  Eden vérifie que FL en a bien retiré quelque chose et qu'elle est calée sur la voix
  complète ; sinon la voix est traitée avec prudence (détails dans `docs/mixage.md`).

---

## 4. Architectures étudiées

| Option | Pour | Contre | Verdict |
|---|---|---|---|
| **1. Python (application + analyse + DSP numpy/scipy), C++ plus tard si nécessaire** | Développement rapide, excellent écosystème audio/analyse, tests faciles, Windows OK | Les traitements « échantillon par échantillon » (compresseur, de-esser) sont lents en Python pur → numba ou module C++ ciblé | **Retenue** |
| 2. Tout en C++/JUCE (application + moteur) | Performances, plugins VST3 possibles | Développement bien plus long, analyse/IA plus lourde à intégrer ; licence JUCE (GPL-3 ou commerciale) | Pas pour la v1 |
| 3. Eden comme plugin VST3 dans FL | S'intègre au mixer de FL | Ne peut pas voir tout le projet ni exporter seul ; contraire au souhait « Eden = environnement de mixage séparé » | Rejetée |
| 4. Moteur DSP Spotify `pedalboard` | Effets de qualité prêts, hôte VST3 | Licence **GPL-3.0** (contamine Eden si distribué) | À éviter sauf décision explicite |

**Architecture retenue (évolutive sans réécriture)** :

```
┌──────────────────────────── Eden (Windows, Python) ─────────────────────────────┐
│                                                                                 │
│  Interface (PySide6)  ──►  Orchestrateur de session (étapes, progression réelle, │
│        ▲                   reprise, historique des versions)                    │
│        │                          │                                             │
│        │      ┌───────────────────┼─────────────────────────┐                   │
│        │      ▼                   ▼                         ▼                   │
│        │  Inspection .flp     Acquisition des stems     Moteur de mixage        │
│        │  (lecture seule)     - rendu FL (CLI/guidé)    - analyse (LUFS, spectre,│
│        │  - parseur Eden      - vérification + null test   sifflantes, masquage) │
│        │  - sources audio     - passerelle script FL     - décisions (règles     │
│        │  - routage/effets      (optionnelle)              explicites + scores)  │
│        │  - rôles des pistes                             - DSP (EQ, comp, de-ess,│
│        │                                                   satur., reverb/delay) │
│        │                                                 - finition + export WAV │
│        │                                                          │              │
│        └──────────── Espace de travail Eden (%LOCALAPPDATA%\Eden) ◄┘              │
│                      rapports, sons rendus par FL, versions de mix, réglages     │
└─────────────────────────────────────────────────────────────────────────────────┘
          ▲ lecture seule                         ▲ rendu / script
          │                                       │
     projet.flp + WAV                       FL Studio (ton PC)
```

### Rôle de l'IA

- Le traitement audio est fait par du DSP déterministe et testé.
- Les décisions combinent : mesures objectives (LUFS, crêtes, bandes de fréquences,
  énergie des sifflantes, masquage voix/instru), règles explicites lisibles, et
  comparaison de plusieurs réglages candidats par des métriques.
- Un modèle de langage peut ensuite **expliquer** et **proposer** à partir de ces mesures,
  mais il n'« entend » pas le son : aucune décision ne repose sur lui seul.
- Amélioration progressive : banc de tests de non-régression (morceaux de référence,
  métriques attendues), et historique de tes corrections pour ajuster les règles.

---

## 5. Structure du dépôt

```
Eden/
├── src/eden/
│   ├── flp/            lecteur du format .flp (événements, identifiants, parseur)
│   ├── project/        modèle, sources audio, catégories de plugins, rôles, inspection,
│   │                   projets du dossier choisi (accueil)
│   ├── gui/            interface PySide6
│   ├── safety.py       protection du projet original, espace de travail
│   ├── report.py       rapport lisible en français
│   ├── updater.py      mises à jour automatiques
│   └── cli.py          ligne de commande (eden inspect / gui / update)
├── tests/              tests automatisés (pytest)
├── tools/              scripts de développement
├── docs/               cette documentation
└── .github/workflows/  tests automatiques Windows + Linux
```

Prévu ensuite : `src/eden/render/` (phase 3), `src/eden/engine/` (analyse, DSP,
décisions — phase 4), `src/eden/session/` (historique, versions, reprise), `fl_script/`
(passerelle installée dans FL Studio).

---

## 6. Dépendances, licences, coûts

| Dépendance | Usage | Licence | Coût |
|---|---|---|---|
| Python 3.11+ | langage | PSF | gratuit |
| numpy | calcul | BSD | gratuit |
| scipy | filtres, rééchantillonnage | BSD | gratuit |
| soundfile (libsndfile) | lecture/écriture WAV/FLAC/AIFF | BSD / LGPL-2.1 | gratuit |
| packaging | comparaison de versions (mises à jour) | BSD/Apache | gratuit |
| PySide6-Essentials (Qt) | interface | LGPL-3.0 (utilisable dans une appli fermée en liaison dynamique) | gratuit |
| PySide6-Addons (Qt) | Qt Quick 3D (le jardin), Qt Multimedia (l'écoute avant / après, avec FFmpeg compilé en LGPL-2.1) | LGPL-3.0 | gratuit |
| pytest | tests (dev) | MIT | gratuit |
| PyInstaller + Inno Setup | installateur Windows (seulement pour le construire) | GPL avec exception / licence Inno Setup (libre) | gratuit |
| _Option_ : certificat de signature de code | éviter l'alerte SmartScreen | — | ~100–400 €/an |
| _Option_ : moteur de correction de hauteur | voir §7 | variable | variable |

PySide6 6.12.0 libère une référence de trop à `True` à chaque signal émis : avant Python 3.12
(où `True` peut être libéré), Eden s'arrête après quelques milliers de signaux (« bool_dealloc »).
Sous Python 3.11, cette version est donc exclue (`pyproject.toml`) ; dès Python 3.12, `True` est
immortel et l'erreur sans effet : l'installateur, construit avec Python 3.12, n'est pas concerné.

Évités pour l'instant à cause de leur licence : PyFLP (GPL-3), pedalboard (GPL-3),
essentia (AGPL-3), Rubber Band (GPL ou licence commerciale payante).

---

## 7. Correction de hauteur (Auto-Tune)

- La plupart des rappeurs ont déjà leur correcteur dans la chaîne FL (Auto-Tune, Waves
  Tune, Pitcher, Graillon, NewTone…). Eden le **détecte déjà** (catégorie « Correction de
  hauteur ») et ne le dupliquera pas : il est inclus dans le rendu FL.
- Pour proposer des réglages : estimation de la tonalité (profils de Krumhansl sur le
  chroma de l'instru) avec un **indice de confiance**, et détection de hauteur de la voix
  (pYIN). Une tonalité estimée n'est qu'une proposition, modifiable par l'utilisateur.
- Pour appliquer une correction **dans Eden** : pas de faux Auto-Tune. Options à évaluer
  en phase 4b : héberger ton propre plugin VST3 de correction (licence que tu possèdes
  déjà), ou un moteur open source de qualité suffisante (tests d'écoute obligatoires).

---

## 8. Risques techniques

| Risque | Impact | Mitigation |
|---|---|---|
| Format .flp non documenté, change selon les versions (FL 21, 2024, 2025) | informations manquantes ou mal lues | événements inconnus comptés et signalés ; tests sur tes vrais projets ; jamais d'écriture du .flp |
| Rendu automatique par ligne de commande non disponible / incomplet | rendu manuel nécessaire | mode d'export guidé + vérification automatique des fichiers |
| Stems qui ne se resomment pas exactement (bus, sidechain, effets aléatoires, envois parallèles) | son différent de l'original | null test obligatoire, analyse du graphe de routage, rapport clair |
| Effets temporels coupés en fin de clip (reverb/delay) | queues tronquées | rendu FL avec queues (option « leave remainder »), vérification de la fin |
| Mauvaise identification des voix | mauvais traitement | rôles avec raisons et confiance ; pas encore de correction manuelle : renommer la piste dans FL Studio puis relancer l'analyse |
| Qualité du DSP « maison » | son moins bon qu'avec des plugins pros | métriques + écoutes comparatives, bascule vers un module C++ si nécessaire |
| Performances Python sur des titres longs | lenteur | numpy vectorisé, numba, C++ ciblé |
| Mises à jour depuis un dépôt privé | l'application ne peut pas télécharger les versions | dépôt public de releases ou jeton (voir `mises-a-jour.md`) |

---

## 9. Réalisable directement / solution alternative

**Directement** : lecture de la structure du projet, des routages et des effets
présents ; localisation et lecture des fichiers audio ; identification des voix ; analyse
du signal ; moteur de mixage voix + instru ; finition ; export WAV (dossier, nom, fréquence,
profondeur de bits) ; historique et versions ; interface Windows ; mises à jour automatiques.

**Avec une solution alternative** :
- son exact du projet → rendu par FL Studio (guidé, automatique si la ligne de commande
  le permet) ;
- réglages internes des plugins → passerelle de script dans FL Studio (optionnelle) ;
- correction de hauteur appliquée par Eden → hébergement d'un plugin existant ou moteur à
  évaluer ; en attendant, celle de ton projet FL est conservée ;
- stems séparés d'une instru livrée en un seul fichier stéréo → non récupérables
  proprement ; Eden travaille alors l'instru comme un bloc (EQ dynamique/ducking ciblé
  pour laisser la place à la voix), et le signale.
