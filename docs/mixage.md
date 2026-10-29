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

- **Chaque voix seule**, rendue par FL avec toute sa chaîne (inserts, bus, envois).
- **Chaque voix sèche** : si sa chaîne FL contient une reverb ou un delay que FL joue
  vraiment (slot actif avec un dry/wet qui n'est pas à 0, insert et ses effets actifs, insert
  qui atteint le Master : un retour coupé ou routé nulle part ne compte pas), FL la rend aussi
  avec ces effets coupés. Un plugin qu'Eden n'identifie pas compte comme reverb ou delay
  quand il est sur un autre insert que celui de la voix et que le nom de cet insert contient
  « verb », « delay », « echo », « écho » ou « space » (choix d'Eden) ; Eden le signale.
  Un retour d'effet est reconnu par la topologie du Mixer (un insert autre que celui de la
  voix, qui porte une reverb ou un delay, et dont la voix n'a pas besoin pour atteindre le
  Master) : il est coupé en entier, limiteur ou EQ compris. Quand la voix peut se passer de
  chacun de ces inserts mais pas de tous à la fois (un bus voix avec un delay en ligne à côté
  d'un retour de reverb), leur numéro ne compte pas : ceux dont le premier effet (EQ,
  utilitaires et plugins non identifiés mis à part) est la reverb ou le delay sont les
  retours, les autres sont le chemin de la voix, car un bus commence par sa dynamique (choix
  d'Eden) ; si ça ne tranche pas, pas de voix sèche, et Eden dit pourquoi. Sur le chemin
  propre de la voix, les slots de reverb et de delay sont désactivés un par un.
  *Voix complète − voix sèche* = exactement ce que tes effets ajoutent. Eden traite la voix
  sèche, comme un mixeur qui reçoit des pistes sèches et met les effets en envoi, puis remet
  tes effets **tels quels** par-dessus.
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
  que la voix. Sinon la voix sèche est écartée et Eden le dit. En amont, `eden fl-probe`
  vérifie sur ton PC que FL respecte un slot d'effet désactivé (écart au-dessus de −60 dB
  entre les rendus avec et sans l'effet, choix d'Eden), quand une piste de la playlist du
  projet testé passe par une reverb ou un delay dont FL a enregistré l'état ; sinon ce
  point est noté « non vérifié sur ce projet ».
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
  repère plus, et la moyenne court alors sur plusieurs phrases.
- **Chaque groupe** du Mixer qui sort au Master sans voix (808, batterie, instru…).
- **Le reste** = mix d'origine (avant Master) − voix − groupes.

À **0 %**, le résultat est exactement ton mix d'origine, bit pour bit (vérifié par un test).

## 1. Le morceau

| Quoi | Comment | Sert à |
|---|---|---|
| Accordage | écart de l'instru au La 440 Hz, mode d'un histogramme au cent près des pics spectraux, mesuré **avant** le chroma (sourcé : méthode d'Essentia) ; ramené au demi-ton le plus proche, de −50 à +50 cents (choix d'Eden : Essentia replie de −35 à +65 cents, ce qui lit une instru à 430 Hz un demi-ton trop bas) | lire les notes sur la bonne grille (une instru en 432 Hz est lue juste) |
| Tonalité | chroma des pics au-dessus de **200 Hz** (kick, 808 et lignes de basse brouillent le chroma ; Faraldo, sourcé) des parties harmoniques : instru complète, éléments musicaux, effets, inconnus et reste du mix, sans les groupes batterie et 808 (quand tous les groupes sont batterie ou 808 : tout le beat) ; corrélation avec trois profils (Krumhansl-Kessler, Shaath, edma ; valeurs sourcées sur Essentia) ; Temperley écarté (penche vers le majeur relatif, sourcé). Quand majeur et mineur relatifs sont proches (scores à moins de 0,1), le 808 tranche s'il joue vraiment une des deux toniques : au moins 10 % de son énergie grave et 1,5 fois plus que l'autre (choix d'Eden) ; sinon les deux sont affichées | affichage, contrôle des notes du 808 |
| Tempo | tempo du projet FL ; pulsation « ressentie » ramenée entre 65 et 135 BPM (corpus MCFlow de rap : 79–124 BPM, non vérifié ; la trap écrite à 140 se ressent à 70) | delays, pré-delay, relâchements, phrases |
| Notes du 808 | NSDF (McLeod & Wyvill) sur la bande < 200 Hz décimée de tous les groupes basse / 808 réunis, notes de 25 à 150 Hz, affinage parabolique ; les trames d'un glissando (> 30 cents en 60 ms) sont ignorées : les hauteurs qu'un slide traverse ne sont pas des notes | note principale, notes hors gamme (averties, jamais corrigées ; ≥ 0,5 s et ≥ 3 % du jeu du 808), désaccord > 25 cents |
| Kick / 808 | attaques du kick sous 150 Hz, sur tous les groupes batterie réunis (FL rend souvent chaque élément sur son propre insert) : montée de 4 dB en 20 ms, à moins de 12 dB des plus forts (ghost kicks compris) ; part des kicks qui tombent sur une note de 808, et de combien le 808 baisse déjà après le kick, mesuré contre sa propre décroissance | décider d'un ducking |
| Graves en stéréo | corrélation G/D sous 100 Hz | mono des graves au master |

## 2. La chaîne de chaque voix

Ordre des chaînes rap publiées (Lil Baby / Tillie, Jaycen Joshua, Polo G / Todd Hurtt, Mike
Senior — *Sound On Sound*, **non vérifié**) : correction de hauteur (déjà dans FL) →
coupe-bas → résonances fixes → bas-médiums → de-esser léger → compression de niveau →
compression des crêtes → compression parallèle → saturation → air / recul → de-esser
principal → gain de compensation.

Chaque étape a sa mesure déclencheuse et son plafond. Les étapes dynamiques fixent leur seuil
**sur le signal qu'elles reçoivent vraiment** (après les étapes d'avant) ; une étape qui ne
réduirait nulle part plus de 0,3 dB n'est pas appliquée et n'apparaît pas dans le rapport.
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

| Étape | Mesure | Eden agit si… | Traitement à 100 % | Statut |
|---|---|---|---|---|
| Coupe-bas | énergie **une octave sous la coupe prévue**, là où le filtre retire 12 dB ou plus (spectre au hertz près) ; note la plus grave (5ᵉ centile du F0) | > −32 dB de l'énergie de la voix | 80 Hz lead, 130 Hz doublages / ad-libs, 160 Hz chœurs, **jamais au-dessus de 0,9 × la note la plus grave** | fréquences non vérifiées (Jaycen Joshua ~50 Hz, Lil Baby ~70 Hz) ; « coupe-bas partout » est une idée fausse (Pestana & Reiss 2014) : d'où le déclencheur ; règle du F0, mesure et seuil : choix d'Eden (juste sous la coupe, la voix elle-même sonne encore : notes sous le 5ᵉ centile, attaques des syllabes. Voix de test : propres, −33,9 dB au plus ; avec un grondement à −54 dBFS RMS, −31,5 dB au moins ; un grondement plus faible ne se distingue pas des attaques d'une voix grave) |
| Résonances fixes | 150–2000 Hz : chaque harmonique du chant comparée à la droite (dB contre log f) de ses voisines au même instant, jusqu'à une octave de chaque côté, en moyenne sur le chant (une fondamentale n'a pas de voisine en dessous : les notes ne sont jamais jugées) ; 2–8 kHz : enveloppe LPC moyenne | 150–2000 Hz : ≥ 4,5 dB sur 1/8 d'octave **et** 4,5 dB au-dessus des bandes à 1/6–1/3 d'octave (un formant de voyelle bouge et s'étale) ; 2–8 kHz : ≥ 4,5 dB au-dessus de la moyenne sur une octave ; pas sur une note tenue | coupes étroites (Q 6), −4 dB max, 3 au plus, à 1/3 d'octave l'une de l'autre au moins | atténuer les résonances saillantes : sourcé (Pestana & Reiss 2014) ; méthode et seuils : choix d'Eden |
| Bas-médiums | même mesure des harmoniques, moyennée sur un tiers d'octave, entre 150 et 500 Hz, seulement là où des harmoniques ont été mesurées (à 1/16 d'octave près) ; et 200–500 Hz vs 1–4 kHz (spectre moyen) | bosse ≥ 2,5 dB et écart > 6 dB, pas sur une note tenue, ni à moins d'1/3 d'octave d'une coupe de résonance | −2,9 à −4 dB, Q 1,2, à la fréquence de la bosse | une coupe aveugle des bas-médiums n'est **pas** une pratique d'expert (Pestana & Reiss 2014, sourcé) : seulement sur une vraie bosse ; seuils : choix d'Eden |
| De-esser léger | niveau des « s » les plus forts (90ᵉ centile) **dans la bande du de-esser** vs voyelles (75ᵉ centile) : ce que le de-esser compare à son seuil ; pic spectral des « s » | « s » à moins de 1 dB sous les voyelles | seuil = voyelles − 2 dB, 3 dB max, bande dès 0,7 × le pic des « s » (3,5–8 kHz ; 4,5 kHz sans pic mesuré), anticipation 5 ms | deux de-essers (avant / après compression) : non vérifié (Senior) |
| Compression de niveau | écart P90 − P10 des blocs de 400 ms **à l'intérieur des phrases** | > 4 dB | 1,5:1 (écart de 4 dB) à 3:1 (10 dB et plus), attaque 10 ms, relâchement 60 ms puis 800 ms après 200 ms de réduction (type opto), seuil pour 3 dB sur le P90 du chant | chiffres non vérifiés (SOS, LA-2A) ; choix d'Eden |
| Compression des crêtes | facteur de crête | > 9 dB | 4:1, attaque 2 ms, relâchement 80 ms, 6 dB max, 3 dB sur le P97 | non vérifié (1176) ; choix d'Eden |
| Parallèle | facteur de crête | > 12 dB, voix principale et ad-libs (jamais sur une voix prudente) | copie 8:1, 100 Hz – 5 kHz, mélangée à 20 % (ad-libs 10 %), alignée à l'échantillon | pratique non vérifiée (bus parallèle des sessions rap) |
| Saturation | — | toujours | tanh suréchantillonné ×4, de 200 Hz jusqu'au début de la bande des « s », 15 % (ad-libs 20 %, autres 10 %), même couleur quel que soit le volume rendu | non vérifié ; choix d'Eden |
| Air | > 8 kHz vs 2–5 kHz sur les voyelles | < −25 dB | +1,5 dB au-dessus de 10 kHz | choix d'Eden |
| Recul | — (doublages, chœurs, ad-libs) | toujours | −1,5 à −2 dB au-dessus de 7 kHz | choix d'Eden |
| De-esser principal | « s » dans la bande du de-esser vs voyelles | « s » à moins de 5 dB sous les voyelles | seuil = voyelles − 6 dB, 2 à 6 dB (lead), jusqu'à 8 dB (autres), même bande | non vérifié (Pro-DS en fin de chaîne) |
| Gain de compensation | volume BS.1770 avant / après la chaîne | dès qu'un compresseur ou un de-esser agit | rend à la voix le volume que la chaîne lui a pris | le niveau de la voix dans le mix est ensuite décidé sur une mesure, à un seul endroit |

## 3. Niveaux et suivi

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
- **Voix restée hors de sa fenêtre** : l'intensité règle la part du changement qu'Eden fait
  (à 50 %, la moitié). Si, ce changement fait, la voix reste hors de sa fenêtre (un gain
  statique déplace l'équilibre d'autant de dB), Eden le signale dans les avertissements avec
  l'écart qui reste, par exemple « « Lead » reste à -6.2 dB de l'instru pendant qu'elle
  chante, niveau d'Eden compris (visé +1 dB, accepté de -1 à +4 dB) : monte la voix ou
  baisse l'instru dans FL Studio », précédé de « À cette intensité, » sous 100 %. Le suivi
  phrase par phrase ne corrige pas cet écart : il garde l'équilibre médian de la voix.
- **Voix principales qui chantent ensemble** (prises empilées d'un refrain, piste dupliquée) :
  deux voix chantent ensemble quand celle qui chante le moins partage au moins la moitié de
  ses blocs chantés avec l'autre (choix d'Eden), de proche en proche. Leur somme est réglée
  contre l'instru comme une seule voix, avec la même cible et le même maximum de 10 dB, et
  elles reçoivent le même gain statique : ce réglage ne change pas leur équilibre entre elles
  (le suivi phrase par phrase, ensuite, se fait voix par voix). Seule exception : une voix
  principale qui copie une autre (corrélation > 0,8 à ±40 ms) n'est jamais montée. Quand deux
  voix se copient l'une l'autre (piste dupliquée), la première dans l'ordre du projet compte
  comme l'originale et reçoit le gain ; seule l'autre est gardée à son niveau, et la somme
  est alors mesurée à nouveau pour l'avertissement.
- **Suivi phrase par phrase** (« vocal riding », pratique d'expert sourcée : Pestana & Reiss
  2014) : phrases = plages de chant d'au moins 0,3 s séparées d'au moins une croche du tempo
  ressenti ; l'instru est mesurée **au-dessus de 200 Hz**, la bande qui couvre les paroles (le
  sub d'un 808 les masque à peine ; choix d'Eden) ; référence = l'équilibre médian de la voix
  sur tout le morceau (pas une valeur fixe) ; une phrase à plus de 1,5 dB de cette référence
  est ramenée, ±6 dB max (plage par défaut d'un Vocal Rider, non vérifié). La voix n'est
  **jamais baissée parce que l'instru se retire** : une phrase où l'instru est à plus de 6 dB
  sous sa phrase médiane (break, filtre, beat coupé pour une punchline) est laissée telle
  quelle et ne compte pas dans la référence, et une phrase n'est baissée que de ce dont la voix
  elle-même dépasse sa phrase médiane (6 dB et cette règle : choix d'Eden). Le gain tient
  pendant le silence et change dans les 120 ms qui précèdent la phrase suivante (les silences
  du rap durent le plus souvent une double croche, ~180 ms : MCFlow, non vérifié).
- **Doublages / ad-libs / chœurs** par rapport à la voix principale : −6 (−10 à −3), −6
  (−9 à −3), −7 (−10 à −4) dB (moyennes de blogs, **non vérifié**), changement statique
  4 dB max ; hors de leur fenêtre une fois ce changement fait, Eden le signale aussi
  (« monte cette voix » ou « baisse cette voix dans FL Studio »). Un doublage **copie** de
  la voix principale (corrélation > 0,8 à ±40 ms, choix d'Eden) n'est jamais remonté
  (filtrage en peigne), et rien n'est signalé : c'est voulu.

## 4. Espace

Rien n'est ajouté à une voix qui porte déjà une reverb ou un delay FL. Pour les autres,
les « quatre envois » d'un lead rap devant mais collé au beat (architecture non vérifiée,
synthèse de la recherche ; niveaux : choix d'Eden) :

| Envoi | Réglage | Niveau (sous la voix, avant ducking) |
|---|---|---|
| Ambiance | 80 ms, pré-delay 8 ms, 400 Hz – 6 kHz | −23 dB |
| Plate | 0,8 à 1,4 s (≈ 2 temps ressentis), pré-delay = 1/64 ou 1/32 le plus proche de 45 ms, borné 20–80 ms, 300 Hz – 6 kHz, baissée de 2,5 dB pendant le chant | −19 dB |
| Delay 1/8 | ping-pong, feedback 0,25, 400 Hz – 4 kHz, baissé de 10 dB pendant le chant ; remonte en un quart du temps de delay, pour que le premier écho après la phrase s'entende en entier | −21 dB |
| Jet d'écho (lead) | 1/4, feedback 0,35, envoyé seulement sur la fin d'une phrase suivie d'un silence | −12 dB |

- Voix secondaires : mêmes envois 4 dB plus présents (plus loin).
- L'envoi est dé-essé une fois (8 dB) avant tous les effets : un « s » répété n'est que du
  bruit.
- Les niveaux sont réglés sur le volume BS.1770 de la voix sèche, pas sur ses crêtes.
- **Plafond** : la reverb de tout le morceau, **tes effets FL compris**, reste ≤ −16 LU par
  rapport au mix sec. Sourcé : De Man, McNally & Reiss 2017, 80 mixes : à −9 LU ou plus,
  toujours jugé trop mouillé ; −14 LU plus souhaitable. Le rap se tient plus sec : choix
  d'Eden. Si le plafond est dépassé, seuls les effets d'Eden baissent ; les tiens ne sont
  jamais touchés.
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
- Panoramique à puissance constante. Valeurs de placement : choix d'Eden.

## 6. Place pour les paroles et basses

- **Démasquage** : dans chaque bande de tiers d'octave centrée de 250 Hz à 8 kHz, Eden
  mesure l'instru moins la voix pendant le chant. Une bande où l'instru est 3 dB ou plus
  sous la voix n'a pas besoin de creux ; les autres baisseraient, à 100 %, de 1 dB (instru
  3 dB sous la voix) à 3 dB (instru 3 dB au-dessus ou plus). Sont écartées celles que
  l'instru couvre de plus de 12 dB (un creux de 3 dB n'y découvre rien) et celles où la
  voix est à plus de 20 dB sous sa bande la plus forte (elle n'y a presque rien) : 12 et
  20 dB, choix d'Eden. Au plus 3 bandes sont gardées : celles où le creux rend le plus de
  paroles audibles, soit l'importance de la bande pour l'intelligibilité (ANSI S3.5,
  1–4 kHz ≈ 72 % du poids, sourcé ; chaque tiers reçoit le tiers du poids de son octave)
  × l'audibilité gagnée, l'audibilité d'une bande valant 0 quand la voix est 15 dB sous
  l'instru, 1 à partir de 15 dB au-dessus, et montant en ligne droite entre les deux
  (ANSI S3.5, non vérifié sur le texte de la norme). Dans les bandes retenues (instru de
  3 dB sous la voix à 12 dB au-dessus), l'audibilité n'atteint jamais 0 ni 1 : l'audibilité
  gagnée vaut la profondeur du creux divisée par 30, et le classement revient à importance
  × profondeur. Le creux ne joue que quand la voix chante (méthode de Hafezi & Reiss 2015,
  sourcé). L'instru est creusée là où elle a été mesurée : dans les groupes et dans le
  reste du mix (une instru qui passe par un bus partagé avec les voix s'y retrouve). Quand
  des voix sont restées dans le reste du mix (au-delà des 16 voix qu'Eden fait rendre une
  par une), seuls les groupes sont mesurés et creusés : creuser le reste baisserait aussi
  ces voix ; le motif du creux le dit. Le creux est affiché sur les groupes, et sur une
  ligne « Reste du mix », quand ils portent au moins 25 % de ce qu'il retire (choix
  d'Eden). Fait **avant** l'équilibre, pour que la voix soit réglée sur l'instru telle
  qu'on l'entendra. Doublages, chœurs et ad-libs baissent de 2 dB entre 1 et 4 kHz aux
  mêmes moments (choix d'Eden) : un doublage chante sous la voix principale. Seule la voix
  baisse : ses reverbs et delays FL rendus à part restent tels quels (sur une voix
  « prudente », ils sont dans la voix et baissent avec elle).
- **Kick / 808** : si plus d'un kick sur deux (lus sur tous les groupes batterie réunis)
  tombe sur une note de 808 qui ne baisse pas déjà (< 2 dB), chaque groupe basse / 808 est
  baissé de 3 dB sous 100 Hz à chacun de ces kicks : descente en 5 ms
  (cosinus, sans clic) avant l'attaque, tenue 30 ms, remontée 100 ms. Filtre à phase nulle :
  au-dessus de 100 Hz, le 808 (sa distorsion, ses harmoniques) est intact. Jamais plus : les
  ingénieurs sont partagés sur le ducking, Eden reste conservateur.
- **808 nu** (harmoniques 2–5 à plus de 20 dB sous la fondamentale, mesurées sur tous les
  groupes basse / 808 réunis) : harmoniques générées, dans chacun de ces groupes, depuis
  sa bande sub seule, note par note (enveloppe normalisée), pour que l'oreille
  reconstruise la note à partir des harmoniques 3 à 5 (fondamentale manquante) ; filtrées
  80–400 Hz, 14 dB sous la fondamentale (choix d'Eden), pour qu'un téléphone entende la note.

## 7. Mastering Eden

Chaîne (tout hors ligne, en float64) :

1. graves en mono sous 100 Hz si la corrélation G/D y est < 0,9 (filtre à phase nulle) ;
2. tenue des graves : 2:1 sous 100 Hz, ≤ 3 dB, attaque 10 ms, si les notes graves varient de
   plus de 4 dB d'une note à l'autre (choix d'Eden). Une note = une crête de l'enveloppe des
   graves (moyenne sur 25 ms) qui ressort d'au moins 6 dB, à au moins 120 ms de la précédente
   et à moins de 30 dB de la plus forte ; l'écart est pris du 10ᵉ au 90ᵉ centile de ces
   crêtes, sur au moins 4 notes (choix d'Eden). La décroissance d'une note n'est donc pas un
   écart entre notes. Une note n'est comptée que si l'enveloppe redescend de 6 dB autour
   d'elle : une note plus faible qui démarre sur la queue encore forte de la précédente, ou des
   notes tenues qui s'enchaînent sans creux, ne ressortent pas et ne sont pas comparées ;
3. compression de bus : 1,6:1, seuil 4 dB sous les passages forts (P90), attaque 30 ms,
   relâchement sur le temps ressenti, ≤ 3 dB (≈ 1,5 dB sur les passages forts) ;
4. gain → clip doux suréchantillonné ×8 (arrondi à partir de 70 % du plafond du clip,
   plafond du clip à −1 dBFS, ou −2 dBFS avec un plafond final à −3 dBTP) → limiteur
   true-peak (sur la crête de l'onde continue, anticipation 1,5 ms : le gain descend en rampe
   sur au moins 1,5 ms avant une crête, jamais d'un coup ; tenue 20 ms pour ne pas onduler
   dans un cycle de 808) au plafond final.

Comme pour les voix, une compression qui ne réduirait nulle part plus de 0,3 dB n'est pas
appliquée et n'apparaît pas dans le rapport ; celles qui agissent affichent la réduction
mesurée (moyenne quand elles agissent, et maximum).

- **Cible : −9 LUFS** intégrés (« fort, comme le rap commercial », ton choix). Les charts se
  tiennent vers −8 LUFS (iZotope 2024, non vérifié). Au-delà, rien n'est gagné sur les
  plateformes, qui baissent les morceaux forts, et la distorsion d'encodage augmente. Le gain
  est visé sur une estimation rapide (le clip et la loi du limiteur sans suréchantillonnage) ;
  une première passe réelle mesure l'écart entre l'estimation et la vraie chaîne, et le gain
  est visé à nouveau avec cet écart. Deux passes réelles suffisent le plus souvent, trois au
  plus ; une quatrième n'a lieu que si la troisième dépasse encore le budget.
- **Budget de réduction** (choix d'Eden) : clip + limiteur ne baissent pas de plus de
  **9 dB** les crêtes qui reviennent dans le morceau, mesurées par blocs de 50 ms (le 98,5ᵉ
  centile des blocs réduits de plus de 0,5 dB, sans dépasser le 10ᵉ bloc le plus réduit :
  un clic, une plosive ou un seul impact au drop ne décident pas du volume de tout le
  morceau). Un événement isolé peut aller jusqu'à **13 dB** sur 30 ms (trois blocs de 10 ms
  de suite). Plus court, un clic écrêté reste un clic : sa réduction est affichée, pas
  comptée. Au-delà du budget, Eden baisse le gain de l'excès et le dit : « les crêtes qui
  reviennent » quand ce sont elles, ou le moment de l'événement isolé. Après une baisse, il
  remonte une fois s'il reste au moins 0,3 dB de budget.
- **Plafond** : −2 dBTP (Spotify demande ≤ −2 dBTP pour un master plus fort que −14 LUFS :
  non vérifié, cohérent avec AES TD1008). À −9 LUFS, −2 dBTP laisserait moins de 8 dB entre
  crête et volume. Sur un master aussi dense, Opus 96k et MP3 128k dépassent de 1,2 à 2,2 dB
  à l'encodage (sourcé : essais d'encodage reproduits deux fois indépendamment). Un master à
  −9 LUFS reçoit donc **−3 dBTP**, c'est le cas normal. Si le budget arrête le master plus
  bas, le plafond est choisi à nouveau sur le volume atteint : quand, à −2 dBTP, le même master
  (1 dB plus haut, exactement : toute la chaîne suit le plafond) laisse encore au moins 8 dB
  entre crête et volume, il passe à −2 dBTP.
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
- Pas encore de lecteur intégré pour écouter et comparer avant/après dans Eden.
