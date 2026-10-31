Eden 1.5.0 : mix et master analysés élément par élément et recorrigés — master au ressenti, voix ni écrasées ni inversées, fini le son crunchy.

## Installation

1. Télécharge `Eden-Setup-1.5.0.exe` ci-dessous et double-clique dessus (pas besoin de droits
   administrateur ni de Python). Si une version précédente d'Eden est installée, la mise à jour se fait aussi
   toute seule à sa fermeture.
2. L'installateur n'est pas signé : si Windows affiche « Windows a protégé votre ordinateur »,
   clique sur « Informations complémentaires » puis « Exécuter quand même ».

## Refait dans 1.5.0 (tout le mix et le master ré-analysés, chaque problème trouvé refait)

Tes quatre retours (voix crunchy/robotique qui sature, « bas devient super fort et fort devient
super bas », mastering qui abuse, voix basse remontée jusqu'à saturer), chacun remonté à sa cause :

- **Le master vise maintenant le ressenti, pas la moyenne.** Il règle le volume sur ce que
  **tiennent les passages forts** du morceau (le 95ᵉ centile du volume court terme), plus sur la
  moyenne : visée sur la moyenne, un couplet calme la tirait vers le bas, le gain surcompensait —
  le refrain saturait et les passages calmes sortaient trop fort. C'est la cause principale du
  « quand le son est bas il le met super fort, quand il est fort il le met super bas ».
- **Un mastering moins abusé.** L'écrêtage + limiteur ne prennent plus que **6 dB** sur les crêtes
  qui reviennent (au lieu de 9 : les refrains sortaient écrasés) ; une fois cette limite touchée,
  le master reste un peu moins fort et te le dit, au lieu de revenir se garer sur la limite. Le
  clip doux passe sous le plafond du limiteur (avant, les deux étages travaillaient en permanence,
  l'un par-dessus l'autre) et son genou est resserré : le haut du mix ne vit plus en permanence
  dans la distorsion. Le limiteur anticipe sur 5 ms et relâche sur 250 ms : plus de pompage entre
  deux kicks.
- **Fini le son crunchy / robotique.** Le détecteur des de-essers lisait le signal sur des trames
  de 1 ms : son gain ondulait au rythme de la hauteur de ta voix — une modulation métallique,
  « crunchy ». Il est maintenant lissé (5 ms) avec une attaque de 3 ms.
- **Une voix basse de base n'est plus remontée jusqu'à saturer.** Quand toutes tes prises sont
  enregistrées à travers ta chaîne FL (Auto-Tune, reverb imprimés), leurs niveaux sont ceux que tu
  as validés : le réglage statique est borné à ±4 dB (au lieu de 10) et le suivi phrase par phrase
  est coupé — tes variations de jeu ne sont plus « corrigées ». Si un écart reste, Eden te le dit
  au lieu de forcer.
- **Et trois causes de crêtes en trop retirées** : une voix posée d'un côté ne sort plus +3 dB
  au-dessus de sa prise (compensation de panoramique plafonnée) ; un mix sorti plus bas n'est plus
  remonté avant le master (les crêtes de l'instru entraient plus fort que FL ne les a jamais
  jouées) ; le gain de compensation ne rend plus que ce que compresseurs et de-essers ont pris —
  il ne remonte plus les respirations ni ce que les filtres ont retiré.
- **Eden voit toujours tes plugins FL** (reverb, delay sur tes pistes et leurs envois) et n'ajoute
  jamais d'espace par-dessus le tien ; en plus, il **écoute** chaque prise : une queue de reverb
  qui sonne après tes fins de phrases suffit à la classer « produite », même si le plugin n'est
  pas reconnu — détection affinée dans cette version (seuil −48 dB, deux fins de phrases au
  moins).

## Refondu dans 1.4.0 (retours d'écoute : voix robotique, toujours trop fort par moments)

- **Le « fantôme » est retiré du mix.** Eden reconstruisait ton morceau comme voix + instru +
  « reste » (ton morceau moins toutes les pistes). Comme FL Studio ne rend pas deux fois
  exactement pareil sur ton PC, ce « reste » n'était pas une vraie piste : c'était un fantôme de
  toutes tes voix, légèrement différent. Dès qu'Eden bougeait le volume d'une voix, elle battait
  contre son fantôme : son **robotique**, « **sous l'eau** », et des moments où les deux
  s'additionnent — **trop fort d'un coup**. Désormais, si la somme des pistes ne redonne pas ton
  morceau à l'identique, ce reste est retiré et le morceau est reconstruit uniquement à partir
  des vraies pistes.
- **Ta prise produite n'est plus refaçonnée.** Tes prises sont enregistrées à travers ta chaîne
  FL (Auto-Tune…) : leur son est fini. Eden ne leur applique plus que deux choses — respirations
  baissées, et un de-esser si les « s » dépassent. Plus de compression, plus de saturation, plus
  d'EQ correctif sur une voix déjà produite : saturer une voix autotunée, c'est le son métallique
  que tu entendais.

## Corrigé dans 1.3.2 (retours d'écoute : les voix doivent être reliées ensemble)

- **Une voix n'est plus jamais montée par rapport aux autres.** Eden remontait un chœur ou un
  ad-lib que tu avais posé discret vers sa « cible » : l'empilement sortait du mix et saturait.
  Maintenant, toutes les voix suivent le même gain que les voix principales, rien de plus. Une
  voix qui couvre la voix principale est encore baissée (borné), et une voix très en retrait est
  seulement signalée : la décision de la monter t'appartient.
- **Un seul réglage de niveau pour toute la performance**, mesuré sur tes voix principales
  réunies contre l'instru : un couplet calme et un refrain plein gardent l'écart que tu leur as
  donné (avant, chaque section était ramenée vers la même cible : « le son monte énormément
  quand c'est bas »).
- **Le creux de présence sur les doublures est supprimé.** Il baissait les doublures de 2 dB
  entre 1 et 4 kHz à chaque fois que le lead chantait : le son de l'empilement changeait à
  chaque entrée de voix (« effet bizarre, comme sous l'eau »).

## Corrigé dans 1.3.1 (retours d'écoute : volume inconstant, doublures qui saturent, master qui bouge)

- **Un seul gain pour toutes les voix.** Le suivi phrase par phrase réglait chaque groupe de voix
  de son côté : deux prises d'un même refrain dérivaient l'une de l'autre, leur somme sortait du
  mix ou saturait, et la voix passait tantôt sous l'instru, tantôt dessus. Le suivi est maintenant
  lu sur les voix principales réunies, et **toutes** les voix (doublures, chœurs, ad-libs) suivent
  ce même gain : l'équilibre que tu as réglé entre elles ne bouge plus.
- **Rapper doucement reste doux.** Une phrase que tu as baissée de 6 dB ou plus est un choix de
  jeu : Eden ne la remonte plus jamais. Et le suivi est borné à ±3 dB (au lieu de ±4).
- **L'instru ne clignote plus.** Le creux qui fait de la place aux paroles s'ouvrait en 15 ms et
  se refermait en 200 ms : à chaque phrase, le grave et l'aigu de l'instru bougeaient — « le
  master change toutes les 5 secondes ». Il s'ouvre maintenant en ~120 ms et se referme en
  ~900 ms : plus de pompage audible.

## Corrigé dans 1.3.0 (retours d'écoute d'un utilisateur)

- **Les respirations étaient très fortes** : rien ne les baissait, et la compression puis le gain
  de compensation les remontaient (mesuré : +2,5 dB sur une voix de test). Eden fait maintenant ce
  que font Waves DeBreath et iZotope Breath Control : il détecte les respirations (du souffle non
  voisé entre les phrases, plus faible que le chant) et les ramène à 22 dB sous la voix **avant**
  toute compression. Les plus douces ne bougent pas, le chant non plus.
- **La voix montait et baissait au hasard** : le suivi de niveau prenait une respiration isolée
  pour une « phrase » trop faible et pouvait la monter de 6 dB. Les phrases sont maintenant lues
  sur la bande des voyelles (une respiration n'y passe pas pour une phrase), une « phrase » à plus
  de 10 dB sous les autres n'est pas touchée, et chaque mouvement doit avoir sa cause mesurée :
  la voix n'est montée que de ce dont elle a baissé plus ce dont l'instru a monté, ±4 dB au plus
  (au lieu de ±6).
- **Beaucoup trop d'écho, voix « sous l'eau »** : Eden ajoutait son espace complet à chaque groupe
  de voix, avec un jet d'écho sur chaque fin de phrase. Tous les retours baissent de 4 dB, le jet
  d'écho passe à −16 dB et ne part que sur une fin de phrase suivie d'un vrai silence, le plafond
  de reverb du morceau descend de −16 à −19 LU. Et si tes prises portent déjà une reverb
  enregistrée dedans (FL enregistre la piste du Mixer avec ses effets), Eden le détecte à
  l'écoute et n'ajoute **rien** par-dessus.
- **« La somme des pistes diffère » sans cause visible** : quand la vérification échoue, Eden rend
  ton morceau une 2e fois. Si FL Studio ne rend pas deux fois pareil (un plugin à modulation
  aléatoire, une version d'essai), c'est sa variation : la vérification passe et le dit. Si FL
  rend deux fois pareil, l'écart vient d'un effet que l'instru et les voix traversent ensemble,
  et Eden le dit.

## Corrigé dans 1.2.10

- **Eden pouvait se fermer d'un coup entre deux étapes** (analyse → son de FL Studio → mixage) :
  l'étape suivante démarrait pendant que celle d'avant finissait, et Windows arrêtait Eden quand
  le travail de l'étape d'avant était effacé trop tôt. Chaque étape est maintenant gardée jusqu'à
  sa vraie fin.

## Nouveau dans 1.2.9

- **L'arbre pousse de tous les côtés** : les branches partent du tronc par trois, tout autour, et
  s'allongent lentement ensemble ; la couronne s'étend partout à la fois, plus une branche seule
  d'un côté.
- **Tu le vois grandir** : à chaque avancée du travail, l'arbre grandit en douceur jusqu'au
  nouveau pourcentage (il démarre, accélère, ralentit), au lieu de sauter à l'étape suivante. Le
  pourcentage affiché suit exactement l'arbre. Pendant que FL Studio rend tes pistes (il ne dit
  rien tant qu'une piste n'est pas finie), l'arbre continue de pousser doucement.
- **La caméra glisse** : quand l'arbre grandit, elle recule et remonte en douceur pour le cadrer,
  sans saut d'image ; le zoom à la molette est doux aussi.

## Corrigé dans 1.2.8

- **Des prises de voix prises pour des instrus** : l'écoute de la 1.2.7 était trop stricte pour
  de vraies prises. Une voix grave près du micro a de l'énergie vers 70-90 Hz, et le beat du
  casque qui fuit dans le micro faisait croire que le son ne s'arrêtait jamais. Eden regarde
  maintenant sous 60 Hz (le kick et le 808, pas une voix), ignore ce qui est 20 dB sous la voix,
  et compte comme mono une prise faite sur un seul côté. Une prise enregistrée dans FL (son nom
  porte la date et l'heure, ou elle est dans le dossier des enregistrements) reste une voix, sauf
  si elle n'est presque que des basses.
- **« La somme des pistes diffère » avec tes pistes VOICE et AUTOTUNE** : ces prises passent par
  les mêmes effets du Mixer (Auto-Tune…). Rendues à part, elles ne redonnaient pas le morceau ;
  reconnues comme des voix, elles sont rendues toutes ensemble.
- **Plus bloqué** : si la vérification échoue quand même, le bouton « Mixer quand même » apparaît.
  Ce qu'Eden n'a pas pu séparer reste tel quel (à 0 % tu retrouves ton mix) ; écoute l'avant / après.
- **Fausse alerte « Leave remainder »** : quand c'est ton instru qui joue jusqu'à la toute fin du
  morceau, le son présent à la fin est le sien, pas un écho coupé : plus d'alerte pour ça.

## Nouveau dans 1.2.7

- **Les noms de tes pistes ne comptent plus pour savoir si c'est une voix** : chacun nomme ses
  pistes à sa façon. Eden écoute chaque fichier : une voix enregistrée au micro est mono (ou ses
  deux côtés sont pareils), n'a presque rien sous 90 Hz (ni kick ni 808) et s'arrête entre ses
  phrases ; un instrument a des basses, ou est stéréo et ne s'arrête jamais. Le nom ne sert plus
  qu'à dire quelle voix (lead, ad-lib…) ou quel instrument, quand il le dit.
- **Le rôle des voix aux noms quelconques** vient de leur place dans le morceau : une prise
  qu'aucune autre voix ne recouvre est la voix principale (les prises du lead se suivent) ; une
  prise posée sur une autre voix est des ad-libs si elle parle peu, des backs si elle est pleine.
- Plus de message te demandant de renommer tes pistes.

## Corrigé dans 1.2.6

- **Tes prises de voix étaient prises pour des instrus** : FL nomme une prise d'après le projet,
  la date et l'entrée (« lucki type beat - 'casino'_2026-10-25 15-45-47_VOICE ») ; le « beat »
  du nom du projet l'emportait. Le début du nom (le projet) ne compte plus, la fin (« VOICE »)
  oui, et une prise enregistrée compte comme une voix.
- **« La somme des pistes diffère du mix d'origine » avec un export WAV en 16 bits** : sans le
  limiteur du Master, ton morceau dépasse le maximum et FL le coupe là, pas ses pistes. Quand
  les pistes redonnent le morceau partout ailleurs, Eden prend leur somme (qui ne sature pas)
  et continue. Sinon, le message dit toujours à quoi ressemble l'écart et où il est.

## Corrigé dans 1.2.5

- **Ça prenait des heures** : en 1.2.4, un seul FL Studio rendait toutes les copies d'un coup ;
  avec FL Studio 2026, Eden finissait par attendre son délai de sécurité. Maintenant, **autant
  de FL Studio en même temps que ton PC en a la place** (un pour 2 cœurs logiques et pour 1,5 Go
  de mémoire libre, en laissant 2 Go au reste, 8 au plus), chacun sur une copie, toujours en
  priorité basse. Un FL qui reste ouvert une fois son fichier écrit est fermé par Eden.
- **« La somme des pistes diffère du mix d'origine »** : les voix jouées directement dans le
  Master sont maintenant vérifiées ensemble (si elles passent dans les mêmes effets, un
  Auto-Tune ou un compresseur, rendues une par une elles ne redonnaient pas le morceau), et
  les canaux que la playlist ne fait pas jouer ont un rendu de contrôle. Si la vérification
  échoue encore, Eden dit à quoi ressemble l'écart, où il est le plus fort, et si ton export
  WAV en 16 bits sature.

## Nouveau dans 1.2.4

- **Une piste du Mixer = un seul rendu** : tous les fichiers d'une même piste (les couplets du
  lead, les ad-libs…) sont rendus ensemble, prod et reste coupés, au lieu d'un rendu par
  fichier. Ils passent dans les effets de la piste comme dans le morceau, et Eden les mixe
  comme une piste. Des fichiers de rôles différents sur une même piste (lead et ad-libs) sont
  rendus à part, parce qu'Eden ne les traite pas pareil.
- FL Studio ne s'ouvrait qu'une fois pour tous les rendus (retiré en 1.2.5).
- **Le PC ne rame pas** : FL Studio tourne en priorité basse, ce que tu fais sur le PC passe
  avant.
- Chaque rendu terminé apparaît tout de suite dans la liste.

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
[docs/mixage.md](https://github.com/kimany91/Eden/blob/v1.2.11/docs/mixage.md).
