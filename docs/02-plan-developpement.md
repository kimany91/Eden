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
- sécurité : lecture seule, empreinte SHA-256 vérifiée avant/après, copie du projet dans
  l'espace de travail d'Eden, aucun fichier écrit dans le dossier du projet ;
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
- écriture de **copies de travail** du `.flp` (re-sérialisation identique à l'octet près,
  vérifiée sur le vrai projet FL 20.8) avec les seules modifications nécessaires : couper
  un insert, un canal ou un envoi, contourner les effets du Master, réparer un chemin audio ;
- **plan de rendu** calculé depuis le graphe du Mixer : projet complet, référence
  pré-Master, un rendu par groupe qui sort au Master (envois parasites coupés pour ne
  rien compter deux fois), un rendu par voix avec toute sa chaîne d'effets ;
- lancement de FL Studio en ligne de commande sur chaque copie, délai maximum, détection
  du fichier produit, vérifications (format, crête, silence, écrêtage) ;
- **test de reconstruction** : somme des groupes = rendu pré-Master (seuil −60 dB) ;
- reprise après interruption (manifeste, rendus déjà faits réutilisés) ;
- `eden fl-probe` : sur ton PC, essaie les syntaxes connues de FL Studio, puis vérifie que
  couper un canal, un insert et un envoi donne bien du silence ; enregistre la syntaxe qui
  marche ;
- `eden render` et bouton « Récupérer le son depuis FL Studio » ;
- tests avec un simulateur de FL Studio (effets non linéaires sur bus et Master), y compris
  la détection d'un découpage faux.

Critères restant à valider **avec ton FL Studio** :
- [ ] `eden fl-probe` réussit (sinon, son compte rendu dit exactement ce qui bloque) ;
- [ ] sur 3 projets réels, test de reconstruction < −60 dB, durées identiques ;
- [ ] aucune fenêtre bloquante de FL pendant les rendus (plugins manquants, etc.).

Mastering : il reste dans FL Studio. Le mix d'Eden est réinjecté dans ton Master
(calibration du gain + contrôle « mix d'origine repassé dans le Master = morceau d'origine »,
faits à chaque rendu).

Ensuite : passerelle de script FL optionnelle pour lire les réglages des plugins.

## Phase 4 — Premier moteur de mixage

Chaîne simple et contrôlable, appliquée seulement si l'analyse la justifie :
gain d'entrée → EQ correctif (résonances) → compression → de-esser → équilibre
voix/instru → mix pré-Master (niveau d'entrée du Master conservé, pour que ton mastering FL
réagisse comme avant) → passage dans ton Master FL → export WAV (dossier, nom,
fréquence, profondeur de bits).

Chaque module : mesures avant/après, paramètres enregistrés avec la raison de la décision,
tests unitaires sur signaux synthétiques (sinus, bruit rose, sifflantes simulées) et tests
de non-régression sur extraits de référence.

Critères : aucune saturation numérique ; LUFS et crêtes dans les cibles ; mix « intensité
0 % » identique au rendu d'origine ; écoute validée par toi sur 3 morceaux.

Phase 4b : saturation, reverb/delay, gestion fine des backs/ad-libs, automation de volume
vocal, correction de hauteur (cf. audit §7).

## Phase 5 — Interface et installateur ✅ (base) / ⏳ (compléments)

Fait : interface Qt Quick animée (ouverture avec l'arbre qui se construit, étapes,
glisser-déposer, progression réelle) ; logo ; installateur Windows (Inno Setup, sans droits
administrateur, raccourcis) construit et testé automatiquement sur Windows à chaque envoi ;
publication automatique des versions sur tag `v*`, utilisée par les mises à jour.

Reste : lecteur audio A/B (original / Eden, à niveau égal), réglages d'intensité par
module, historique des versions (restaurer, comparer), écran d'export WAV.

## Phase 6 — Tests et amélioration

Plusieurs morceaux et prises de voix ; cas d'erreur (projets incomplets, plugins absents,
fichiers manquants, interruption pendant un rendu — reprise) ; ajustement des règles à
partir de tes corrections.
