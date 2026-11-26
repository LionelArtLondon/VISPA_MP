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

Les vignettes forment désormais un plateau fixe : les rangées sont choisies une
fois par page et par filtre, en privilégiant les rangées complètes lorsqu'elles
restent lisibles. La molette zoome autour du pointeur et le bouton central permet
de déplacer l'ensemble. Le zoom, la sélection et le redimensionnement ne changent
pas la répartition des images entre les rangées.

En dessous, « Suggestions » : les candidates déjà calculées pour la réplique ou le plan du marqueur sélectionné. Chaque vignette montre son motif (« tenue », « bouche 0,91 », « floue »). Cliquer une suggestion remplace l’image de cette proposition, localement, avant l’écriture dans Resolve. Pas de nouvelle inférence.

Un clic droit sur une suggestion ouvre trois actions : ajouter un Extra, ajouter
un Core ou commencer une nouvelle page à cette image. L'ajout garde la proposition
d'origine et apparaît dans les deux vues, dans l'ordre de la timeline. Une image
déjà occupée par une proposition ou un marqueur manuel ne peut pas être ajoutée
deux fois. Ces ajouts restent présents lors des recalculs de seuils et sont
enregistrés dans le projet `.vispamp`. Le rôle choisi peut ensuite être changé
avec les pastilles habituelles. Les filtres qui masqueraient l'ajout passent à
« All images » pour le rendre visible.

Une séparation horizontale déplaçable sépare la revue des Suggestions, en Bande
comme en Planche. Remonter cette barre agrandit le panneau et ses images ; les
candidates défilent horizontalement quand elles dépassent sa largeur. La hauteur
est partagée entre les deux modes, conservée lors de la fermeture du panneau et
enregistrée dans le projet `.vispamp`. Le zoom et le déplacement de Planche restent
inchangés.

Dans Suggestions, maintenir le bouton central de la souris et glisser déplace
la rangée horizontalement, y compris en commençant sur une image ou son libellé.
La barre de défilement suit le mouvement ; relâcher le bouton rend les clics de
sélection et le menu contextuel habituels.

Chaque vue conserve séparément son zoom et son cadrage lors du passage de Bande à
Planche et inversement. Le projet `.vispamp` enregistre les deux vues, y compris
les colonnes de Bande, pour retrouver la même disposition à la réouverture. Le
point central est conservé même si la taille de la fenêtre a changé. Les anciens
projets sans ces informations utilisent les vues par défaut.

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

La ligne de format de page contient aussi « Frame format » et une case
« Labels ». Les contrôles défilent horizontalement si la fenêtre est étroite.
« Labels » masque les badges Page/Core/Extra de la Planche tout en conservant les
contours colorés et les signes de sélection. Le format de cadre propose Source,
16:9, 4:3, 3:2, 1:1, 2:3, 9:16 et Custom (proportions largeur:hauteur).
Source montre l'image entière ; les autres formats utilisent un recadrage centré
sans déformation. Le ratio s'applique aux images de Planche, Bande et Suggestions,
uniquement pour la prévisualisation : les sources et les positions des marqueurs
restent identiques. Le format et l'affichage des badges sont mémorisés dans le
projet et dans les préférences de session.

Un clic droit sur une proposition en Bande ou en Planche permet « Delete marker
proposal ». Le retrait modifie la préparation locale et prend effet dans Resolve
au prochain placement. Les marqueurs posés à la main restent protégés. La
proposition retirée ne réapparaît pas lors d'un recalcul de seuils ; ces exclusions
sont enregistrées dans le projet. Ajouter explicitement cette image depuis une
suggestion la rétablit. Une nouvelle analyse commence une nouvelle préparation.

Le même menu permet maintenant d'attribuer directement les rôles « Page start »,
« Core » ou « Extra ». Les pastilles du volet Adjust portent ces rôles, plutôt
que les noms des couleurs. Le rôle choisi à la main est conservé au recalcul.

Une proposition peut être glissée depuis Bande ou Planche vers la colonne Pages.
Déposer sur une page fermée l'ajoute à la fin ; déposer dans les enfants d'une
page dépliée affiche une ligne d'insertion avant ou après l'image survolée. La
liste défile automatiquement près de ses bords. Les marqueurs manuels ne se
déplacent pas. L'ordre et les groupes choisis sont conservés dans `.vispamp`, y
compris après recalcul ou changement d'image par une suggestion. Le bouton
« Automatic pages » permet de revenir aux groupes déduits des débuts de page.

Cet ordre est un ordre de lecture pour la préparation : les frames sources et
les rôles ne changent pas pendant le geste. Le bandeau le précise et la
confirmation de placement rappelle que les marqueurs Resolve restent aux
timecodes sources. Le placement ne transmet pas un ordre de lecture arbitraire
à un exporteur qui regroupe uniquement les marqueurs chronologiquement.

### Sens des réglages de sélection

« Sharpness » est un seuil de netteté mesurée des candidats, sans accentuation de
l'aperçu. Le relever écarte davantage d'images douces, en particulier parmi les
Extras. Pour une réplique, le repli configuré peut conserver une image quand
aucune candidate ne passe le filtre.

« Open mouth » est le seuil du score visuel de bouche ouverte. Le score doit
aussi dépasser celui de bouche fermée ; augmenter 0,20 vers 0,80 rend la
sélection plus stricte. Ce seuil ne représente ni une ouverture physique en
pourcentage ni un volume audio. Si aucune image ne convient, le repli peut
conserver une image portant « Mouth not verified ».

La compression agit aussi quand une moyenne Core est active : une compression
plus forte rapproche le nombre de pages du minimum autorisé. La moyenne Core
guide ensuite la sélection à l'intérieur des bornes d'images. Les bornes de
pages restent proratisées selon la durée analysée et la durée d'épisode choisie.

Les Extras d'action utilisent désormais les changements de dessins normalisés
en contraste, en complément du mouvement brut, et un espacement séparé
« Time between Extras » (0,12 s par défaut). Les filtres de netteté/flou et la
protection des marqueurs manuels restent actifs. Les candidats Extra sont
comparés aussi entre eux pour éviter des images quasi identiques. Ces réglages
recalculent les choix depuis les candidats déjà analysés, sans nouveau modèle.

## Réglage

Volet de droite, dans les deux modes.

- Curseur « Netteté » : le seuil de netteté déjà utilisé par les règles (`sharpness_floor`).
- Curseur « Bouche » : le seuil de bouche déjà utilisé (`mouth_min`).
- « Recalculer » relance `propose` sur l’analyse en cache. Il ne relance ni ffmpeg, ni Silero, ni le tagueur. Le comportement actuel de `recompute` reste celui-ci.
- Dans Réglages › Pages › Images per page, « Core images, target average » donne
  une moyenne souhaitée de marqueurs verts et bleus par page. `Off` (valeur 0)
  conserve le comportement piloté par la compression. Une valeur positive guide
  le découpage et la sélection des Core vers une marge d'une image autour de la
  cible, en respectant les bornes de pages et d'images existantes. Les
  Extras cyan ne comptent pas dans cette moyenne et ne sont pas supprimés par
  cet objectif. Les plafonds déjà définis continuent de s'appliquer. La cible
  reste souple : elle ne crée pas de nouvelles images et un avertissement indique
  quand les limites empêchent de l'atteindre. Le réglage est sauvegardé avec les
  paramètres et avec le projet.
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

Le pont transmet un nom non vide (`marqueur-001`, `marqueur-002`, etc.) dans
l'ordre chronologique, toutes couleurs confondues : Resolve refuse les
marqueurs dont le nom est vide. Après écriture, les marqueurs sont relus sur la
timeline vérifiée ; seules les positions dont la couleur, le nom et la signature
correspondent sont annoncées comme posées. Le dialogue de confirmation compte
uniquement les propositions dans la zone In/Out et indique celles qui en sont
exclues. Un dialogue final distingue les marqueurs vérifiés, les refus et les
positions déjà occupées par des marqueurs manuels.
- Un seuil modifié ne relance pas les modèles.
- La revue peut commencer sur une zone In/Out avant l’épisode entier.

## Projets de revue — ajouté le 25 novembre 2026

Le menu « Project » propose « Open project… » (Ctrl+O), « Save project » (Ctrl+S),
« Save project as… » (Ctrl+Maj+S) et « DaVinci project folder… ».

Un fichier `.vispamp` conserve l'analyse, les propositions effectivement retouchées,
les réglages, le format, la sélection et les vignettes candidates. Les vidéos et les
modèles ne sont pas copiés. Sauvegarder fonctionne même si Resolve a été fermé.
Le fichier reste utilisable si le cache de vignettes d'origine a disparu.

Pour ouvrir une préparation, le projet et la timeline d'origine doivent être ouverts
dans Resolve et le pont doit répondre. Leurs identifiants uniques et le montage sont
contrôlés avant de remplacer le travail affiché. En cas de refus, un message nomme
le projet et la timeline à ouvrir ; la préparation courante reste intacte. Le
chargement restaure les choix enregistrés sans relancer l'analyse ni poser de marqueurs.

Resolve ne fournit pas le chemin du dernier `.drp` exporté. Le dossier est donc
choisi manuellement une première fois, puis mémorisé par projet Resolve comme
emplacement proposé pour les sauvegardes. Le menu permet de le changer.

Une étoile dans le titre signale le travail non sauvegardé. Avant de fermer ou de
remplacer une préparation, le logiciel propose de sauvegarder, abandonner ou annuler.
Les contrôles de revue sont verrouillés pendant une opération en cours ; l'annulation
de l'analyse reste disponible.

## Fichiers

- `vispa_mp/ui.py` : remplacer la construction de la fenêtre. Garder `read_timeline`, `run_analysis`, `write_markers`, `recompute`, `settings`.
- Nouveau module de barre de défilement, copie adaptée de `scrollbar_style.py`.
- Les formats de page et l’orientation peuvent vivre dans l’état de la fenêtre. Ils ne modifient pas `presets/default.json` tant qu’ils ne changent pas les règles.
- Tests : la flèche n’ouvre pas la page quand on clique le nom. Changer de page sans ouvrir les enfants ne déplace que la tête de lecture. Changer une pastille change `color` de la proposition sélectionnée et laisse un marqueur manuel intact. « Recalculer » ne rappelle pas `analyze`. La barre installée n’a pas de boutons fléchés (`SC_ScrollBarAddLine` absent, comme le test Cue).
