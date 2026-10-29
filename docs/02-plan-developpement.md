# Eden — Plan de développement

Chaque phase se termine par des critères **vérifiables**. Une phase n'est déclarée
terminée que lorsque ses critères sont remplis et testés.

## Phase 1 — Audit et conception ✅

Livrable : `docs/01-audit-architecture.md`.

## Phase 2 — Prototype d'inspection en lecture seule ✅ (sur projets de test) / ⏳ (sur tes projets)

Fait :
- lecteur `.flp` propre à Eden (canaux, Mixer, routages, slots, VST, playlist, patterns,
  marqueurs, tempo) ;
- localisation des fichiers audio (chemins absolus, `%FLStudio…%`, projet déplacé) et
  lecture de leurs caractéristiques (fréquence, canaux, durée, format) ;
- chemin du signal de chaque source jusqu'au Master et inventaire des effets existants
  par catégorie ;
- identification des rôles (voix lead, doublage, backs, ad-libs, instru, batterie, 808…)
  avec raisons et niveau de confiance ;
- sécurité : lecture seule, empreinte SHA-256 vérifiée avant/après, aucun fichier écrit
  dans le dossier du projet ;
- rapport Markdown (français) et JSON ; ligne de commande ; interface PySide6 avec
  progression réelle et erreurs indiquant l'étape ;
- mises à jour automatiques (vérification, téléchargement, contrôle SHA-256, installation
  à la fermeture) ;
- 66 tests automatisés (dont un vrai projet FL Studio 20.8).

Critères restant à valider **avec toi** :
- [ ] `eden inspect` sur au moins 3 de tes projets (FL 21/2024/2025) sans erreur ;
- [ ] voix lead / backs / ad-libs correctement reconnus ou corrigeables ;
- [ ] liste des événements inconnus revue pour ta version de FL.

## Phase 3 — Pilotage de FL Studio et récupération du son ✅ (simulateur) / ⏳ (ton PC)

Principe retenu : **Eden pilote FL Studio lui-même**, aucun export manuel.

Fait :
- écriture de **copies temporaires** du `.flp`, effacées dès que FL les a rendues
  (re-sérialisation identique à l'octet près,
  vérifiée sur le vrai projet FL 20.8) avec les seules modifications nécessaires : couper
  un insert, un canal ou un envoi, contourner les effets du Master, réparer un chemin audio ;
- **plan de rendu** calculé depuis le graphe du Mixer : projet complet, référence
  pré-Master, un rendu par groupe qui sort au Master (envois parasites coupés pour ne
  rien compter deux fois), un rendu par voix avec toute sa chaîne d'effets ;
- lancement de FL Studio en ligne de commande sur chaque copie, délai maximum, détection
  du fichier produit, vérifications (format, crête, silence, écrêtage, fin d'écho ou de
  reverb coupée) ;
- **test de reconstruction** : somme des groupes = rendu pré-Master (seuil −60 dB) ;
- reprise après interruption (manifeste, rendus déjà faits réutilisés) ;
- `eden fl-probe` : sur ton PC, essaie les syntaxes connues de FL Studio, puis vérifie que
  couper un canal, un insert et un envoi donne bien du silence, et qu'un slot d'effet
  désactivé l'est vraiment : une piste rendue seule avec et sans une de ses reverbs ou un de
  ses delays (dont FL a enregistré l'état activé/désactivé), l'écart entre les deux rendus
  doit dépasser −60 dB. Un slot peut ne rien changer pour une raison qui lui est propre
  (plugin réglé pour laisser passer le son, fader du retour en bas) : jusqu'à deux autres
  slots sont alors essayés, de préférence sur un autre insert, et avec une autre piste quand
  il y en a une (le même slot n'est repris avec une autre piste que s'il n'en reste aucun
  autre ; 3 essais au plus, choix d'Eden), chaque essai noté dans le compte rendu, et le
  test n'échoue que si aucun ne change le rendu ; sans reverb ni delay de ce genre dans le
  projet, ou si tous les rendus essayés sont muets, il est noté « non vérifié ». La syntaxe
  qui marche n'est enregistrée que si tout ce qui a pu être vérifié passe ;
- `eden render` et bouton « Récupérer le son depuis FL Studio » ;
- tests avec un simulateur de FL Studio (effets non linéaires sur bus et Master), y compris
  la détection d'un découpage faux.

Critères restant à valider **avec ton FL Studio** :
- [ ] `eden fl-probe` réussit (sinon, son compte rendu dit exactement ce qui bloque) ;
- [ ] sur 3 projets réels, test de reconstruction < −60 dB, durées identiques ;
- [ ] aucune fenêtre bloquante de FL pendant les rendus (plugins manquants, etc.).

Rendu « voix sèche » : pour chaque voix dont la chaîne FL contient une reverb ou un delay
que FL joue vraiment (slot actif avec un dry/wet qui n'est pas à 0, insert et ses effets
actifs, insert qui atteint le Master), une copie supplémentaire est rendue avec ces effets
contournés (slots désactivés sur le chemin de la voix, retours d'effets coupés) ; voix
complète − voix sèche = exactement ce que tes effets ajoutent.

Mastering : c'est Eden qui le fait (décision : « Eden fait tout le mastering »). Les
effets de ton Master FL ne servent qu'à ton écoute dans FL Studio.

Ensuite : passerelle de script FL optionnelle pour lire les réglages des plugins.

## Phase 4 — Mixage et mastering Eden ✅ (voix de test, simulateur) / ⏳ (écoute)

Fait (détails, seuils et sources : `docs/mixage.md`) :
- mesures normalisées : volume intégré, court terme, plage de volume (ITU-R BS.1770 /
  EBU R128, coefficients exacts), crête réelle à 8× et lue comme un mesureur courant
  (libebur128) ;
- analyse du morceau : accordage de l'instru, tonalité (profils Krumhansl-Kessler, Shaath et
  edma, 808 pour départager les relatives), tempo du projet et pulsation ressentie, notes du 808 et accord avec la
  gamme, collisions kick / 808, stéréo des graves ;
- chaîne vocale complète par rôle, dans l'ordre des chaînes pro documentées, chaque étape
  déclenchée par une mesure et plafonnée ;
- voix sèche quand FL joue vraiment une reverb ou un delay sur la chaîne de la voix : un
  effet désactivé ou inaudible (mix à 0 %, insert coupé, volume de l'insert à zéro, insert
  sans sortie vers le Master) ne compte pas, et l'inspection dit lequel des deux il est ; un
  plugin non identifié compte comme reverb ou delay quand il est sur un autre insert que
  celui de la voix et que le nom de cet insert contient « verb », « delay », « echo »,
  « écho » ou « space » (choix d'Eden) ; un retour d'effet est reconnu par la topologie du
  Mixer, pas par son numéro. La voix sèche rendue par FL n'est gardée que si elle passe le
  contrôle : pas muette, FL en a retiré quelque chose (pendant le chant, part des effets
  au-dessus de −60 dB sous la voix), calée sur la voix complète à 2 échantillons près, part
  des effets sans copie de la voix et pas plus forte qu'elle. Eden traite alors la voix
  sèche et remet tes effets tels quels ; sinon (état d'un slot non enregistré par FL,
  retours impossibles à distinguer, plugin non identifié sur le chemin de la voix, voix
  sèche écartée) la voix est traitée en compression « prudente » ;
- niveaux (voix principale au-dessus de l'instru pendant le chant, autres voix par rapport
  à elle), suivi phrase par phrase, espace en quatre envois pour les voix qui n'en ont pas,
  placement stéréo, place pour les paroles (bandes pondérées par leur importance pour
  l'intelligibilité), kick / 808, harmoniques du 808 pour petites enceintes ;
- mastering Eden : graves en mono, tenue des graves, compression de bus, clip doux puis
  limiteur true-peak, volume cible rap commercial, simulation de la lecture sur chaque
  plateforme ;
- versions conservées, export WAV (dossier, nom, fréquence, 16/24/32 bits) ;
- page « Mixage Eden » dans l'interface, commande `eden mix`.

Critères validés : à 0 %, résultat identique au morceau d'origine (écart < −100 dB) ;
voix propre : seulement les étapes de forme, volume rendu par le gain de compensation ;
chaque défaut de test corrigé et mesurablement réduit ; plafond de crête tenu pour les deux
lectures ; conversion à l'export sans repliement ni crête remontée ; aucun export écrêté en
16/24 bits.

Reste à valider **avec toi** : écoute sur 3 morceaux, ajustement des seuils.

Phase 4b : lecteur A/B intégré, courbe d'équilibre tonal de référence (corpus de masters
rap), séparation kick / 808 quand l'instru est un seul fichier stéréo, suppression
dynamique des résonances (détecteur tenant compte des harmoniques, à valider sur de vraies
voix).

## Phase 5 — Interface et installateur ✅ (base) / ⏳ (compléments)

Fait : interface Qt Quick animée (ouverture avec l'arbre qui se construit, étapes,
glisser-déposer, progression réelle) ; logo ; installateur Windows (Inno Setup, sans droits
administrateur, raccourcis) construit et testé automatiquement sur Windows à chaque envoi ;
publication automatique des versions sur tag `v*`, utilisée par les mises à jour.

Fait aussi : page de mixage (intensité, décisions, versions, export).

Reste : lecteur audio A/B (original / Eden, à niveau égal), réglage d'intensité par
traitement.

## Phase 6 — Tests et amélioration

Plusieurs morceaux et prises de voix ; cas d'erreur (projets incomplets, plugins absents,
fichiers manquants, interruption pendant un rendu — reprise) ; ajustement des règles à
partir de tes corrections.
