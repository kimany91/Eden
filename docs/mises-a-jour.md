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
- **Pas encore testé en réel** : il n'existe pas encore d'installateur Windows ni de
  release publiée. Ils seront produits en phase 5 (PyInstaller + Inno Setup + workflow
  GitHub Actions qui publie l'installateur et `SHA256SUMS.txt` à chaque tag `v*`).

## Décision nécessaire : dépôt privé

L'API GitHub ne montre pas les releases d'un dépôt privé sans jeton d'accès, et mettre un
jeton dans l'application l'exposerait. Options :

1. **Dépôt public séparé** `eden-releases` ne contenant que les installateurs (le code
   reste privé) — recommandé ;
2. rendre le dépôt `eden` public ;
3. garder un jeton personnel en lecture seule sur ton PC uniquement (`eden update --token`),
   acceptable pour un usage strictement personnel.

## Sécurité, étape suivante

La somme SHA-256 protège contre un téléchargement corrompu, pas contre un compte GitHub
compromis. Étape suivante prévue : signature des versions (clé Ed25519 dont la clé
publique est intégrée à Eden), et éventuellement signature de code Windows (payante).
