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

## Phase 3 — Rendu et récupération des sources

1. **Spike sur ton PC** (½ journée) : tester le rendu en ligne de commande de ta version
   de FL Studio (master, puis stems par insert) ; tester un script de passerelle dans FL.
2. Module `render/` : rendu automatique si possible, sinon export guidé (Eden affiche les
   réglages exacts et surveille le dossier).
3. Vérifications automatiques des stems : même fréquence d'échantillonnage, même longueur,
   alignement à l'échantillon, absence d'écrêtage, **null test** somme des stems vs master.
4. Choix des stems à partir du graphe de routage (pas de double comptage des bus).
5. Passerelle FL optionnelle : export des paramètres des plugins de la chaîne vocale.

Critères : sur 3 projets réels, somme des stems = master à < −60 dB d'écart (ou écart
expliqué) ; durée et synchronisation identiques ; aucun fichier du projet modifié.

## Phase 4 — Premier moteur de mixage

Chaîne simple et contrôlable, appliquée seulement si l'analyse la justifie :
gain d'entrée → EQ correctif (résonances) → compression → de-esser → équilibre
voix/instru → finition (crêtes, true peak) → export WAV (dossier, nom, 44,1/48/96 kHz,
16/24/32 bits flottant).

Chaque module : mesures avant/après, paramètres enregistrés avec la raison de la décision,
tests unitaires sur signaux synthétiques (sinus, bruit rose, sifflantes simulées) et tests
de non-régression sur extraits de référence.

Critères : aucune saturation numérique ; LUFS et crêtes dans les cibles ; mix « intensité
0 % » identique au rendu d'origine ; écoute validée par toi sur 3 morceaux.

Phase 4b : saturation, reverb/delay, gestion fine des backs/ad-libs, automation de volume
vocal, correction de hauteur (cf. audit §7).

## Phase 5 — Interface complète

Lecteur audio avec bascule A/B instantanée (original / Eden, à niveau égal), réglages
d'intensité par module, historique des versions (restaurer, comparer, annuler), export WAV,
installateur Windows (PyInstaller + Inno Setup) et publication automatique des versions.

## Phase 6 — Tests et amélioration

Plusieurs morceaux et prises de voix ; cas d'erreur (projets incomplets, plugins absents,
fichiers manquants, interruption pendant un rendu — reprise) ; ajustement des règles à
partir de tes corrections.
