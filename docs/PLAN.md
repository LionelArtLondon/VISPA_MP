# VISPA MP — plan de fiabilité et de vitesse

Suite du plan « Marqueurs Resolve automatiques » (`C:\Users\quero\.cursor\plans\marqueurs_resolve_automatiques_3194b41c.plan.md`). Ce plan-là est livré : pont Resolve, coupes, parole, tagueur, règles, revue. `docs/INTERFACE.md` reste la référence de l'écran. Ce document ne change ni les règles de marqueurs ni l'interface. Il rend l'analyse d'un épisode entier possible, plus rapide et reprenable.

## Ce qui est bon et reste

- Tout est local. Les décisions sont des règles lisibles, nourries par deux petits modèles spécialisés (Silero pour la parole, WD EVA02 pour la bouche, le flou et les personnages). Aucun grand modèle de langage.
- L'analyse (vidéo, son, modèles) est séparée des règles. Un seuil recalcule sans relancer les modèles.
- Les marqueurs manuels ne sont jamais touchés. `customData` `vispa-mp` désigne les marqueurs du programme.
- ffmpeg est le bon lecteur. Il lit les codecs que Resolve emploie (H.264, H.265, ProRes, DNxHR), il est déjà livré dans `tools/ffmpeg`, et les alternatives (OpenCV, PyAV, Decord) reposent sur lui. On change la façon de l'appeler, pas l'outil.
- Le lien Resolve gratuit fonctionne depuis Workspace > Scripts (branche `optimisation-lien-resolve`).

## Ce qui a été mesuré le 25 novembre 2026

Machine : 16 cœurs, RTX 3080 10 Go, onnxruntime 1.32 version processeur seulement.

| Étape | Mesure | Épisode de 24 min |
|---|---|---|
| Tagueur WD EVA02-Large, une image à la fois, processeur | 3,2 s par image | 2 000 à 4 000 images : 1 h 45 à 3 h 30 |
| Silero VAD, processeur | 0,5 s par minute d'audio | environ 15 s |
| Chargement du tagueur | 5,6 s | une fois |

## Défauts trouvés

1. **L'extraction des images bloque au-delà d'une centaine d'images.** `extract_stills` construit un seul filtre `select='eq(n,…)+eq(n,…)+…'` pour toutes les candidates d'un média. ffmpeg refuse l'expression au-delà d'environ 100 termes (« Cannot allocate memory »). Au-delà de 3 000, Windows refuse même la ligne de commande (WinError 206). Une zone In/Out de 2 minutes dépasse déjà 100 candidates. L'analyse échoue donc à l'étape « images to recognize », après la lecture de la vidéo.
2. **Rien n'est gardé entre deux sessions.** La bande 64×36, le son et les JPEG sont en cache, mais pas les scores du tagueur ni l'analyse. Fermer l'app après une analyse de 3 heures oblige à tout refaire. L'ancien plan prévoyait ce cache.
3. **L'analyse ne s'arrête pas.** Pas de bouton Annuler, pas de temps restant. `cut_records` accepte un `cancel` que personne ne passe.
4. **Le GPU n'est pas vu.** Le code essaie CUDA puis DirectML, mais le paquet `onnxruntime` installé ne propose que le processeur.
5. **La netteté est mesurée sur la vignette 64×36.** Le curseur « Sharpness » et le choix de l'image de corps reposent sur une variance du Laplacien calculée sur 2 304 pixels. À cette taille, elle mesure surtout la quantité de traits, pas le flou.
6. **La zone In/Out n'allège pas la lecture.** La bande et le son couvrent toujours tout le clip de la vidéo 1. Un essai sur une minute lit quand même l'épisode entier.

## Étape 1 — Fiabilité, avant tout essai sur un épisode entier

- **Images extraites en un seul passage, sans expression géante.** ffmpeg décode le média une fois, réduit à 448 px de large et envoie les images brutes à Python. Python garde les numéros demandés et écrit les JPEG. Aucune limite de nombre. Test : 3 000 images demandées sur un média de test, toutes écrites, dans l'ordre.
- **Cache des scores.** Un fichier par image source (clé : média, date, taille, numéro d'image, version du tagueur). Une image déjà notée n'est plus repassée au tagueur.
- **Analyse sauvegardée.** L'analyse complète est écrite dans `cache/analyses/` (clé : chemins et dates des médias, zone, réglages qui changent le choix des candidates). « Analyze » la recharge si rien n'a changé. Au démarrage, la dernière analyse de la timeline lue est proposée.
- **Annuler et temps restant.** Un bouton Annuler arrête proprement entre deux images. La progression affiche « 1 240 / 3 100 images · 12 min restantes ». Ce qui est déjà noté reste en cache, donc une reprise repart d'où elle s'est arrêtée.

C'est bon quand une analyse coupée à mi-chemin, puis relancée, ne repasse au tagueur que les images manquantes, et qu'une zone de 5 minutes passe sans erreur.

**Fait le 25 novembre 2026.** Les scores sont dans `cache/scores/` (un fichier `.jsonl` par modèle), les analyses dans `cache/analyses/`. Le bouton « Analyze » devient « Cancel » pendant l'analyse. « Read timeline » recharge l'analyse déjà faite si les médias, la zone et les réglages de choix d'images n'ont pas changé. Mesuré : 617 images extraites en 6,3 s d'une vidéo 1080p H.264 de 3 minutes (l'ancienne méthode échouait au-delà d'environ 100) ; une analyse réelle relancée à l'identique revient du cache en moins d'une seconde.

### Garder les réglages — fait le 25 novembre 2026

Fait comme décrit ci-dessous, à une différence près : « Reset » ne remet que les réglages de marqueurs. Le format de page et l'orientation restent, puisqu'ils sont choisis sous les yeux sur la planche. `presets/user.json` est ignoré par git.

Aujourd'hui, chaque lancement repart de `presets/default.json`. Les curseurs Sharpness et Mouth, tout ce qui est dans Réglages, le format et l'orientation de la planche sont perdus à la fermeture.

- Chaque changement est écrit dans `presets/user.json`, seulement les valeurs qui diffèrent de `default.json`. `default.json` reste la référence livrée et n'est jamais réécrit par l'app.
- Au démarrage : `DEFAULTS`, puis `default.json`, puis `user.json`. Une clé inconnue ou une valeur hors bornes est ignorée, sans bloquer le lancement.
- « Reset » revient à `default.json` et vide `user.json`.
- Le format de page (A5, A4, B5, Personnalisé, avec largeur et hauteur) et l'orientation sont gardés dans le même fichier.
- Comme les réglages qui décident des images examinées sont gardés, « Read timeline » retrouve l'analyse faite avec eux à la session d'avant.

C'est bon quand on change Mouth et le format, qu'on ferme et rouvre l'app, et que les deux valeurs sont revenues ; puis que Reset les ramène au défaut et le garde après un nouveau redémarrage.

## Étape 2 — Vitesse

- **Tagueur sur la RTX.** Remplacer `onnxruntime` par `onnxruntime-directml` dans `requirements.txt` : il passe par DirectX 12 et n'exige ni CUDA ni cuDNN. Mesurer. Essayer `onnxruntime-gpu` (CUDA) seulement si DirectML déçoit.
- **Silero reste sur le processeur.** Il appelle le modèle toutes les 32 ms d'audio, et le GPU serait plus lent sur ces petits appels. `providers()` prend un argument pour ça.
- **Images par lots.** Le modèle accepte un lot (`batch_size` libre). Lots de 8 à 16 sur le GPU, préparation des images dans un fil à part pendant que le GPU calcule.
- **Lecture limitée à la zone.** Avec In/Out actif, la bande et le son commencent un peu avant le In (pour retrouver la coupe précédente) et s'arrêtent après le Out, avec `-ss` avant `-i`.
- **Décodage matériel.** Essayer `-hwaccel d3d11va` (ou `cuda`) sur les deux passages ffmpeg, mesurer, garder le processeur en repli si le média n'est pas pris en charge.

Cible à vérifier par mesure : le tagueur passe de 3,2 s à moins de 0,1 s par image, et un épisode de 24 min s'analyse en 10 à 20 minutes, dont l'essentiel en lecture vidéo.

## Étape 3 — Qualité, mesurée

- **Jeu de référence.** 30 images d'un épisode, notées à la main (bouche ouverte, fermée, cachée ; nette ou floue). Un script donne le taux de bonnes réponses. Toute modification du tagueur, du cadrage ou des seuils se juge sur ce chiffre.
- **Netteté sur l'image de 448 px.** Calculée pendant l'étape 1, quand l'image est déjà décodée. La vignette 64×36 ne sert plus qu'aux coupes. Les seuils `sharpness_floor` et `sharpness_ratio` sont recalés sur le jeu de référence.
- **Cadrage pour le tagueur.** Aujourd'hui l'image 16:9 est posée sur un carré blanc, donc les visages occupent moins de place. Comparer avec un recadrage carré centré sur le jeu de référence. Garder le meilleur.
- **PixAI Tagger** reste le secours de l'ancien plan, essayé seulement si le jeu de référence montre que WD classe mal la bouche.

## Plus tard, sans changement

Séparer deux voix sans silence, reprendre les tours déjà minutés dans Cue, écrire vers Cue.

## Fichiers touchés

- `vispa_mp/frames.py` : extraction en un passage, `-ss`, décodage matériel.
- `vispa_mp/analyze.py` : cache des scores et de l'analyse, annulation, temps restant, zone In/Out.
- `vispa_mp/tags.py` : lots, `providers()` par modèle.
- `vispa_mp/speech.py` : Silero sur le processeur.
- `vispa_mp/shots.py`, `vispa_mp/rules.py` : netteté sur l'image de 448 px.
- `vispa_mp/ui.py` : Annuler, progression, reprise de la dernière analyse.
- `requirements.txt` : `onnxruntime-directml`.
- Tests : extraction de 3 000 images, reprise après annulation, cache retrouvé après redémarrage, Silero sur le processeur.
