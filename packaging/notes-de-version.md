Eden 1.2.3 : marche avec FL Studio 2025 / 2026, et bien plus vite.

## Installation

1. Télécharge `Eden-Setup-1.2.3.exe` ci-dessous et double-clique dessus (pas besoin de droits
   administrateur ni de Python). Si une version précédente d'Eden est installée, la mise à jour se fait aussi
   toute seule à sa fermeture.
2. L'installateur n'est pas signé : si Windows affiche « Windows a protégé votre ordinateur »,
   clique sur « Informations complémentaires » puis « Exécuter quand même ».

## Corrigé dans 1.2.3

- **FL Studio 2025 / 2026** : FL ne rendait plus une copie où Eden avait éteint des pistes du
  Mixer (« FL Studio s'est arrêté sans produire de fichier WAV »). Eden n'éteint plus jamais
  une piste du Mixer : pour jouer une partie seule, il coupe les autres canaux et les envois,
  et contourne les effets du Master un par un.
- **Bien plus rapide** : le test du premier lancement ne fait plus qu'un seul rendu (il en
  faisait jusqu'à une dizaine) ; ce qu'il vérifiait l'est sur chaque morceau par la vérification
  finale (la somme des pistes doit redonner le morceau). Et deux rendus identiques ne lancent
  plus FL Studio deux fois (une voix jouée directement dans le Master et la même voix seule,
  le morceau avant et après le Master quand le Master n'a pas d'effet).

## Corrigé dans 1.2.2

- **FL Studio ne passe plus devant Eden** : il travaille sur un bureau Windows à part, jamais
  affiché ; ni son logo ni sa fenêtre n'apparaissent. S'il pose une question (un plugin
  introuvable…), Eden lit son message, ferme FL et te le montre au lieu d'attendre. Si ton PC
  refuse ce bureau à part, ou si FL n'y rend rien, il est lancé comme avant.
- **Test de FL Studio** : les canaux qui ne jouent nulle part sont aussi coupés pendant le test
  d'isolation et les rendus séparés. Si le test échoue, « Voir le compte rendu » et « Copier le
  compte rendu » apparaissent dans le message d'erreur.

## Corrigé dans 1.2.1

- **Projets FL Studio 2024 / 2025 (et 26)** : Eden ne lisait pas leur playlist (FL a agrandi
  ses clips). Durée inconnue, voix pas reconnues par le nom de leurs pistes, et chaque canal du
  Channel Rack comptait comme une piste du morceau. C'est lu maintenant.
- **Canaux qui ne jouent nulle part** (la batterie d'un modèle de projet, un sample essayé puis
  laissé) : ils sont ignorés, et un de leurs fichiers introuvable n'arrête plus Eden
  (« Fichiers audio introuvables, le rendu serait incomplet »). Un fichier qui manque à une piste
  qui joue arrête toujours Eden, pour ne pas rendre un morceau incomplet.

## Nouveautés de la 1.2

- **Tes projets en un clic** : choisis une seule fois le dossier où tu enregistres tes projets
  FL Studio (celui de FL est proposé s'il existe). Eden s'en souvient et te les montre tous, les
  plus récents en premier, avec une recherche quand il y en a beaucoup. Un clic sur un projet et
  Eden démarre. Les sauvegardes de FL Studio (dossier « Backup ») ne sont pas listées.
- **Les prods déjà faites** : une instru téléchargée d'un seul fichier (sur YouTube par exemple)
  est reconnue comme l'instru complète, quel que soit le titre de la vidéo (« Hats & Percs »,
  « 808 Melody »… ne la font plus passer pour une batterie ou un 808). Elle est déjà mixée et
  masterisée : Eden n'y cherche plus de kick ni de 808, ne retouche pas son mix, lui fait
  seulement de la place pour ta voix pendant que tu rappes, et le master ne l'écrase pas une
  deuxième fois. Avec une instru masterisée peu fort, le morceau peut finir un peu sous
  −9 LUFS : Eden le dit plutôt que d'écraser ses percussions.
- **Plus de fenêtre par-dessus Eden** : plus de fenêtre noire de commande, et FL Studio est lancé
  réduit dans la barre des tâches, sans prendre la main. Si une fenêtre de FL s'ouvre quand même,
  c'est qu'il te demande quelque chose (un plugin introuvable par exemple).

## À savoir

Les réglages du mix ont été testés sur des voix et des beats de test et sur de vrais projets FL
pour l'analyse, pas encore à l'écoute sur tes morceaux. Détails :
[docs/mixage.md](https://github.com/kimany91/Eden/blob/v1.2.3/docs/mixage.md).
