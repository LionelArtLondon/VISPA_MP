# Interface de revue — VISPA MP

Document pour l’agent qui construit l’application. Il décrit l’écran de revue validé le 25 novembre 2026. Le moteur (coupes, parole, tagueur, règles, pont Resolve) reste en place. Ce document remplace la présentation actuelle de `vispa_mp/ui.py` : colonne de réglages à gauche, liste plate à droite.

## Images à ouvrir

Les deux images suivantes font foi pour la disposition, la densité et les libellés. Les ouvrir avant de coder.

- Bande : `C:\Users\quero\.cursor\projects\i-ANIMECOMICS-TOOLS-VISPA-MP\assets\vispa-mp-fusion-bande-v2.jpg`
- Planche : `C:\Users\quero\.cursor\projects\i-ANIMECOMICS-TOOLS-VISPA-MP\assets\vispa-mp-fusion-planche-v2.jpg`

Images plus anciennes, seulement pour l’historique du choix. Ne pas en reprendre la mise en page.

- `...\assets\vispa-mp-fusion-bande.jpg` et `vispa-mp-fusion-planche.jpg` — première fusion. Les boutons y sont trop grands, surtout sur la planche.
- `...\assets\vispa-mp-mockup-c.jpg` — l’idée de la pastille de couleur suivie du timecode et de l’intitulé. Elle vit maintenant dans l’arbre des pages.
- `...\assets\vispa-mp-mockup-a.jpg` — la règle Vidéo 1 et la tête de lecture orange.
- `...\assets\vispa-mp-mockup-b.jpg` — la page comme groupe d’images.

Défauts des images v2, à ne pas coder :

- Sur la bande, « Page 12 » est dessinée deux fois. Il n’y a qu’une ligne par page. La flèche de cette ligne ouvre ou ferme ses marqueurs.
- Sur la bande, certaines lignes ont une flèche à droite en plus de celle de gauche. Une seule flèche, à gauche du nom.
- Sur la planche, les trois boutons ne sont pas au même endroit que sur la bande. Les deux modes partagent le même en-tête, celui de la bande : boutons compacts juste après « marqueurs ».
- Sur la planche, la liste sous la page 12 est incomplète et les pastilles Vert / Cyan sont des anneaux. Toutes les propositions de la page sont listées. Les pastilles sont pleines, comme sur la bande.
- « Recalculer » n’est pas un second bouton principal. Seul « Poser les marqueurs » est en plein teal.

## Barre de titre

La barre de titre Windows est remplacée par celle de VISPA, déjà reprise dans `VISPA_CUE/vispa_cue/window_chrome.py` (`ShellTitleBar`). `vispa_mp/window_chrome.py` la porte sur la fenêtre principale.

- Hauteur 30 px, fond `#1d3947`, filet bas `#3c5b6b`.
- « VISPA MP » centré, Segoe UI 13 px, blanc atténué.
- À droite : réduire `─`, agrandir `⛶` (restaurer `❐`), fermer `X`. Le survol du fermer est le rouge arrondi `#ae3643`. Les autres survols sont `#31565d`.
- Glisser la barre déplace la fenêtre. Un double-clic l’agrandit. Les bords restent ceux de Windows, avec l’aimantation.
- L’en-tête de travail (boutons, nom de timeline, Resolve) reste en dessous. Ce n’est pas la barre de titre.

## Coque

Reprendre les tokens de VISPA Cue, `I:\ANIMECOMICS\TOOLS\VISPA_CUE\vispa_cue\ui_tokens.py`. Les recopier dans VISPA MP. Ne pas importer le paquet `vispa_cue`.

- Fond `#081820`, panneaux `#102631`, titre de panneau `#1C3E4B`, barre `#0E232C`
- Texte `#E8F2F5`, texte secondaire `#A3BCC5`, accent `#2FD0C0`
- Bouton principal `#1FB5A7`, texte du bouton `#04201D`
- Ligne sélectionnée `#175460`, tête de lecture `#FF8A5C`
- Police Segoe UI. Timecodes en Consolas.
- Boutons, listes déroulantes et champs : hauteur 28 px, rayon 4 px, comme `CONTROL` et `RADIUS`.

Couleurs de marqueurs, déjà dans `vispa_mp/ui.py` : Vert `#3c8c4a`, Bleu `#2f6fed`, Cyan `#3ec2d6`. Ce sont `PAGE`, `CORE` et `EXTRA` de `vispa_mp/markers.py`. Jaune et orange ne sont pas proposés.

En-tête, identique en Bande et en Planche :

- « VISPA MP » en cyan acier, puis « marqueurs » en gris.
- Trois boutons compacts, largeur du libellé, hauteur 28 px, alignés à gauche : « Lire la timeline », « Analyser », « Poser les marqueurs ». Ils ne s’étirent pas sur la fenêtre. Ils ne changent pas de taille quand on change de mode.
- Au centre, le nom de la timeline lue.
- À droite, un point cyan et « Resolve relié », ou l’état réel si Resolve n’est pas joignable.

« Télécharger les modèles » et « Réinitialiser » quittent cette barre. Ils vont dans Réglages.

Pied : timecode de la tête de lecture locale, zone In/Out si elle existe, « Vidéo 1 · Audio 1 ».

## Deux modes, un seul état

« Bande » et « Planche » sont deux vues de la même sélection. Changer de mode ne referme pas l’arbre, ne déplace pas la tête de lecture, ne relance pas l’analyse.

La tête de lecture orange de la règle « Vidéo 1 » est celle de VISPA MP. Cliquer ou faire glisser cette règle déplace la revue dans le logiciel. Ce geste ne sert pas à piloter la tête de lecture de Resolve. Écrire les marqueurs continue d’appeler le pont Resolve.

## Colonne Pages

Une page commence à un marqueur vert et va jusqu’au vert suivant. Les marqueurs entre les deux sont ses enfants. Les marqueurs posés à la main dans cet intervalle apparaissent aussi, en point gris, avec l’intitulé « manuel · laissé ». Ils ne sont ni recolorés, ni réécrits.

Chaque page est une seule ligne : une flèche, puis « Page N ». La zone cliquable de la flèche fait au moins 24 px de côté.

- Cliquer le nom sélectionne la page, amène la tête de lecture au premier marqueur de cette page, et met la page dans la vue (bande ou planche). La ligne ne s’ouvre pas.
- Cliquer la flèche ouvre ou ferme les enfants. Rien d’autre.
- Une page peut être sélectionnée et fermée. Une autre peut être ouverte sans être sélectionnée.
- Cliquer un enfant sélectionne ce marqueur, place la tête de lecture sur son image, et met à jour Suggestions et le volet Réglage.

L’intitulé d’un enfant est le `note` déjà produit par les règles : « Début de page », « Corps, fin de plan », « Réplique, bouche ouverte », « Réserve, action », « Réserve, deuxième bouche », et les variantes déjà écrites dans `rules.py`. Devant : la pastille de couleur, puis le timecode.

Page précédente et page suivante se font sans faire défiler tous les marqueurs. Quand la liste des pages a le focus, Alt+Haut et Alt+Bas changent de page. La ligne de la page sélectionnée est ramenée dans la vue. Les pages fermées le restent.

Si une page dépasse `max_page_images` images de page (bleu), l’alerte déjà calculée reste visible à côté du nom de la page, dans les deux modes.

## Bande

Sous l’en-tête, la règle « Vidéo 1 » : graduation, blocs vert / bleu / cyan des propositions, tête de lecture orange. Sous la règle, les vignettes de la page sélectionnée, avec timecode, couleur et note courte. La vignette du marqueur sélectionné est entourée.

En dessous, « Suggestions » : les candidates déjà calculées pour la réplique ou le plan du marqueur sélectionné. Chaque vignette montre son motif (« tenue », « bouche 0,91 », « floue »). Cliquer une suggestion remplace l’image de cette proposition, localement, avant l’écriture dans Resolve. Pas de nouvelle inférence.

## Planche

Même colonne Pages, même règle « Vidéo 1 » en bandeau plus fin, même volet Réglage.

Le centre est une page blanche au format choisi, posée sur le fond sombre. Les images de la page sélectionnée y sont rangées en ordre de lecture, dans des cases à gouttière régulière. Le vert ouvre la page. Les bleus portent la lecture. Les cyan sont des réserves, plus petites si la place manque. C’est un aperçu très simple de la page, pas la mise en page de VISPA. Rien n’est écrit vers VISPA ni vers Cue depuis cette vue.

Formats, dans cet ordre : A5, A4, B5, Personnalisé.

- A5 : 148 × 210 mm
- A4 : 210 × 297 mm
- B5 : 176 × 250 mm
- Personnalisé : deux champs « Largeur » et « Hauteur », en millimètres. Ils sont actifs seulement dans ce cas. Les autres formats les laissent visibles et inactifs, comme sur l’image planche.

Orientation : « Portrait » ou « Paysage ». Elle échange largeur et hauteur pour tous les formats, y compris Personnalisé. Le choix du format et de l’orientation est gardé pour la session. Il ne change aucune règle de marqueur.

Sous la page, une légende du type « Page 12 · A5 · portrait ».

## Réglage

Volet de droite, dans les deux modes.

- Curseur « Netteté » : le seuil de netteté déjà utilisé par les règles (`sharpness_floor`).
- Curseur « Bouche » : le seuil de bouche déjà utilisé (`mouth_min`).
- « Recalculer » relance `propose` sur l’analyse en cache. Il ne relance ni ffmpeg, ni Silero, ni le tagueur. Le comportement actuel de `recompute` reste celui-ci.
- « Couleur du marqueur » : trois pastilles, Vert, Bleu, Cyan. Elles changent la couleur de la proposition sélectionnée, donc `color` parmi `Green`, `Blue`, `Cyan`, et le `name` via `NAMES`. Cue lit la couleur. Une proposition cyan reste un extra. Un marqueur manuel n’est pas modifiable ici. La ligne « Les marqueurs à la main restent. » reste sous les pastilles.

Les autres réglages déjà branchés dans `ui.py` (compression de l’histoire, silences, portion de fin de plan, plan d’action, In/Out, repli de bouche, réinitialiser, télécharger les modèles) ne disparaissent pas. Ils passent derrière un bouton « Réglages », hors de l’écran de travail. Les changer recalcule aussi sans réinférence, comme aujourd’hui.

## Barres de défilement

La barre demandée est celle de la suite, déjà peinte dans `I:\ANIMECOMICS\TOOLS\VISPA_CUE\vispa_cue\scrollbar_style.py` (`VispaScrollBarStyle`). Le commentaire de ce fichier renvoie à la barre de VISPA, `VispaQtScrollBar`. Aucun logiciel nommé Gizmo n’est dans `I:\ANIMECOMICS\TOOLS`. Reprendre cette barre-là, telle quelle.

La recopier dans VISPA MP et l’installer une fois sur `QApplication`, avant la fenêtre, comme `install_scrollbar_style`. Ne pas importer `vispa_cue`.

À respecter :

- Largeur 16 px, pouce minimum 26 px, pas de boutons fléchés.
- Le rail est un trait de 1 px, `#878787`, blanc au survol.
- Le pouce est une capsule cyan, trait de 9 px à bouts ronds, `#239ba8`, `#00e5ff` au survol.
- Le fond de la barre est celui du viewport, pas une piste grise opaque.
- Toute liste, toute zone qui défile, y compris Pages, les vignettes et la planche, utilise cette barre. Pas de barre Qt par défaut à côté.

## Ce que l’écran continue de faire

- « Lire la timeline » lit la vidéo 1 et l’audio 1. Les pistes du dessus restent ignorées. L’avertissement `CUE_SOURCE` reste affiché.
- « Analyser » lance l’analyse actuelle, d’abord sur la zone In/Out quand ce réglage est actif.
- « Poser les marqueurs » écrit les propositions après confirmation. `plan_apply` laisse les marqueurs manuels. Le décompte posés / laissés reste dans le pied.
- Un seuil modifié ne relance pas les modèles.
- La revue peut commencer sur une zone In/Out avant l’épisode entier.

## Fichiers

- `vispa_mp/ui.py` : remplacer la construction de la fenêtre. Garder `read_timeline`, `run_analysis`, `write_markers`, `recompute`, `settings`.
- Nouveau module de barre de défilement, copie adaptée de `scrollbar_style.py`.
- Les formats de page et l’orientation peuvent vivre dans l’état de la fenêtre. Ils ne modifient pas `presets/default.json` tant qu’ils ne changent pas les règles.
- Tests : la flèche n’ouvre pas la page quand on clique le nom. Changer de page sans ouvrir les enfants ne déplace que la tête de lecture. Changer une pastille change `color` de la proposition sélectionnée et laisse un marqueur manuel intact. « Recalculer » ne rappelle pas `analyze`. La barre installée n’a pas de boutons fléchés (`SC_ScrollBarAddLine` absent, comme le test Cue).
