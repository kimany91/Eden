# Le mixage et le mastering d'Eden

Eden ne recrée aucun son : il travaille sur ce que **FL Studio** a rendu, avec tous tes
effets, et raisonne comme un ingénieur du son rap — mesures, décisions expliquées, plafonds.
Puis il fait lui-même le **mastering**, fort et propre pour les plateformes.

Les règles viennent d'une recherche sourcée puis vérifiée point par point. Chaque chiffre
est marqué :

- **sourcé** : vérifié sur la source (norme, article, code de référence) ;
- **non vérifié** : vient d'une source réelle mais que la vérification n'a pas pu ouvrir
  (beaucoup de pages *Sound On Sound* et de blogs étaient bloquées) ;
- **choix d'Eden** : valeur de départ raisonnée, à valider à l'écoute.

## Les morceaux du mix

Le morceau est reconstruit comme voix + groupes + « reste du mix » (le morceau moins toutes les
pistes). Le reste n'est gardé que si la somme des pistes redonne le morceau strictement : il
porte alors les vrais bus partagés. Sinon (FL ne rend pas deux fois pareil, ou un effet commun
aux pistes), il n'est qu'un **fantôme de chaque piste** — l'écart entre deux rendus — qui bat
contre les voix dès qu'Eden bouge leur niveau (son métallique ou « sous l'eau », sautes de
volume : retour d'écoute d'un utilisateur) : il est retiré, et le morceau est reconstruit à
partir des pistes elles-mêmes (sauf si des voix y sont restées : elles passent avant).

- **Chaque voix seule**, rendue par FL avec toute sa chaîne (inserts, bus, envois). Une voix,
  ce sont tous les fichiers d'une même piste du Mixer avec le même rôle (les couplets du
  lead, les ad-libs…), rendus ensemble : ils passent dans les effets de la piste comme dans
  le morceau (un compresseur, un Auto-Tune les entend ensemble), et Eden les mixe comme une
  piste, ce que fait un ingénieur. Des fichiers de rôles différents sur une même piste sont
  rendus à part, parce qu'Eden ne les traite pas pareil.
- **Chaque voix sèche** : si sa chaîne FL contient une reverb ou un delay que FL joue
  vraiment (slot actif avec un dry/wet qui n'est pas à 0, insert et ses effets actifs,
  volume de l'insert au-dessus de zéro, insert qui atteint le Master : un retour coupé,
  baissé à zéro ou routé nulle part ne compte pas), FL la rend aussi avec ces effets coupés.
  Un plugin qu'Eden n'identifie pas compte comme reverb ou delay quand il est sur un autre
  insert que celui de la voix et que le nom de cet insert contient « verb », « delay »,
  « echo », « écho » ou « space » (choix d'Eden) ; Eden le signale. Un retour d'effet est
  reconnu par la topologie du Mixer (un insert autre que celui de la voix, qui porte une
  reverb ou un delay, et dont la voix n'a pas besoin pour atteindre le Master) : il est
  coupé en entier, limiteur ou EQ compris. Quand la voix peut se passer de chacun de ces
  inserts mais pas de tous à la fois (un bus voix avec un delay en ligne à côté d'un retour
  de reverb), leur numéro ne compte pas : ceux dont le premier effet (EQ, utilitaires et
  plugins non identifiés mis à part) est la reverb ou le delay sont les retours, les autres
  sont le chemin de la voix, car un bus commence par sa dynamique (choix d'Eden) ; si ça ne
  tranche pas, pas de voix sèche, et Eden dit pourquoi. Sur le chemin propre de la voix, les
  slots de reverb et de delay sont désactivés un par un. *Voix complète − voix sèche* =
  exactement ce que tes effets ajoutent. Eden traite la voix sèche, comme un mixeur qui
  reçoit des pistes sèches et met les effets en envoi, puis remet tes effets **tels quels**
  par-dessus.
- **Contrôle de la voix sèche** : elle ne doit pas être muette, et FL doit en avoir retiré
  quelque chose : pendant le chant, la part des effets doit dépasser −60 dB sous la voix
  (choix d'Eden), sinon les effets coupés n'ont pas été respectés ou ne s'entendaient pas.
  Elle doit aussi être calée sur la voix complète à 2 échantillons près (un plugin contourné
  peut changer la compensation de latence de FL) : le décalage est cherché jusqu'à 100 ms de
  chaque côté (choix d'Eden) ; si le meilleur décalage trouvé dépasse 100 ms, ou s'il
  dépasse 2 échantillons et que la voix sèche n'y est qu'à moins de la moitié du niveau du
  plus faible des deux rendus (choix d'Eden), Eden la dit « décalée de plus de 100 ms ».
  La part des effets ne doit contenir ni la voix elle-même (un retour qui laisse passer
  l'envoi sec, un plugin dont le bouton dry/wet baisse aussi la voix), ni être plus forte
  que la voix. Sinon la voix sèche est écartée et Eden le dit : c'est ce contrôle qui vérifie,
  sur chaque morceau, que FL a bien contourné les effets coupés.
- **Voix « prudente »** : quand la séparation est impossible (état d'un slot non enregistré
  par FL, retours d'effet impossibles à distinguer, plugin non identifié sur le chemin de la
  voix) ou écartée, la réduction est limitée à 3 dB par compresseur, sans compression
  parallèle. Dans une phrase, le gain ne remonte jamais au-dessus de la réduction **moyenne**
  de la phrase jusque-là (moyenne pondérée par la puissance, comme le volume, du gain qu'aurait
  le compresseur sans ce plancher) ; dans les silences entre phrases (au moins une double
  croche du tempo ressenti), il reste figé à la moyenne de la phrase qui précède. Ce qui passe
  sous le seuil, tes queues de reverb ou d'écho, baisse donc à peu près comme le volume de sa
  phrase, et le gain de compensation le lui rend (choix d'Eden). Les queues baissent quand même
  un peu moins que leur phrase, dont les moments forts sont réduits plus que la moyenne, et
  ressortent donc un peu. Mesuré sur 10 voix de test (25 et 40 s) avec une reverb de 1,5 s à
  −12 dB ou un écho à la noire à −6 dB : pris en entier, tes effets changent de niveau comme
  la voix à 0,3 dB près ; seuls dans les silences, ils ressortent par rapport à elle de 0,1 à
  0,4 dB avec la reverb (jusqu'à 0,6 dB après une phrase) et de 0,2 à 0,9 dB avec l'écho
  (jusqu'à 1,4 dB après une phrase). Un écho aussi fort remplit les silences : Eden ne les
  repère plus, et la moyenne court alors sur plusieurs phrases. La compression de niveau peut
  y devenir une baisse presque fixe, que le gain de compensation rend aussitôt : si sa
  réduction ne bouge pas d'au moins 0,3 dB (voir § 2), elle n'est ni appliquée ni affichée.
  Mesuré sur des voix de test de 40 s avec cet écho : quand leurs phrases varient de ±2 dB, sa
  réduction bouge de 0,2 dB (5 voix sur 5, retirée) ; quand elles varient de ±4 à ±8 dB, de 0,5
  à 0,7 dB (3 voix, gardée).
- **Chaque groupe** du Mixer qui sort au Master sans voix (808, batterie, instru…).
- **Le reste** = mix d'origine (avant Master) − voix − groupes.

**L'instru complète** (une prod téléchargée d'un seul fichier, sur YouTube par exemple) est
**déjà mixée et masterisée** : Eden ne retouche pas son mix. Elle est reconnue comme le seul
fichier stéréo du projet qui dure au moins 80 % du morceau, **quel que soit son nom** : le titre
d'une vidéo (« UK Drill - Hats & Percs », « Dark 808 Melody », « Kick Back ») la ferait sinon
prendre pour une batterie, un 808 ou des backs (choix d'Eden). Plusieurs fichiers ainsi sont
des pistes séparées (un fichier par instrument) : leurs noms décident. Un fichier lu comme
une voix ne devient l'instru que si rien d'autre dans le projet ne peut l'être. Sur une
instru complète, Eden ne cherche ni kick ni 808 (§ 1, § 6) et ne signale pas un 808
désaccordé qu'on ne peut pas changer ; il lui fait seulement de la place pour la voix
pendant qu'elle chante (§ 6), et le master ne l'écrase pas une deuxième fois (§ 7).

À **0 %**, le résultat est exactement ton mix d'origine, bit pour bit (vérifié par un test).

## 1. Le morceau

| Quoi | Comment | Sert à |
|---|---|---|
| Accordage | écart de l'instru au La 440 Hz, mode d'un histogramme au cent près des pics spectraux, mesuré **avant** le chroma (sourcé : méthode d'Essentia) ; ramené au demi-ton le plus proche, de −50 à +50 cents (choix d'Eden : Essentia replie de −35 à +65 cents, ce qui lit une instru à 430 Hz un demi-ton trop bas) | lire les notes sur la bonne grille (une instru en 432 Hz est lue juste) |
| Tonalité | chroma des pics au-dessus de **200 Hz** (kick, 808 et lignes de basse brouillent le chroma ; Faraldo, sourcé) des parties harmoniques : instru complète, éléments musicaux, effets, inconnus et reste du mix, sans les groupes batterie et 808 (quand tous les groupes sont batterie ou 808 : tout le beat) ; corrélation avec trois profils (Krumhansl-Kessler, Shaath, edma ; valeurs sourcées sur Essentia) ; Temperley écarté (penche vers le majeur relatif, sourcé). Quand majeur et mineur relatifs sont proches (scores à moins de 0,1), le 808 tranche s'il joue vraiment une des deux toniques : au moins 10 % de son énergie grave et 1,5 fois plus que l'autre (choix d'Eden), et l'affichage le dit ; sinon les deux sont affichées | affichage, contrôle des notes du 808 |
| Tempo | tempo du projet FL ; pulsation « ressentie » ramenée entre 65 et 135 BPM (corpus MCFlow de rap : 79–124 BPM, non vérifié ; la trap écrite à 140 se ressent à 70) | delays, pré-delay, relâchements, phrases |
| Notes du 808 | NSDF (McLeod & Wyvill) sur la bande < 200 Hz décimée de tous les groupes basse / 808 réunis, notes de 25 à 150 Hz, affinage parabolique ; les trames d'un glissando (> 30 cents en 60 ms) sont ignorées : les hauteurs qu'un slide traverse ne sont pas des notes | note principale, notes hors gamme (averties, jamais corrigées ; ≥ 0,5 s et ≥ 3 % du jeu du 808), désaccord > 25 cents, tenue des notes du 808 (§ 6) |
| Kick / 808 | attaques du kick sous 150 Hz, sur tous les groupes batterie réunis (FL rend souvent chaque élément sur son propre insert) : montée de 4 dB en 20 ms, à moins de 12 dB des plus forts (ghost kicks compris) ; un coup n'est un kick que si la bande sous 150 Hz porte au moins 10 % de sa puissance sur ses 30 premières ms (choix d'Eden) : les 12 dB se comptent depuis les coups les plus forts de la bande grave des groupes batterie, et dans un groupe batterie sans kick (hi-hats, caisse claire, percussions ; le kick est alors dans l'instru complète, ou c'est le 808 qui en tient lieu) le peu de grave qu'ils laissent passer serait lu comme des kicks. Sur des batteries de test : hi-hats 0 %, caisses claires au corps de 180 à 200 Hz 4 % au plus, kicks de 11 % (une couche de clic qui porte 8 dB de plus que le coup sur leurs 30 premières ms) à 82 %, 18 % sous une crash ; un tom au corps sous 150 Hz (44 %) passe pour un kick ; part des kicks qui tombent sur une note de 808, et de combien le 808 baisse déjà après le kick, mesuré contre sa propre décroissance | décider d'un ducking ; pas de tenue des notes du 808 sur un 808 que FL baisse déjà (§ 6) |
| Graves en stéréo | corrélation G/D sous 100 Hz | mono des graves au master |

## 2. La chaîne de chaque voix

Ordre des chaînes rap publiées (Lil Baby / Tillie, Jaycen Joshua, Polo G / Todd Hurtt, Mike
Senior — *Sound On Sound*, **non vérifié**) : correction de hauteur (déjà dans FL) →
coupe-bas → résonances fixes → bas-médiums → de-esser léger → compression de niveau →
compression des crêtes → compression parallèle → saturation → air / recul → de-esser
principal → gain de compensation.

Chaque étape a sa mesure déclencheuse et son plafond. Les étapes dynamiques fixent leur seuil
**sur le signal qu'elles reçoivent vraiment** (après les étapes d'avant). Un compresseur ou un
de-esser n'est appliqué, et n'apparaît dans le rapport, que si sa réduction **bouge** : sa
réduction la plus forte doit dépasser d'au moins 0,3 dB celle qu'il garde sur 95 % des moments
où le signal sonne (choix d'Eden). Une réduction fixe ne fait que baisser le volume, et le gain
de compensation le rend aussitôt ; une étape qui ne réduit nulle part 0,3 dB échoue au même
test. Le haut de la courbe est son maximum, pas un centile : un de-esser qui ne prend que
quelques « s » perçants (4 en 24 s sur trois voix de test : 4,7 à 6,2 % du chant) travaille bien,
même si sa courbe ne bouge presque pas entre ses 5ᵉ et 95ᵉ centiles.
Une voix propre reçoit la saturation, plus le recul des aigus si c'est un doublage, un chœur ou
un ad-lib ; si ses attaques dépassent son corps (facteur de crête > 9 dB), la compression des
crêtes, et au-delà de 12 dB (voix principale et ad-libs) la compression parallèle ; le gain de
compensation suit dès qu'un compresseur ou un de-esser a agi.

Les mesures se font canal par canal, puissances moyennées (comme la mesure de volume) : une
voix élargie dans FL (un côté retardé, polarité inversée) est mesurée comme on l'entend, pas
repliée en mono, ce qui creuserait des trous et des bosses en peigne. « Chant » = les trames
de 1 ms à moins de 35 dB des passages forts ; seul le silence numérique (sous −90 dBFS) est
écarté d'office, si bien qu'une voix rendue plus bas est mesurée de la même façon. Les
« notes tenues » sont les demi-tons qui portent plus de 30 % des trames de 40 ms où la voix
a une hauteur nette (**choix d'Eden**) : ni résonance ni bosse n'est cherchée à moins
d'1/6 d'octave d'une note tenue ou de son octave.

**Prise déjà produite** (enregistrée à travers sa chaîne FL : Auto-Tune, reverb imprimés dans
le fichier — détectée à l'écoute, voix « printed ») : son son est fini, c'est celui de
l'artiste. Eden n'applique que les respirations et, si les « s » dépassent vraiment les
voyelles (> 0 dB), un de-esser ; **rien d'autre** — la chaîne corrective ci-dessous est pour
les prises brutes (saturer une voix autotunée sonne métallique, compresser une prise déjà
compressée pompe : retours d'écoute d'un utilisateur).

| Étape | Mesure | Eden agit si… | Traitement à 100 % | Statut |
|---|---|---|---|---|
| Respirations | segments entre les phrases (lues sur la bande voisée 120 Hz – 3,5 kHz, à 120 ms au moins des phrases : ni attaque ni fin de mot), 0,08 à 1,2 s, plus forts que le plancher (chant − 60 dB) mais **sous chant − 8 dB** (aussi fort que la voix, c'est une fricative de fin de mot ou un cri, pas une respiration), et dont la bande de bruit (2–9 kHz) monte au niveau de la bande voisée (médiane ≥ −6 dB) : du souffle, pas une note ni un mot | une respiration détectée dépasse chant − 23 dB | ramenées à 22 dB sous le chant (P95), 15 dB de réduction max, fondus de 20 ms ; les plus douces ne bougent pas ; **avant toute compression**, qui les remonterait | pratique standard (Waves DeBreath, iZotope Breath Control mode Target : les fortes baissées, les douces laissées) ; seuils : choix d'Eden |
| Coupe-bas | pendant le chant : énergie **une octave sous la coupe prévue**, là où le filtre retire 12 dB ou plus (spectre au hertz près) ; dans les **silences entre les phrases** (au moins 250 ms où la bande de la voix entre 100 et 500 Hz reste à 35 dB sous ses passages forts, silence numérique écarté ; lus par tranches de 250 ms, spectre tous les 4 Hz) : puissance **sous la coupe prévue** par rapport à la voix chantée ; note la plus grave (5ᵉ centile du F0) | > −32 dB de l'énergie de la voix pendant le chant, **ou** > −40 dB dans les silences | 80 Hz lead, 130 Hz doublages / ad-libs, 160 Hz chœurs, **jamais au-dessus de 0,9 × la note la plus grave** | fréquences non vérifiées (Jaycen Joshua ~50 Hz, Lil Baby ~70 Hz) ; « coupe-bas partout » est une idée fausse (Pestana & Reiss 2014) : d'où le déclencheur ; règle du F0, mesures et seuils : choix d'Eden (juste sous la coupe, la voix elle-même sonne encore pendant le chant : notes sous le 5ᵉ centile, attaques des syllabes ; dans les silences, elle se tait. Voix de test : propres, −33,9 dB au plus pendant le chant, et rien dans leurs silences (silence numérique) ; avec un grondement à −54 dBFS RMS, −31,5 dB au moins. Un grondement plus faible ne se distingue pas, pendant le chant, des attaques d'une voix grave : dans les silences (graines 1 à 8, voix normale et grave, lead, doublage et chœur), un grondement à −60 dBFS RMS lit −37,2 à −35,1 dB, coupé ; à −66 dBFS RMS, −43,2 à −41,2 dB, gardé ; un bruit de fond rose à −70 dBFS, −53,1 à −50,9 dB, et à −60 dBFS, −43,1 à −40,9 dB, gardés ; les queues d'une reverb FL de 1,5 s à −12 dB, −58,2 dB au plus) |
| Résonances fixes | 150–2000 Hz : chaque harmonique du chant comparée à la droite (dB contre log f) de ses voisines au même instant, jusqu'à une octave de chaque côté, en moyenne sur le chant (une fondamentale n'a pas de voisine en dessous : les notes ne sont jamais jugées) ; 2–8 kHz : enveloppe LPC moyenne | 150–2000 Hz : ≥ 4,5 dB sur 1/8 d'octave **et** 4,5 dB au-dessus des bandes à 1/6–1/3 d'octave (un formant de voyelle bouge et s'étale) ; 2–8 kHz : ≥ 4,5 dB au-dessus de la moyenne sur une octave ; pas sur une note tenue | coupes étroites (Q 6), −4 dB max, 3 au plus, à 1/3 d'octave l'une de l'autre au moins | atténuer les résonances saillantes : sourcé (Pestana & Reiss 2014) ; méthode et seuils : choix d'Eden |
| Bas-médiums | même mesure des harmoniques, moyennée sur un tiers d'octave, entre 150 et 500 Hz, seulement là où des harmoniques ont été mesurées (à 1/16 d'octave près), toutes notes confondues **et note par note** : les trames où la voix a une hauteur nette sont groupées en notes (l'étendue d'un demi-ton qui en réunit le plus forme une note, mise de côté avant de chercher la suivante : une note chantée entre deux demi-tons reste une seule note, avec son vibrato tant qu'il tient dans un demi-ton ; au-delà, elle compte pour deux) ; et 200–500 Hz vs 1–4 kHz (spectre moyen) | bosse ≥ 2,5 dB toutes notes confondues, **vue sur deux notes au moins** : chacune, sur ses propres harmoniques du tiers d'octave (20 au moins), les lève d'au moins 1,5 dB en moyenne et les place au-dessus de la droite de leurs voisines dans 90 % des cas au moins ; et écart > 6 dB ; pas sur une note tenue, ni à moins d'1/3 d'octave d'une coupe de résonance | −2,9 à −4 dB, Q 1,2, à la fréquence de la bosse | une coupe aveugle des bas-médiums n'est **pas** une pratique d'expert (Pestana & Reiss 2014, sourcé) : seulement sur une vraie bosse ; règle des deux notes et seuils : choix d'Eden. Une bosse fixe (effet de proximité, son de boîte) lève les harmoniques de chaque note, à chaque fois ; le premier formant des voyelles bouge d'une syllabe à l'autre. Voix de test, graines 1 à 20 : une bosse de +6 dB à 200, 300 ou 400 Hz lit 2,94 dB au moins, vue sur 2 à 6 notes, dont deux au moins au-dessus de la droite dans 100 % des cas (à 200 Hz, seules les notes de 98 et 110 Hz ont des harmoniques dans le tiers d'octave où elle est lue). Une voix propre dont les notes les plus graves sont entre 220 et 250 Hz, avec ou sans plateau de +1,4 à +3 dB sous 300 Hz, ne montre de bosse sur deux notes nulle part : la 2ᵉ harmonique de ses notes les plus graves tombe sur le premier formant des voyelles, juste sous 500 Hz, et lit jusqu'à 3,6 dB toutes notes confondues (sur la graine 11, huit de ces voix étaient coupées à tort avant cette règle), mais là où la bosse toutes notes confondues atteint 2,5 dB avec plus de 6 dB d'écart, une note n'est au-dessus de la droite que dans 85 % des cas au plus, et la deuxième dans 74 % au plus. Limites : une voix qui ne chante qu'une seule note dont les harmoniques tombent dans la bosse n'est pas corrigée (une coupe manquée coûte moins qu'une coupe à tort) ; sur la graine 11, la bosse de +6 dB à 400 Hz est lue à 456 Hz, où elle monte encore de 4,7 dB, et la coupe y garde 91 % de sa profondeur à 400 Hz ; la règle des 90 % n'est vérifiée que sur des voix de synthèse |
| De-esser léger | niveau des « s » les plus forts (90ᵉ centile) **dans la bande du de-esser** vs voyelles (75ᵉ centile) : ce que le de-esser compare à son seuil ; pic spectral des « s » | « s » à moins de 1 dB sous les voyelles | seuil = voyelles − 2 dB, 3 dB max, bande dès 0,7 × le pic des « s » (3,5–8 kHz ; 4,5 kHz sans pic mesuré), anticipation 5 ms ; détecteur lissé 5 ms et attaque 3 ms (les deux de-essers) : lu sur les trames brutes de 1 ms, le gain ondulait au rythme de la hauteur de la voix — un son « crunchy », robotique (retour d'écoute) | deux de-essers (avant / après compression) : non vérifié (Senior) |
| Compression de niveau | écart P90 − P10 des blocs de 400 ms **à l'intérieur des phrases** | > 4 dB | 1,5:1 (écart de 4 dB) à 3:1 (10 dB et plus), attaque 10 ms, relâchement 60 ms puis 800 ms après 200 ms de réduction (type opto), seuil pour 3 dB sur le P90 du chant | chiffres non vérifiés (SOS, LA-2A) ; choix d'Eden |
| Compression des crêtes | facteur de crête | > 9 dB | 4:1, attaque 2 ms, relâchement 80 ms, 6 dB max, 3 dB sur le P97 | non vérifié (1176) ; choix d'Eden |
| Parallèle | facteur de crête | > 12 dB, voix principale et ad-libs (jamais sur une voix prudente) | copie 8:1, 100 Hz – 5 kHz, mélangée à 20 % (ad-libs 10 %), alignée à l'échantillon | pratique non vérifiée (bus parallèle des sessions rap) |
| Saturation | — | toujours | tanh suréchantillonné ×4, de 200 Hz jusqu'au début de la bande des « s », 15 % (ad-libs 20 %, autres 10 %), même couleur quel que soit le volume rendu | non vérifié ; choix d'Eden |
| Air | > 8 kHz vs 2–5 kHz sur les voyelles | < −25 dB | +1,5 dB au-dessus de 10 kHz | choix d'Eden |
| Recul | — (doublages, chœurs, ad-libs) | toujours | −1,5 à −2 dB au-dessus de 7 kHz | choix d'Eden |
| De-esser principal | « s » dans la bande du de-esser vs voyelles | « s » à moins de 5 dB sous les voyelles | seuil = voyelles − 6 dB, 2 à 6 dB (lead), jusqu'à 8 dB (autres), même bande | non vérifié (Pro-DS en fin de chaîne) |
| Gain de compensation | volume BS.1770 **juste avant le premier compresseur ou de-esser** / après la chaîne | dès qu'un compresseur ou un de-esser agit (s'ils restent tous inactifs, aucun gain : l'écart ne viendrait que des filtres, de la saturation ou de la compression parallèle) | rend à la voix le volume que compresseurs et de-essers lui ont pris — pas ce que respirations et filtres ont retiré : mesuré depuis l'entrée de la chaîne, il rendait aussi ce volume-là et remontait les respirations à peine baissées | le niveau de la voix dans le mix est ensuite décidé sur une mesure, à un seul endroit |

## 3. Niveaux et suivi

Une voix dont le type n'a pas pu être reconnu (« Voix (type à confirmer) » : une piste nommée
« Vox », « Voix », « Hook », « Couplet »…) est mixée comme une voix principale : même chaîne,
même réglage contre l'instru, même suivi, mêmes envois d'espace. Rien ne permet encore de
choisir son type dans Eden : renomme la piste dans FL Studio (« Lead », « Double », « Backs »,
« Ad-lib »…) puis relance l'analyse.

- **Voix principale** : volume K-pondéré de la voix moins celui de l'instru, **pendant
  qu'elle chante** ; cible **+1 dB**, fenêtre −1 à +4 dB (**choix d'Eden**), changement
  statique 10 dB max (**choix d'Eden** : une voix brute posée sur une instru déjà masterisée
  peut se trouver 10 dB en dessous). Repères : les experts placent la voix principale à peu près
  au volume de tout le reste réuni (≈ 0 dB, Pestana & Reiss 2014, sourcé) ; les autres voix
  étant réglées ensuite vers −6 dB sous elle, +1 dB contre l'instru seule retombe près de
  0 dB contre tout le reste. La mesure BS.1770 lit une voix environ 2 LU plus bas qu'on ne
  l'entend (Pestana & Reiss 2013, non vérifié en texte intégral). Le classement du rap
  parmi les genres « voix devant » (Gerdes & Siedenburg 2023) et la préférence des auditeurs
  pour une voix 3 à 6 dB plus forte (Knoll & Siedenburg 2022) n'ont pas pu être ouverts.
  Quand **toutes les voix sont des prises déjà produites** (enregistrées à travers leur chaîne
  FL : Auto-Tune, reverb imprimés — reconnues à l'oreille, voir § 4), leurs niveaux sont ceux
  que l'artiste a validés en enregistrant : le changement statique est borné à **±4 dB** au
  lieu de 10 (retour d'écoute d'un utilisateur : une voix posée basse exprès, remontée de
  10 dB, saturait le master).
- **Voix restée hors de sa fenêtre** : l'intensité règle la part du changement qu'Eden fait
  (à 50 %, la moitié). Si, ce changement fait, la voix reste hors de sa fenêtre (un gain
  statique déplace l'équilibre d'autant de dB), Eden le signale dans les avertissements avec
  l'écart qui reste, par exemple « « Lead » reste à -6.2 dB de l'instru pendant qu'elle
  chante, niveau d'Eden compris (visé +1 dB, accepté de -1 à +4 dB) : monte la voix ou
  baisse l'instru dans FL Studio », précédé de « À cette intensité, » sous 100 %. Le suivi
  phrase par phrase ne corrige pas cet écart : il garde l'équilibre médian de la voix.
- **Un seul gain statique pour toute la performance vocale**, mesuré sur les voix principales
  réunies contre l'instru : un couplet posé doucement et un refrain empilé gardent l'écart que
  l'artiste leur a donné (réglés chacun vers la même cible, une section calme remontait au
  niveau d'une section pleine : retour d'écoute d'un utilisateur).
- **Voix principales qui chantent ensemble** (prises empilées d'un refrain, piste dupliquée) :
  deux voix chantent ensemble quand celle qui chante le moins partage au moins la moitié de
  ses blocs chantés avec l'autre (choix d'Eden), de proche en proche. Leur somme est réglée
  contre l'instru comme une seule voix, avec la même cible et le même maximum de 10 dB, et
  elles reçoivent le même gain statique : ce réglage ne change pas leur équilibre entre elles
  (le suivi phrase par phrase, ensuite, se fait voix par voix). Seule exception : une voix
  principale qui copie une autre (corrélation > 0,8 à ±40 ms, lue seulement entre deux voix qui
  chantent ensemble : une copie chante quand l'originale chante) n'est jamais montée. Quand deux
  voix se copient l'une l'autre (piste dupliquée), la première dans l'ordre du projet compte
  comme l'originale et reçoit le gain ; seule l'autre est gardée à son niveau, et la somme
  est alors mesurée à nouveau pour l'avertissement.
- **Suivi phrase par phrase** (« vocal riding », pratique d'expert sourcée : Pestana & Reiss
  2014) : phrases = plages de chant d'au moins 0,3 s séparées d'au moins une croche du tempo
  ressenti, lues sur la **bande voisée** de la voix (120 Hz – 3,5 kHz, là où vivent les
  voyelles) : une respiration, la fuite du casque ou une queue d'effet n'y passent pas pour
  une phrase — la détection de respiration qu'ont les Vocal Riders du commerce, pour ne
  jamais remonter une respiration (choix d'Eden) ; une « phrase » à plus de 10 dB sous les
  phrases pleines de la voix (leur 75e centile — une médiane glisse sur un morceau à moitié
  posé et laissait passer les respirations) n'en est pas une (respiration, fuite) : laissée
  telle quelle.
  L'instru est mesurée **au-dessus de 200 Hz**, la bande qui couvre les paroles (le sub d'un
  808 les masque à peine ; choix d'Eden) ; référence = l'équilibre médian de la voix sur tout
  le morceau (pas une valeur fixe) ; une phrase à plus de 2 dB de cette référence est
  ramenée, ±3 dB max (loin sous la plage par défaut ±6 dB d'un Vocal Rider : le suivi ne doit
  jamais s'entendre travailler ; choix d'Eden). **Chaque gain doit avoir sa cause dans le
  signal** : une phrase n'est baissée que de ce dont la voix elle-même dépasse ses phrases
  pleines (leur 75e centile ; l'instru qui se retire n'est jamais une raison de baisser la
  voix), et n'est montée que de ce dont la voix est sous elles plus ce dont l'instru dépasse
  sa phrase médiane (un écart sans cause mesurée — prises qui se chevauchent, mesure
  incertaine — ne bouge pas). Une phrase que l'artiste a baissée de 6 dB ou plus sous ses
  phrases pleines est un choix de jeu (rapper doucement) : jamais remontée (retour d'écoute
  d'un utilisateur : « quand je rap doucement, ça sonne ultra fort d'un coup »). Quand toutes
  les voix sont des prises déjà produites, le suivi est coupé : leurs variations de niveau
  sont celles de la prise validée, pas un accident à corriger. **Un seul gain pour toutes les voix**, lu sur
  les voix principales réunies, suivi par les doublages, chœurs et ad-libs : suivis chacun de
  leur côté, deux prises d'un même refrain dérivaient l'une de l'autre et leur somme sortait
  du mix ou saturait (retour d'écoute). Une phrase où l'instru est à plus de 6 dB sous sa phrase médiane (break, filtre,
  beat coupé pour une punchline) est laissée telle quelle et ne compte pas dans la
  référence. Le gain tient
  pendant le silence et change dans les 120 ms qui précèdent la phrase suivante (les silences
  du rap durent le plus souvent une double croche, ~180 ms : MCFlow, non vérifié). Sur une voix
  dont les reverbs et delays FL ont été rendus à part, les phrases et leur niveau sont lus sur la
  voix sans eux : leurs queues rempliraient les silences et souderaient les phrases (sur une voix
  de test aux silences de 0,6 s, avec un écho à la noire à −15 dB, tout le morceau ne formait
  plus qu'une phrase, et rien n'était suivi). Ils reçoivent le même gain que la voix et
  suivent donc leur phrase. Sur une voix « prudente », ils sont dans la voix et ne peuvent pas
  être mis de côté.
- **Doublages / ad-libs / chœurs** : ils suivent le gain de la performance, rien de plus —
  **jamais montés par rapport aux autres voix**. Un chœur que l'artiste a posé discret est un
  choix ; remonté vers une cible, un empilement enregistré sortait du mix et saturait (retour
  d'écoute d'un utilisateur). Les fenêtres par rôle (−6 (−10 à −3) doublage, −6 (−9 à −3)
  ad-lib, −7 (−10 à −4) dB chœurs, moyennes de blogs, **non vérifié**) ne servent plus qu'à
  deux choses : **baisser** une voix qui couvre la voix principale (au-dessus de sa fenêtre,
  elle descend vers sa cible, 4 dB au plus au-delà de « suivre » ; choix d'Eden), et
  **signaler** une voix restée hors fenêtre (« monte cette voix » ou « baisse cette voix dans
  FL Studio ») : la décision de la monter appartient à l'artiste. Un doublage **copie** de la
  voix principale (corrélation > 0,8 à ±40 ms, choix d'Eden) suit son gain sans jamais être
  monté par rapport à elle (filtrage en peigne), et rien n'est signalé : c'est voulu.

## 4. Espace

Rien n'est ajouté à une voix qui porte déjà une reverb ou un delay FL, ni à une prise qui
**sonne déjà réverbérée** : si, après les fins de phrase suivies d'un silence, l'enregistrement
lui-même continue de sonner à moins de 48 dB sous le chant (médiane sur au moins 2 fins de
phrase, fenêtre 80–300 ms après la phrase ; choix d'Eden), une reverb ou un delay a été
enregistré dans la prise (FL enregistre la piste du Mixer avec ses effets) : Eden la traite
comme une voix « prudente » et n'ajoute rien par-dessus. Pour les autres,
les « quatre envois » d'un lead rap devant mais collé au beat (architecture non vérifiée,
synthèse de la recherche ; niveaux : choix d'Eden) :

Le rap se tient sec : chaque retour reste loin sous la voix (niveaux revus à la baisse de
4 dB après écoute d'un utilisateur : « beaucoup trop d'écho » ; choix d'Eden).

| Envoi | Réglage | Niveau (sous la voix, avant ducking) |
|---|---|---|
| Ambiance | 80 ms, pré-delay 8 ms, 400 Hz – 6 kHz | −26 dB |
| Plate | 0,8 à 1,4 s (≈ 2 temps ressentis), pré-delay = 1/64 ou 1/32 le plus proche de 45 ms, borné 20–80 ms, 300 Hz – 6 kHz, baissée de 2,5 dB pendant le chant | −23 dB |
| Delay 1/8 | ping-pong, feedback 0,25, 400 Hz – 4 kHz, baissé de 10 dB pendant le chant ; remonte en un quart du temps de delay, pour que le premier écho après la phrase s'entende en entier | −25 dB |
| Jet d'écho (lead) | 1/4, feedback 0,3, envoyé seulement sur la fin d'une phrase suivie d'un silence d'au moins deux échos (un jet est rare, pas une habitude), baissé de 10 dB pendant le chant ; remonte en un quart du temps de delay | −16 dB |

- Voix secondaires : mêmes envois 4 dB plus présents (plus loin).
- L'envoi est dé-essé une fois (8 dB) avant tous les effets : un « s » répété n'est que du
  bruit.
- Les niveaux sont réglés sur le volume BS.1770 de la voix sèche, pas sur ses crêtes.
- **Plafond** : Eden garde la reverb de tout le morceau, **tes effets FL compris**, à −19 LU
  au plus par rapport au mix sec quand il le peut en baissant ses propres effets ; les tiens
  ne sont jamais touchés. Sourcé : De Man, McNally & Reiss 2017, 80 mixes : à −9 LU ou plus,
  toujours jugé trop mouillé ; −14 LU plus souhaitable. Le rap se tient plus sec : choix
  d'Eden. Quand le plafond n'est dépassé qu'avec les effets d'Eden, ils baissent juste assez,
  et chaque voix concernée dit de combien. Si tes effets dépassent déjà ce plafond à eux
  seuls, Eden retire les siens et te le signale dans les avertissements, avec la valeur
  mesurée et les voix dont les effets FL sont en cause ; sur chaque voix qui en aurait reçu,
  la liste de ses envois est remplacée par « Effets d'Eden retirés » et cette valeur.
- Tes effets FL ne comptent que s'ils ont été rendus à part. Quand la reverb ou le delay FL
  d'une voix reste dans sa voix (voix « prudente »), la reverb du morceau ne peut pas être
  mesurée : Eden n'ajoute alors d'espace à **aucune** voix, et l'indique sur chaque voix qui
  en aurait reçu, en nommant la voix en cause.

## 5. Stéréo

- Voix principale : au centre, jamais touchée (pratique d'expert sourcée).
- Les doublages et les chœurs ne vont par paires que s'ils **chantent ensemble** : celle des
  deux qui chante le moins partage au moins la moitié de ses blocs chantés avec l'autre
  (choix d'Eden). Les paires qui partagent la plus grande part de leur chant se forment
  d'abord ; une voix n'est que dans une paire.
- Doublages : une paire de vraies prises → ±85 % ; un doublage sans partenaire (aucune autre
  vraie prise ne chante avec lui, ou celles qui chantent avec lui sont déjà en paire) →
  centre ; une copie de la voix principale → centre.
- Chœurs : ±55 % en paires ; un chœur sans partenaire (aucun autre ne chante avec lui, ou
  ceux qui chantent avec lui sont déjà en paire) → 40 % à droite.
  Ad-libs : ±50 %, **chaque phrase change de côté** au milieu du silence (fondu 50 ms),
  jamais au centre pendant la voix principale.
- Une voix déjà élargie ou placée dans FL (side > −20 dB du mid) est laissée telle quelle.
  C'est mesuré sur la voix sèche quand FL l'a rendue : ta reverb stéréo n'est pas un
  placement.
- Seule la voix est placée : tes reverbs et delays FL gardent leur largeur. Ils suivent une
  voix posée d'un côté (balance, sans repasser en mono) et restent où FL les a mis sous un
  ad-lib qui change de côté.
- Panoramique à puissance constante, **le canal fort jamais au-dessus de la source** : la
  compensation de puissance est plafonnée à ce que le canal le plus fort reste au niveau du
  fichier d'origine (sans ce plafond, une voix posée franchement d'un côté sortait jusqu'à
  +3 dB au-dessus de sa prise et poussait des crêtes dans le master). Valeurs de placement :
  choix d'Eden.

## 6. Place pour les paroles et basses

- **Démasquage** : dans chaque bande de tiers d'octave centrée de 250 Hz à 8 kHz, Eden
  mesure l'instru moins la voix pendant le chant, la voix au niveau qu'il prévoit de lui
  donner (§ 3, réglé sur l'instru avant le creux) : mesurée telle que FL l'a rendue, une
  voix rendue 10 dB trop bas lirait l'instru 10 dB plus haut dans chaque bande, et les creux
  tomberaient ailleurs. Une bande où l'instru est 3 dB ou plus sous la voix n'a pas besoin
  de creux ; les autres baisseraient, à 100 %, de 1 dB (instru 3 dB sous la voix) à 3 dB
  (instru 3 dB au-dessus ou plus). Sont écartées celles que l'instru couvre de plus de 12 dB
  (même creusée de 3 dB, la voix y resterait à plus de 9 dB sous l'instru ; selon le modèle
  d'audibilité ci-dessous, ce creux y gagnerait pourtant autant que dans une bande retenue
  jusqu'à 15 dB, et moins jusqu'à 18 dB : c'est un choix) et celles où la voix est à plus de
  20 dB sous sa bande la plus forte (elle n'y a presque rien) : 12 et 20 dB, choix d'Eden.
  Le creux s'ouvre en ~120 ms et se referme en ~900 ms : l'instru ne clignote pas au rythme
  des phrases (avec 15 / 200 ms, un utilisateur entendait « le master changer toutes les
  5 secondes »). Au plus 3 bandes sont gardées : celles où le creux rend le plus de paroles audibles, soit
  l'importance de la bande pour l'intelligibilité (ANSI S3.5, 1–4 kHz ≈ 72 % du poids,
  sourcé ; chaque tiers reçoit le tiers du poids de son octave) × l'audibilité gagnée,
  l'audibilité d'une bande valant 0 quand la voix est 15 dB sous l'instru, 1 à partir de
  15 dB au-dessus, et montant en ligne droite entre les deux (ANSI S3.5, non vérifié sur le
  texte de la norme). Dans les bandes retenues (instru de 3 dB sous la voix à 12 dB
  au-dessus), l'audibilité n'atteint jamais 0 ni 1 : l'audibilité gagnée vaut la profondeur
  du creux divisée par 30, et le classement revient à importance × profondeur. Le creux ne
  joue que quand la voix chante (comme l'« Unmask » des égaliseurs dynamiques, non vérifié ;
  choix d'Eden) ; baisser l'instru là où elle masque la voix est la méthode de Hafezi &
  Reiss 2015 (sourcé). L'instru est creusée là où elle a été mesurée : dans les groupes et
  dans le reste du mix (une instru qui passe par un bus partagé avec les voix s'y retrouve).
  Quand des voix sont restées dans le reste du mix (au-delà des 16 voix qu'Eden fait rendre
  une par une), seuls les groupes sont mesurés et creusés : creuser le reste baisserait
  aussi ces voix ; le motif du creux le dit. Le creux est affiché sur les groupes, et sur
  une ligne « Reste du mix », quand ils portent au moins 25 % de ce qu'il retire (choix
  d'Eden). Fait **avant** l'équilibre : le niveau de la voix principale est d'abord prévu
  sur l'instru avant le creux, les bandes sont choisies avec la voix à ce niveau, puis
  l'équilibre est mesuré à nouveau sur l'instru creusée, telle qu'on l'entendra. Les doublages,
  chœurs et ad-libs ne sont plus baissés dans 1–4 kHz pendant la voix principale : ce creux,
  déclenché par le chant, changeait le son de l'empilement à chaque entrée de voix (retour
  d'écoute d'un utilisateur).
- **Tenue des notes du 808** : avant le ducking, Eden lit les notes du 808 sur tous les
  groupes basse / 808 réunis, que FL rend à part : aucun kick n'y gêne la lecture des notes.
  Le niveau est celui de la bande sous 100 Hz, moyenné sur une période de chaque note (sans
  l'ondulation de l'onde) ; seuls comptent ses mouvements à moins de 30 dB du moment le plus
  fort de ces groupes. Une note commence sur son attaque : le niveau monte de 3 dB en 30 ms
  au plus depuis son point le plus bas (une même note rejouée remonte du petit creux entre
  les deux). Le suivi de hauteur (§ 1) place une note jusqu'à environ 150 ms après son
  attaque (un 808 dont la hauteur chute à l'attaque) et jusqu'à 30 ms avant : elle commence
  sur la dernière montée de 200 ms avant à 40 ms après l'endroit où il la place ; sans
  montée, là où finit la dernière baisse de 3 dB en 30 ms de ce même intervalle (une note
  plus faible enchaînée). Un changement de hauteur sans l'une ni l'autre (un glissé)
  continue la note : il n'a pas de tête à lui, seulement la décroissance de la note. Dans
  une note, la même hauteur rejouée monte de 3 dB en 30 ms ; rejouée plus bas sans attaque,
  elle baisse de 3 dB en 30 ms entre deux passages qui tiennent chacun à 1,5 dB près sur
  80 ms, sauf si le niveau remonte dans les 80 ms qui suivent. Une note au plus par 80 ms ;
  son niveau est le haut de ses 80 premières ms. Les notes au-dessus de 80 Hz ne sont pas
  comparées : le filtre à 100 Hz retire déjà une part de leur fondamentale. Si au moins
  4 notes sont lues et qu'elles varient de plus de 4 dB d'une note à l'autre (du 10ᵉ au 90ᵉ
  centile ; dans le grave, l'oreille entend un écart plus grand qu'il ne se mesure), un
  compresseur agit sur la bande sous 100 Hz de ces groupes : ratio 1 + intensité (2:1 à
  100 %), au plus 3 dB × intensité, attaque 10 ms, relâchement 150 ms, seuil réglé pour que
  la courbe du compresseur (genou doux de 6 dB compris) baisse de 1,5 dB × intensité la note
  du 90ᵉ centile telle que la lit son détecteur (lissage 5 ms) ; l'attaque de 10 ms laisse
  passer le début de la tête : sur des 808 de test, la réduction atteinte y est de 67 à 92 %
  de celle de la courbe ; la réduction mesurée est affichée. Le gain est calculé une fois
  sur la somme des groupes et appliqué tel quel à la bande sous 100 Hz de chacun (filtre à
  phase nulle, au-dessus le 808 est intact) : leur somme reçoit exactement ce gain. Comme
  pour les voix (§ 2), une compression dont la réduction ne bouge pas d'au moins 0,3 dB
  n'est pas appliquée. Quand le 808 baisse déjà de 2 dB ou plus après les kicks (un
  sidechain dans FL, mesuré comme pour le ducking ci-dessous, sur les groupes batterie
  rendus à part), la tenue n'est pas faite : ses creux et ses remontées à chaque kick
  passeraient pour des notes (sur des 808 de test aux notes égales, baissés de 4 à 10 dB à
  chaque kick, elle se déclenchait à tort dans 22 cas sur 60). Tous ces seuils et réglages :
  choix d'Eden. Le motif donne le nombre de notes lues et leur écart. Limites : une instru
  rendue en un seul fichier, le 808 dedans (pas de groupe basse / 808 à part), n'a pas ce
  traitement ; un 808 baissé à chaque kick dans FL alors que les kicks ne sont pas rendus
  dans un groupe batterie à part n'est pas reconnu, ses remontées peuvent passer pour des
  notes rejouées ; un kick rendu dans le même groupe que le 808 peut passer pour une note
  rejouée ; une note enchaînée sans monter ni baisser de 3 dB en 30 ms n'est pas séparée de
  la précédente ; deux notes qui se chevauchent battent, et ce battement peut passer pour
  des notes rejouées (sur des 808 de test aux notes égales dont chaque note déborde sur la
  suivante d'un quart de l'écart entre deux notes, la tenue s'est déclenchée à tort dans
  8 cas sur 27).
- **Kick / 808** : si plus d'un kick sur deux (lus sur tous les groupes batterie réunis ;
  un coup dont la bande sous 150 Hz porte moins de 10 % de la puissance sur ses 30 premières
  ms n'en est pas un, voir § 1 : un groupe de hi-hats ou de caisse claire seul ne fait pas
  baisser le 808) tombe sur une note de 808 qui ne baisse pas déjà (< 2 dB), chaque groupe
  basse / 808 est baissé de 3 dB sous 100 Hz à chacun de ces kicks : descente en 5 ms
  (cosinus, sans clic) avant l'attaque, tenue 30 ms après, remontée 100 ms. Chaque kick est
  calé sur son attaque : sa montée est repérée sur la moyenne des 20 ms autour de chaque
  milliseconde, qui commence à monter jusqu'à 10 ms avant le kick, puis le kick est placé sur
  la première milliseconde, de 10 ms avant à 10 ms après, qui dépasse de 4 dB les 20 ms
  d'avant et arrive à moins de 10 dB du coup (choix d'Eden ; à 2 ms près sur des kicks de
  test à 44,1, 48 et 96 kHz, vérifié par les tests). Filtre à phase nulle :
  au-dessus de 100 Hz, le 808 (sa distorsion, ses harmoniques) est intact. Jamais plus : les
  ingénieurs sont partagés sur le ducking, Eden reste conservateur.
- **808 nu** (harmoniques 2–5 à plus de 20 dB sous la fondamentale, mesurées sur tous les
  groupes basse / 808 réunis) : harmoniques générées, dans chacun de ces groupes, depuis
  sa bande sub seule, note par note (enveloppe normalisée), pour que l'oreille
  reconstruise la note à partir des harmoniques 3 à 5 (fondamentale manquante) ; filtrées
  80–400 Hz, 14 dB sous la fondamentale (choix d'Eden), pour qu'un téléphone entende la note.

À la fin du mix, son volume est comparé au morceau tel que FL le jouait (le prémaster) : un
mix sorti **plus fort** est ramené à ce niveau avant le master ; un mix sorti plus bas (des
voix baissées) y **reste** — remonté, les crêtes de l'instru, elle intouchée, entraient dans
le master plus fort que FL ne les a jamais jouées (entendu comme une saturation, différente à
chaque version).

## 7. Mastering Eden

Chaîne (tout hors ligne, en float64) :

1. graves en mono sous 100 Hz si la corrélation G/D y est < 0,9 (filtre à phase nulle) ;
2. compression de bus : 1,6:1, seuil 4 dB sous les passages forts (P90 du niveau tel que le
   lit le détecteur du compresseur, lissé sur 5 ms : les trames brutes de 1 ms ondulent dans
   chaque cycle et placeraient le seuil ailleurs), attaque 30 ms, relâchement sur le temps
   ressenti, ≤ 3 dB ; 1,5 dB de réduction au niveau des passages forts (sur la courbe du
   compresseur ; la réduction mesurée est affichée, voir plus bas) ;
3. gain → clip doux suréchantillonné ×8 (arrondi à partir de 85 % du plafond du clip : à
   70 %, tout le haut du mix vivait en permanence dans le genou et le master sonnait
   granuleux ; plafond du clip 0,1 dB **sous** le plafond du limiteur : placé 1 dB au-dessus,
   le limiteur reprenait chaque crête écrêtée d'un dB de plus, les deux étages travaillaient
   en permanence) → limiteur true-peak (sur la crête de l'onde continue, anticipation 5 ms :
   le gain descend en rampe avant une crête, jamais d'un coup ; tenue 20 ms et relâchement
   250 ms pour ne pas onduler dans un cycle de 808 ni pomper entre deux kicks) au plafond
   final.

La tenue des notes du 808 ne se fait pas ici mais au mixage, sur les groupes 808 (§ 6) : sur
le mix complet, les kicks gênent la lecture des notes.

Comme pour les voix (§ 2), une compression dont la réduction ne bouge pas d'au moins 0,3 dB n'est pas
appliquée et n'apparaît pas dans le rapport ; celles qui agissent affichent la réduction
mesurée (moyenne quand elles agissent, et maximum).

- **Cible : −9 LUFS ressentis** (« fort, comme le rap commercial », ton choix) : le volume
  que **tiennent les passages forts** du morceau — le 95ᵉ centile du volume court terme
  (fenêtres de 3 s) — pas la moyenne du morceau. Visée sur la moyenne, un couplet calme la
  tirait vers le bas : le gain surcompensait, le refrain saturait et les couplets posés
  sortaient trop fort (retour d'écoute d'un utilisateur : « quand le son est bas il le met
  super fort, quand il est fort il le met super bas »). Les charts se tiennent vers −8 LUFS
  (iZotope 2024, non vérifié). Au-delà, rien n'est gagné sur les plateformes, qui baissent
  les morceaux forts, et la distorsion d'encodage augmente. Le gain est visé sur une
  estimation rapide (le clip et la loi du limiteur sans suréchantillonnage) ; une première
  passe réelle mesure l'écart entre l'estimation et la vraie chaîne, et le gain est visé à
  nouveau avec cet écart. Deux passes réelles suffisent le plus souvent, trois au plus ; une
  quatrième n'a lieu que si la troisième dépasse encore le budget.
- **Budget de réduction** (choix d'Eden) : clip + limiteur ne baissent pas de plus de
  **6 dB** les crêtes qui reviennent dans le morceau (à 9 dB d'abord essayés, les refrains
  sortaient audiblement écrasés : retour d'écoute ; la limitation commerciale forte se tient
  vers 3–6 dB), mesurées par blocs de 50 ms (le 98,5ᵉ
  centile des blocs réduits de plus de 0,5 dB, sans dépasser le 10ᵉ bloc le plus réduit :
  un clic, une plosive ou un seul impact au drop ne décident pas du volume de tout le
  morceau). Un événement isolé peut aller jusqu'à **10 dB** sur 30 ms (trois blocs de 10 ms
  de suite). Plus court, un clic écrêté reste un clic : sa réduction est affichée, pas
  comptée. Au-delà du budget, Eden baisse le gain de l'excès **plus 0,5 dB** — jamais garé
  exactement sur le bord — et le dit : « les crêtes qui reviennent » quand ce sont elles, ou
  le moment de l'événement isolé. Une fois le budget touché, le gain ne remonte plus vers son
  bord : il remontait, le master vivait en permanence à la limite et chaque passage dense
  s'écrasait.
- **Avec une instru complète**, déjà passée par le limiteur de son beatmaker, le budget sur
  les crêtes qui reviennent tombe à **5 dB** (choix d'Eden ; 9 dB pour un événement isolé) :
  le master reste un peu moins fort plutôt que d'écraser ses percussions une deuxième fois,
  et le dit.
- **Plafond** : −2 dBTP (Spotify demande ≤ −2 dBTP pour un master plus fort que −14 LUFS :
  non vérifié, cohérent avec AES TD1008). À −9 LUFS, −2 dBTP laisserait moins de 8 dB entre
  crête et volume. Sur un master aussi dense, Opus 96k et MP3 128k dépassent de 1,2 à 2,2 dB
  à l'encodage (sourcé : essais d'encodage reproduits deux fois indépendamment). Un master à
  −9 LUFS reçoit donc **−3 dBTP**, c'est le cas normal. Si le budget arrête le master plus
  bas, le plafond est choisi à nouveau sur le volume atteint : quand, à −2 dBTP, le même master
  (jusqu'à 1 dB plus haut, exactement — toute la chaîne suit le plafond — mais jamais remonté
  au-delà de la cible) laisse encore au moins 8 dB entre crête et volume, il passe à −2 dBTP.
- **Crête réelle** : lue deux fois. D'abord la crête de l'onde continue : reconstruction
  idéale à 8× (sans affinage, jusqu'à 0,17 dB sous-lus entre les points), affinée par une
  parabole autour du point le plus haut de chaque échantillon ; elle reste à 0,01 dB d'une
  référence à 64× sur du bruit, des ondes écrêtées et des masters (vérifié par les tests).
  Ensuite comme la lit libebur128 (4×, filtre de 49 points, vérifié sur son code). La plus
  haute des deux est gardée ; le limiteur laisse la sortie au moins 0,01 dB sous le plafond.
  Les mesureurs de FFmpeg (filtres ebur128 et loudnorm) ne lisent pas comme libebur128 : ils
  rééchantillonnent à 192 kHz et peuvent afficher jusqu'à environ 0,3 dB de plus (mesuré sur
  des masters d'Eden : 0,05 à 0,25 dB de plus).
- **Vérifications** : volume intégré et court terme maximal, plage de volume (EBU Tech 3342),
  crête réelle, rapport crête / volume (averti 0,5 dB sous celui que le plafond prévoit,
  plafond moins volume visé, ou atteint si le budget arrête le master : 6 dB à −9 LUFS et
  −3 dBTP, d'où 5,5 dB ; un master plus calme ne l'est que sous 7,5 dB ; choix d'Eden), perte
  en mono, **trous en mono** (une bande de tiers d'octave qui, en moyenne sur 2 s, perd plus
  de 6 dB en mono alors qu'elle porte au moins 1 % de la puissance de ces 2 s ; un élément
  large et décorrélé perd 3 dB en moyenne et n'en est pas un), et ce que chaque plateforme
  fera du fichier : Spotify, YouTube, TIDAL, Amazon, SoundCloud −14 LUFS ; Deezer −15 ; Apple
  Music −16 (non vérifiés, cohérents entre eux) ; les morceaux forts sont baissés, Spotify ne
  remonte les faibles que jusqu'à −1 dBTP.

## Versions et export

- Chaque mixage est gardé : WAV final 32 bits flottant, et toutes les décisions avec leurs
  raisons (le morceau, le mastering et ses contrôles). Il peut être réaffiché puis exporté.
- L'export choisit le dossier, le nom, la fréquence et la profondeur : 16 bits avec dither
  TPDF, 24 bits, ou 32 bits flottant. « .wav » est ajouté au nom tel que tu l'as tapé, points
  compris : « Beat v1.2 - Eden » donne « Beat v1.2 - Eden.wav ».
- Il n'y a pas de conversion si tu gardes la fréquence de FL. Sinon, le filtre est plat
  jusqu'à 91 % de la fréquence de Nyquist la plus basse (20 kHz à 44,1 kHz) et rejette
  100 dB au-dessus : rien ne se replie dans l'audible.
- Une conversion peut remonter un peu la crête réelle (l'onde est reconstruite entre de
  nouveaux points). Un limiteur true-peak la ramène alors sous celle du fichier, et l'export
  affiche la crête finale.
- Eden n'écrase jamais un fichier existant et refuse un export 16 ou 24 bits qui serait
  écrêté.

## Limites et à valider

- Les valeurs « choix d'Eden » et « non vérifié » sont des valeurs de départ, à ajuster à
  l'écoute sur tes morceaux. Les tests automatiques vérifient le reste :
  - chaque mesure déclenche bien son traitement, et chaque traitement réduit bien le défaut
    visé ;
  - 0 % est exact ;
  - le master atteint sa cible sous le plafond pour les deux lectures de crête.
- Pas de suppression dynamique des résonances (type *soothe*). Mesurée sur des voix, la
  méthode simple (pics du spectre au-dessus de leur enveloppe en tiers d'octave) confond les
  harmoniques normales d'une voix avec des résonances dures. Il faudrait un détecteur qui
  tienne compte des harmoniques, validé sur de vraies voix. Les résonances fixes (pièce,
  micro) sont, elles, corrigées.
- L'équilibre de la voix principale se mesure contre l'instru seule. Les autres voix sont
  réglées ensuite par rapport à elle.
- Pas de courbe d'équilibre tonal de référence (il faudrait un corpus de masters rap) : Eden
  ne corrige pas la balance tonale globale au master.
- Quand l'instru est un seul fichier stéréo, kick et 808 ne peuvent pas être traités
  séparément.
- L'écoute avant / après de la page du résultat compare ton morceau tel que FL Studio
  l'exporte et la version d'Eden ; « même volume » (activé par défaut) baisse la plus forte
  de l'écart mesuré en BS.1770 pendant l'écoute seulement.
