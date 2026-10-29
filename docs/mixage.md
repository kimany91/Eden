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
- **Chaque voix sèche** : si sa chaîne FL contient une reverb ou un delay, FL la rend aussi
  avec ces effets coupés. Un retour d'effet est reconnu par la topologie du Mixer (un insert
  autre que celui de la voix, qui porte une reverb ou un delay, et dont la voix n'a pas besoin
  pour atteindre le Master) : il est coupé en entier, limiteur ou EQ compris. Sur le chemin
  propre de la voix, les slots de reverb et de delay sont désactivés un par un.
  *Voix complète − voix sèche* = exactement ce que tes effets ajoutent. Eden traite la voix
  sèche, comme un mixeur qui reçoit des pistes sèches et met les effets en envoi, puis remet
  tes effets **tels quels** par-dessus.
- **Contrôle de la voix sèche** : pendant le chant, elle doit être calée sur la voix complète
  (un plugin contourné peut changer la compensation de latence de FL) ; la part des effets
  ne doit contenir ni la voix elle-même (un retour qui laisse passer l'envoi sec, un plugin
  dont le bouton dry/wet baisse aussi la voix), ni être plus forte que la voix. Sinon la voix
  sèche est écartée et Eden le dit.
- **Voix « prudente »** : quand la séparation est impossible (état d'un slot non enregistré
  par FL) ou écartée, la réduction est limitée à 3 dB, sans compression parallèle, et le gain
  est figé dans les silences entre phrases (silence = au moins une double croche du tempo
  ressenti) à la réduction **moyenne** de la phrase qui précède : tes queues de reverb ou
  d'écho gardent leur niveau par rapport à la voix.
- **Chaque groupe** du Mixer qui sort au Master sans voix (808, batterie, instru…).
- **Le reste** = mix d'origine (avant Master) − voix − groupes.

À **0 %**, le résultat est exactement ton mix d'origine, bit pour bit (vérifié par un test).

## 1. Le morceau

| Quoi | Comment | Sert à |
|---|---|---|
| Accordage | écart de l'instru au La 440 Hz, mode d'un histogramme au cent près des pics spectraux, mesuré **avant** le chroma (sourcé : méthode d'Essentia) | lire les notes sur la bonne grille (une instru en 432 Hz est lue juste) |
| Tonalité | chroma des pics au-dessus de **200 Hz** (kick, 808 et lignes de basse brouillent le chroma ; Faraldo, sourcé), corrélation avec trois profils (Krumhansl-Kessler, Shaath, edma ; valeurs sourcées sur Essentia) ; Temperley écarté (penche vers le majeur relatif, sourcé). Quand majeur et mineur relatifs sont proches, les notes du 808 tranchent | affichage, contrôle des notes du 808 |
| Tempo | tempo du projet FL ; pulsation « ressentie » ramenée entre 65 et 135 BPM (corpus MCFlow de rap : 79–124 BPM, non vérifié ; la trap écrite à 140 se ressent à 70) | delays, pré-delay, relâchements, phrases |
| Notes du 808 | NSDF (McLeod & Wyvill) sur la bande < 200 Hz décimée, notes de 25 à 150 Hz, affinage parabolique ; les trames d'un glissando (> 30 cents en 60 ms) sont ignorées : les hauteurs qu'un slide traverse ne sont pas des notes | note principale, notes hors gamme (averties, jamais corrigées ; ≥ 0,5 s et ≥ 3 % du jeu du 808), désaccord > 25 cents |
| Kick / 808 | attaques du kick (montée de 4 dB en 20 ms, à moins de 12 dB des plus forts : ghost kicks compris) ; part des kicks qui tombent sur une note de 808, et de combien le 808 baisse déjà après le kick, mesuré contre sa propre décroissance | décider d'un ducking |
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
Une voix propre ne reçoit que la saturation, plus la compression des crêtes si ses attaques
dépassent.

| Étape | Mesure | Eden agit si… | Traitement à 100 % | Statut |
|---|---|---|---|---|
| Coupe-bas | énergie < 70 Hz (lead) ou < 120 Hz (autres) ; note la plus grave (5ᵉ centile du F0) | > −25 dB de l'énergie | 80 Hz lead, 130 Hz doublages / ad-libs, 160 Hz chœurs, **jamais au-dessus de 0,9 × la note la plus grave** | fréquences non vérifiées (Jaycen Joshua ~50 Hz, Lil Baby ~70 Hz) ; « coupe-bas partout » est une idée fausse (Pestana & Reiss 2014) : d'où le déclencheur ; règle du F0 : choix d'Eden |
| Résonances fixes | bosses de l'enveloppe LPC moyenne (les notes et l'Auto-Tune ne la déclenchent pas) | ≥ 4,5 dB au-dessus du voisinage | coupes étroites (Q 6), −4 dB max | atténuer les résonances saillantes : sourcé (Pestana & Reiss 2014) ; seuils : choix d'Eden |
| Bas-médiums | bosse de l'enveloppe entre 150 et 500 Hz, et 200–500 Hz vs 1–4 kHz | bosse ≥ 2 dB et écart > 6 dB | −2,5 à −4 dB, Q 1,2, à la fréquence de la bosse | une coupe aveugle des bas-médiums n'est **pas** une pratique d'expert (Pestana & Reiss 2014, sourcé) : seulement sur une vraie bosse |
| De-esser léger | niveau des « s » les plus forts vs voyelles ; pic spectral des « s » | « s » à moins de 1 dB sous les voyelles | seuil = voyelles − 2 dB, 3 dB max, bande dès 0,7 × le pic des « s » (3,5–8 kHz), anticipation 5 ms | deux de-essers (avant / après compression) : non vérifié (Senior) |
| Compression de niveau | écart P90 − P10 des blocs de 400 ms **à l'intérieur des phrases** | > 4 dB | 2:1 à 3:1, attaque 10 ms, relâchement 60 ms puis 800 ms après 200 ms de réduction (type opto), seuil pour 3 dB sur le P90 du chant | chiffres non vérifiés (SOS, LA-2A) ; choix d'Eden |
| Compression des crêtes | facteur de crête | > 9 dB | 4:1, attaque 2 ms, relâchement 80 ms, 6 dB max, 3 dB sur le P97 | non vérifié (1176) ; choix d'Eden |
| Parallèle | facteur de crête | > 12 dB (jamais sur une voix prudente) | copie 8:1, 100 Hz – 5 kHz, mélangée à 20 % (ad-libs 10 %), alignée à l'échantillon | pratique non vérifiée (bus parallèle des sessions rap) |
| Saturation | — | toujours | tanh suréchantillonné ×4, de 200 Hz jusqu'au début de la bande des « s », 15 % (ad-libs 20 %, autres 10 %), même couleur quel que soit le volume rendu | non vérifié ; choix d'Eden |
| Air | > 8 kHz vs 2–5 kHz sur les voyelles | < −25 dB | +1,5 dB au-dessus de 10 kHz | choix d'Eden |
| Recul | — (doublages, chœurs, ad-libs) | toujours | −1,5 à −2 dB au-dessus de 7 kHz | choix d'Eden |
| De-esser principal | « s » vs voyelles | « s » à moins de 5 dB sous les voyelles | seuil = voyelles − 6 dB, 2 à 6 dB (lead), jusqu'à 8 dB (autres), même bande | non vérifié (Pro-DS en fin de chaîne) |
| Gain de compensation | volume BS.1770 avant / après la chaîne | dès qu'un compresseur ou un de-esser agit | rend à la voix le volume que la chaîne lui a pris | le niveau de la voix dans le mix est ensuite décidé sur une mesure, à un seul endroit |

## 3. Niveaux et suivi

- **Voix principale** : volume K-pondéré de la voix moins celui de l'instru, **pendant
  qu'elle chante** ; cible **+1 dB**, fenêtre −1 à +4 dB (**choix d'Eden**), changement
  statique 4 dB max. Repères : les experts placent la voix principale à peu près au volume
  de tout le reste réuni (≈ 0 dB, Pestana & Reiss 2014, sourcé) ; les autres voix étant
  réglées ensuite vers −6 dB sous elle, +1 dB contre l'instru seule retombe près de 0 dB
  contre tout le reste. La mesure BS.1770 lit une voix environ 2 LU plus bas qu'on ne
  l'entend (Pestana & Reiss 2013, non vérifié en texte intégral). Le classement du rap
  parmi les genres « voix devant » (Gerdes & Siedenburg 2023) et la préférence des auditeurs
  pour une voix 3 à 6 dB plus forte (Knoll & Siedenburg 2022) n'ont pas pu être ouverts.
- **Suivi phrase par phrase** (« vocal riding », pratique d'expert sourcée : Pestana & Reiss
  2014) : phrases = plages de chant d'au moins 0,3 s séparées d'au moins une croche du tempo
  ressenti ; référence = l'équilibre médian de la voix sur tout le morceau (pas une valeur
  fixe) ; une phrase à plus de 1,5 dB de cette référence est ramenée, ±6 dB max (plage par
  défaut d'un Vocal Rider, non vérifié). Le gain tient pendant le silence et change dans les
  120 ms qui précèdent la phrase suivante (les silences du rap durent le plus souvent une
  double croche, ~180 ms : MCFlow, non vérifié).
- **Doublages / ad-libs / chœurs** par rapport à la voix principale : −6 (−10 à −3), −6
  (−9 à −3), −7 (−10 à −4) dB (moyennes de blogs, **non vérifié**). Un doublage **copie** de
  la voix principale (corrélation > 0,8 à ±40 ms, choix d'Eden) n'est jamais remonté
  (filtrage en peigne).

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

## 5. Stéréo

- Voix principale : au centre, jamais touchée (pratique d'expert sourcée).
- Doublages : une paire de vraies prises → ±85 % ; un doublage seul → centre ; une copie
  de la voix principale → centre.
- Chœurs : ±55 % en paires (un seul : ±40 %). Ad-libs : ±50 %, **chaque phrase change de
  côté** au milieu du silence (fondu 50 ms), jamais au centre pendant la voix principale.
- Une voix déjà élargie ou placée dans FL (side > −20 dB du mid) est laissée telle quelle.
- Panoramique à puissance constante. Valeurs de placement : choix d'Eden.

## 6. Place pour les paroles et basses

- **Démasquage** : bandes de tiers d'octave (250 Hz – 8 kHz) où l'instru couvre le plus la
  voix pendant le chant, pondérées par leur importance pour l'intelligibilité (ANSI S3.5,
  1–4 kHz ≈ 72 % du poids, sourcé) : les 3 premières baissent de 1 à 3 dB dans l'instru,
  seulement quand la voix chante (méthode de Hafezi & Reiss 2015, sourcé). Fait **avant**
  l'équilibre, pour que la voix soit réglée sur l'instru telle qu'on l'entendra. Chœurs et
  ad-libs baissent de 2 dB entre 1 et 4 kHz aux mêmes moments.
- **Kick / 808** : si plus d'un kick sur deux tombe sur une note de 808 qui ne baisse pas
  déjà (< 2 dB), le 808 est baissé de 3 dB sous 100 Hz à chaque kick : descente en 5 ms
  (cosinus, sans clic) avant l'attaque, tenue 30 ms, remontée 100 ms. Filtre à phase nulle :
  au-dessus de 100 Hz, le 808 (sa distorsion, ses harmoniques) est intact. Jamais plus : les
  ingénieurs sont partagés sur le ducking, Eden reste conservateur.
- **808 nu** (harmoniques 2–5 à plus de 20 dB sous la fondamentale) : harmoniques générées
  depuis la bande sub seule, note par note (enveloppe normalisée), pour que l'oreille
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
   écart entre notes ; une note plus faible qui démarre sur la queue encore forte de la
   précédente peut ne pas ressortir de 6 dB, et n'est alors pas comptée ;
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
  plafond moins volume : 6 dB à −9 LUFS et −3 dBTP, d'où 5,5 dB ; un master plus calme ne
  l'est que sous 7,5 dB ; choix d'Eden), perte en mono, **trous en mono** (une bande de tiers
  d'octave qui, en moyenne sur 2 s, perd plus de 6 dB en mono alors qu'elle porte au moins
  1 % de la puissance de ces 2 s ; un élément large et décorrélé perd 3 dB en moyenne et n'en
  est pas un), et ce que chaque plateforme fera du fichier : Spotify, YouTube, TIDAL, Amazon,
  SoundCloud −14 LUFS ; Deezer −15 ; Apple Music −16 (non vérifiés, cohérents entre eux) ; les
  morceaux forts sont baissés, Spotify ne remonte les faibles que jusqu'à −1 dBTP.

## Versions et export

- Chaque mixage est gardé : WAV final 32 bits flottant, et toutes les décisions avec leurs
  raisons (le morceau, le mastering et ses contrôles). Il peut être réaffiché puis exporté.
- L'export choisit le dossier, le nom, la fréquence et la profondeur : 16 bits avec dither
  TPDF, 24 bits, ou 32 bits flottant.
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
