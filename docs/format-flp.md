# Notes sur le format .flp

Le format n'est pas documenté par Image-Line. Ces notes listent ce qu'Eden lit et
comment chaque point a été vérifié. Référence : projet sauvegardé par FL Studio 20.8.4
(`tools/fetch_test_assets.py`), comparé à PyFLP 2.2.1 (Python 3.10).

## Conteneur

```
"FLhd" u32=6  i16 format  u16 nb_canaux  u16 PPQ
"FLdt" u32 taille  [événements]
```

Événement = 1 octet d'identifiant, puis : 0–63 → 1 octet ; 64–127 → 2 ; 128–191 → 4 ;
192–255 → longueur en varint (LEB128) + données. Les textes sont en UTF-16LE depuis
FL 11.5 (la version elle-même est en ASCII).

## Ordre observé (FL 20.8)

infos projet → patterns → canaux → arrangements (playlist, pistes, marqueurs) →
paramètres du Mixer → inserts.

## Points vérifiés

| Donnée | Événement | Remarque |
|---|---|---|
| Version / build | 199 / 159 | |
| Tempo | 156 | BPM × 1000 |
| Mesure | 17 / 18 | |
| Création, temps passé | 237 | 2 × float64, dates Delphi (jours depuis 30/12/1899) |
| Nouveau canal | 64 | valeur = index |
| Type de canal | 21 | 0 sampler, 2 natif, 3 layer, 4 instrument/clip audio, 5 automation |
| Insert de destination | 22 | numérotation FL (0 = Master) |
| Volume / pan canal | 219 | i32 pan (0–12800, 6400 = centre), u32 volume (défaut 10000) |
| Chemin du sample | 196 | |
| Plugin : nom interne / nom affiché / données | 201 / 203 / 213 | |
| VST (Fruity Wrapper) | 213 | u32 type puis enregistrements `u32 id, u64 taille` : 54 nom, 55 chemin, 56 éditeur, 51 FourCC (VST2), 52 GUID (VST3), 53 état opaque |
| Insert | 204 nom, 236 drapeaux, 235 routage, 147 fin d'insert | le 1er insert est le Master |
| Drapeaux d'insert (2e u32 de 236) | bit 0 polarité, 1 inversion G/D, 2 effets actifs, 3 insert actif, 11 verrouillé | |
| Slot d'effet | événements plugin puis 98 (fin de slot) | 10 slots par insert |
| Paramètres du Mixer | 225 | enregistrements de 12 octets ; insert = (canal >> 6) & 0x7F, slot = canal & 0x3F ; id 0 slot actif, 1 dry/wet, 64–191 niveau d'envoi vers l'insert (id − 64), 192 volume, 193 pan, 194 séparation stéréo |
| Playlist | 233 | 32 octets par clip, 60 depuis FL 21, 80 depuis FL 2024 (24), 88 en FL 26 : les 32 premiers ne changent pas (relevé par le fork Meowrium/PyFLP et par flpkit ; pas encore vérifié sur un projet FL 25 réel). Taille de la version essayée d'abord, chaque clip validé par la base des patterns 20480 à l'offset 4 ; piste stockée inversée (499 − n) |
| Piste de playlist | 238 données (activée = octet 12), 239 nom (après ses données) | |
| Marqueurs | 148 position (octet haut = type, 8 = signature), 205 nom | |
| Notes de pattern | 224 | 24 octets par note, canal du rack en u16 à l'offset 6 |

## Observations à confirmer sur des projets plus récents

- Les inserts ont par défaut des routes vers 100–103 avec un niveau d'envoi à 0 dans le
  projet de test : Eden les considère comme inaudibles.
- Le bit 13 des drapeaux d'insert est présent sur un insert « Audio track » : sens non confirmé, ignoré.
- Unité des décalages de début/fin des clips audio : non confirmée, valeurs brutes conservées.
- Clips d'automation : cible non décodée.
