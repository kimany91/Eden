# Le mixage d'Eden

Eden ne recrée aucun son. Il travaille sur ce que **FL Studio** a rendu, avec tous tes
effets, puis il repasse le résultat dans **ton Master FL** (ton mastering).

## Les morceaux du mix

- **Chaque voix seule**, rendue par FL avec toute sa chaîne (inserts, bus, envois) :
  Auto-Tune, delays, échos, reverbs y sont déjà.
- **Le reste** = le mix d'origine (avant Master) moins la somme des voix : instru, autres
  sources et ce que les bus ajoutent.

À **0 %**, la somme redonne exactement ton mix d'origine, et le passage dans ton Master
redonne exactement ton morceau. C'est vérifié à chaque fois.

## Ce qu'Eden mesure et quand il agit

Tout est mesuré sur la voix **après** tes effets FL : Eden ne corrige que ce qui reste à
corriger. Une voix propre n'est pas touchée.

| Problème | Mesure | Eden agit si… | Traitement (à 100 %) |
|---|---|---|---|
| Grondement, plosives | énergie sous 70 Hz (120 Hz pour backs, ad-libs, doublages) | > −25 dB de l'énergie de la voix | coupe-bas 80 Hz (110–120 Hz pour les autres voix) |
| Résonance de pièce ou de micro | bosse fixe dans l'enveloppe spectrale moyenne (prédiction linéaire, les notes chantées et l'Auto-Tune ne la déclenchent pas) | ≥ 4,5 dB au-dessus de l'octave voisine | coupe étroite, −3 dB maximum, 3 au plus |
| Son terne | bas-médiums (200–500 Hz) par rapport à la présence (1–4 kHz) | > 6 dB | −1,5 à −3 dB vers 300 Hz |
| Sifflantes | niveau des « s » par rapport aux voyelles | « s » à moins de 3 dB des voyelles | de-esser sur les aigus seulement, 8 dB maximum |
| Dynamique trop irrégulière | écart entre passages faibles et forts (P90 − P10, blocs de 400 ms) | > 7 dB, et voix pas déjà très compressée (facteur de crête > 10 dB) | compression 1,5:1 à 4:1, attaque 8 ms, relâchement 140 ms |
| Voix principale noyée ou trop forte | voix par rapport à l'instru **pendant qu'elle chante** | hors de −0,5 à +4 dB | vers +1,5 dB, 4 dB maximum |
| Backs, ad-libs, doublages | par rapport à la voix principale | backs hors de −10 à −4 dB ; ad-libs et doublages hors de −9 à −3 dB | vers −7 / −6 dB, 4 dB maximum |
| Instru qui masque les paroles | instru par rapport à la voix entre 1,5 et 4 kHz, pendant le chant | > −3 dB | baisse de 1 à 3 dB de cette zone de l'instru, seulement quand la voix chante |

L'**intensité** (0 à 100 %) règle la force de tous ces traitements à la fois.

Ensuite, le niveau du mix est remis au **même volume** que ton mix d'origine avant d'entrer
dans ton Master, pour que ton limiteur et ton mastering réagissent comme avant.

## Ce qui est vérifié à la fin

- Volume intégré (LUFS, norme ITU-R BS.1770) et crête réelle (dBTP) du morceau d'origine et
  du résultat.
- Avertissement si la crête réelle dépasse 0 dBTP en sortie de ton Master, ou si le volume
  final s'écarte de plus de 1 LU de l'original.

## Versions et export

Chaque mixage est gardé (le WAV final et toutes les décisions avec leurs raisons) et peut
être réaffiché puis exporté. L'export choisit le dossier, le nom, la fréquence (pas de
conversion si tu gardes celle de FL) et la profondeur de bits (16 bits avec dither,
24 bits, 32 bits flottant). Eden n'écrase jamais un fichier existant et refuse un export
16 ou 24 bits qui serait écrêté.

## Limites actuelles

- Les seuils ci-dessus sont des valeurs de départ pour le rap. Ils ont été vérifiés sur des
  voix de test aux défauts connus : une voix propre et une voix Auto-Tune ne reçoivent
  aucun traitement, et chaque défaut reçoit sa correction, qui le réduit vraiment. Ils
  doivent maintenant être ajustés à l'écoute, sur tes morceaux.
- Pas encore de lecteur intégré pour écouter et comparer avant/après dans Eden : il faut
  ouvrir le WAV exporté.
- Pas encore de saturation, de reverb ou de delay ajoutés par Eden, ni d'automation de
  volume phrase par phrase (phase 4b).
