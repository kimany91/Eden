# Mises à jour automatiques d'Eden

## Fonctionnement (implémenté dans `src/eden/updater.py`)

1. Au démarrage de l'interface, en arrière-plan et au plus une fois par 24 h, Eden
   interroge GitHub Releases (`/repos/kimany91/eden/releases/latest`).
2. Si la version publiée est plus récente (les pré-versions sont ignorées), Eden
   télécharge l'installateur Windows `Eden-Setup-<version>.exe` **et** le fichier
   `SHA256SUMS.txt` de la même version.
3. L'installateur est **refusé** si sa somme SHA-256 ne correspond pas, ou si la version
   ne publie pas de `SHA256SUMS.txt`. Rien n'est conservé dans ce cas.
4. Un bandeau indique qu'une mise à jour est prête. Elle est installée **à la fermeture**
   d'Eden (jamais pendant une analyse, un mixage ou un export), en mode silencieux ; la
   nouvelle version est utilisée au lancement suivant.
5. Hors ligne, serveur en erreur, aucune version publiée : Eden continue normalement.

En mode développement (lancé depuis le code source), Eden ne télécharge rien : il
signale la nouvelle version et la mise à jour se fait par `git pull`.

Commande manuelle : `eden update`.

## Ce qui est testé / ce qui reste à faire

- Testé (hors ligne, serveur simulé) : comparaison de versions, lecture de la release,
  téléchargement, refus d'un fichier modifié, refus sans somme de contrôle, limitation à
  une vérification par jour, lancement silencieux de l'installateur.
- Chaque installateur est construit et vérifié sur une machine Windows par le workflow
  « Installateur Windows » (installation silencieuse, raccourcis, démarrage de la version
  installée, désinstallation), qui publie l'installateur et `SHA256SUMS.txt` à chaque tag
  `v*`. Première version publiée : 1.0.0.
- **Pas encore testé en réel** : une mise à jour de bout en bout (une 1.0.0 installée qui
  trouve, vérifie et installe la version suivante) ; elle le sera à la prochaine version.

## Publier une version

1. Mettre la nouvelle version dans `src/eden/__init__.py` (`__version__`) et dans le titre
   « État actuel » du README.
2. Écrire ce qui change dans `packaging/notes-de-version.md` : c'est le texte de la page de
   la version sur GitHub.
3. Pousser le tag `v<version>` (par exemple `v1.0.1`) : le workflow refuse un tag qui ne
   correspond pas à `__version__`, construit et vérifie l'installateur, puis publie la
   version.

## Dépôt public

Le dépôt `kimany91/Eden` est public : l'API GitHub montre ses versions sans jeton, et les
mises à jour fonctionnent sans rien configurer. S'il redevenait privé, l'API ne les
montrerait plus sans jeton d'accès, et mettre un jeton dans l'application l'exposerait :
il faudrait alors publier les installateurs dans un dépôt public séparé, ou garder un
jeton personnel en lecture seule sur ton PC uniquement (`eden update --token`).

## Sécurité, étape suivante

La somme SHA-256 protège contre un téléchargement corrompu, pas contre un compte GitHub
compromis. Étape suivante prévue : signature des versions (clé Ed25519 dont la clé
publique est intégrée à Eden), et éventuellement signature de code Windows (payante).
