Première version complète d'Eden : il mixe les voix rap de ton projet FL Studio et masterise le
morceau, sans jamais modifier ton projet.

## Installation

1. Télécharge `Eden-Setup-1.0.0.exe` ci-dessous et double-clique dessus (pas besoin de droits
   administrateur ni de Python).
2. L'installateur n'est pas signé : si Windows affiche « Windows a protégé votre ordinateur »,
   clique sur « Informations complémentaires » puis « Exécuter quand même ».
3. Dans Eden, glisse ton `.flp`, puis clique sur « Récupérer le son depuis FL Studio » (FL doit
   être fermé).

Les versions suivantes s'installeront automatiquement à la fermeture d'Eden.

## Ce que fait Eden

- FL Studio joue chaque partie avec tous tes effets ; Eden récupère ce son exact à partir de
  copies temporaires du projet, effacées ensuite.
- Mix : chaîne vocale réglée sur des mesures (coupe-bas, résonances, de-esser, compression,
  saturation, aigus), niveau des voix par rapport à l'instru et entre elles, suivi phrase par
  phrase, place pour les paroles dans l'instru, stéréo des doublages et ad-libs, espace pour
  les voix qui n'en ont pas, 808 et kick.
- Master fort pour les plateformes : −9 LUFS, crête réelle à −3 dBTP (−2 dBTP quand le morceau
  s'arrête plus bas), contrôle de la lecture en mono et de la baisse de volume appliquée par
  chaque plateforme.
- Chaque décision est expliquée ; l'intensité se règle, chaque version est gardée, l'export
  final est un WAV.

## À savoir

Les réglages ont été testés sur des voix et des beats de test et sur de vrais projets FL pour
l'analyse, mais pas encore à l'écoute sur tes morceaux : tes retours décideront des prochains
ajustements. Détails : [docs/mixage.md](https://github.com/kimany91/Eden/blob/v1.0.0/docs/mixage.md).
