# Interface de revue — VISPA MP

L'en-tête affiche en permanence **Project: nom du projet Resolve** et
**Timeline: nom de la timeline**. **Read timeline** actualise cette source ;
les deux noms figurent aussi dans le bilan de lecture en bas de fenêtre.
Les noms longs sont abrégés à l'écran et restent complets au survol. Le projet
est celui de la bibliothèque Resolve, sans supposer le chemin d'un export `.drp`.

Le bouton **Learning** ouvre l'import, la sélection et l'inspection des images
des chapitres de référence, la comparaison entre chapitres, l'entraînement local et l'activation explicite
d'un profil personnel. Le parcours et les limites
sont décrits dans [LEARNING.md](LEARNING.md). Le profil actif est conservé dans
les projets `.vispamp` ; cette fonction ne place aucun marqueur dans Resolve.

Le bloc permanent **Selection profile**, en haut de la colonne droite, nomme
le profil réellement actif ou **MP standard rules**. Il permet de choisir ou
charger un profil en dépliant son chevron, puis de l'appliquer avec **Use selection**. Un choix en
attente est signalé sans modifier l'indication du mode actif. **Profiles…**
ouvre **Settings › Profiles**, synchronisé avec ce bloc. Le mode standard
conserve les réglages courants ; il ne les réinitialise pas.
**Compare** ouvre deux fenêtres de consultation indépendantes, standard et
profil personnel, depuis la même analyse et les mêmes réglages. Elles offrent
Strip/Board, navigation et zoom sans édition, préférences partagées ou connexion
Resolve. La revue de travail reste intacte.

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
- Boutons, listes déroulantes et champs : hauteur 28 px, rayon 4 px, comme `CONTROL` et `RADIUS`. Exception : les boutons de l’en-tête font 24 px (`HEADER_CONTROL`), centrés dans la barre de 44 px pour laisser 10 px au-dessus et en dessous.

Couleurs de marqueurs, déjà dans `vispa_mp/ui.py` : Vert `#3c8c4a`, Bleu `#2f6fed`, Cyan `#3ec2d6`. Ce sont `PAGE`, `CORE` et `EXTRA` de `vispa_mp/markers.py`. Jaune et orange ne sont pas proposés.

En-tête, identique en Bande et en Planche :

- « VISPA MP » en cyan acier, puis « marqueurs » en gris.
- Après « Project », deux boutons carrés encadrés de 24 × 24 px, séparés de 6 px, avec les icônes Lucide `import` pour « Read timeline » et `sparkles` pour « Analyze ». Leurs tooltips expliquent les actions ; les noms restent accessibles au clavier et aux lecteurs d’écran. Pendant l’analyse, les étincelles deviennent un carré d’arrêt avec le tooltip « Cancel analysis », puis reviennent à leur état initial.
- « Project », « Place markers » et « Learning » gardent leurs libellés, avec 8 px de marge intérieure de chaque côté et une hauteur de 24 px. Les boutons ne s’étirent pas sur la fenêtre et ne changent pas de taille quand on change de mode.
- « Project » réserve un espace distinct au chevron de menu, centré verticalement à droite du texte.
- Au centre, le nom de la timeline lue.
- À droite, « Learning », puis un espace de 12 px avant le point et l’état réel de la connexion Resolve. Réglages reste à l’extrémité droite, dans un bouton carré de 24 px.
- « Strip » et « Board » se trouvent dans « Review tools », à droite de la prévisualisation.

« Télécharger les modèles » et « Réinitialiser » quittent cette barre. Ils vont dans Réglages.

Pied : timecode de la tête de lecture locale, zone In/Out si elle existe, « Vidéo 1 · Audio 1 ».

## Séparateurs des colonnes

Les colonnes Pages, prévisualisation centrale et Review tools sont séparées par
deux poignées verticales redimensionnables. Le trait visible fait 2 px, avec une
zone de prise de 8 px et un curseur horizontal. Il s'éclaircit au survol et passe
au turquoise vif pendant le glissement. Les panneaux gardent une largeur minimale
utilisable ; la zone centrale absorbe l'espace restant.

Les largeurs de Pages et Review tools sont de 280 px par défaut et sont
mémorisées dans les préférences locales. Elles sont partagées entre Strip et
Board. Le redimensionnement conserve les sélections, le zoom et le cadrage des
deux vues. Les contrôles de droite se réorganisent lorsque cette colonne devient
plus étroite. Le séparateur horizontal des Suggestions reste indépendant.

## Deux modes, un seul état

La zone centrale réserve sa hauteur à la règle vidéo et au canevas. Dans la
colonne droite de 280 px par défaut, **Review tools** regroupe les vues, filtres, qualité,
suggestions, formats et orientation. Le profil actif reste toujours visible en
haut ; ses commandes se déplient à la demande. Les outils défilent verticalement
sur une petite fenêtre. **Adjust** reste en bas, avec les pastilles de rôle de
18 px et leurs libellés rapprochés.

Chaque canevas affiche en haut à gauche un compteur fixe, transparent aux clics :
en All images, le total de la page en grand et le nombre de Core en petit à
droite ; en Core, le nombre de Core en grand et le total Extras compris en petit.
Les débuts de page font partie des Core. Le filtre Page starts compte les débuts
de page de tout le chapitre. Les compteurs suivent les retouches et Undo/Redo,
indépendamment du zoom ou des images momentanément hors du cadre.

Les longues informations d'analyse et le budget global se consultent avec
**Analysis details**. Le bouton signale le nombre d'avertissements ; le rapport
non modal garde les textes complets, sans occuper une bande au-dessus du canevas.

« Bande » et « Planche » sont deux vues de la même sélection. Changer de mode ne referme pas l’arbre, ne déplace pas la tête de lecture, ne relance pas l’analyse.

La tête de lecture orange de l'encadré **Timeline** est celle de VISPA MP.
La règle garde 94 px de hauteur dans les deux vues, avec ses graduations et son
timecode. La molette zoome autour du pointeur ; maintenir le bouton central
permet de panoter horizontalement. Un double-clic central ou **Fit timeline**
revient à l'ensemble de la zone analysée. Cliquer ou glisser le bouton gauche
déplace le playhead ; cliquer une épingle sélectionne l'image existante.
Ces gestes naviguent dans MP ; l'écriture continue de passer par **Place markers**.

Le clic droit sur la règle affiche le timecode pointé et propose **Add Core
marker here**, **Add Extra marker here** et **Add Page start marker here**.
MP extrait la frame exacte de la source Vidéo 1 avec jusqu'à quatre voisines
du même plan, puis insère la proposition dans la page déterminée par ses voisins
chronologiques. L'ordre manuel existant est conservé ; un marqueur déjà présent
ne peut pas être écrasé. Les images voisines s'ouvrent dans Suggestions et restent
accessibles aux propositions supplémentaires créées à partir de ces images.

L'extraction travaille en arrière-plan ; le bouton d'analyse devient **Cancel
image capture** pendant cette opération. Une annulation garde la préparation.
Les sources absentes, les trous, les transitions ambiguës et les changements de
vitesse non pris en charge donnent une explication. La première capture tardive
peut demander un décodage depuis le début du média ; les images sont ensuite
réutilisées depuis le cache. Les propositions et leurs suggestions sont
annulables et enregistrées dans `.vispamp`, sans nouvelle analyse IA.

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

En dessous, « Suggestions » : les candidates déjà calculées pour la réplique ou
le plan du marqueur sélectionné. Chaque vignette montre son motif (« tenue »,
« bouche 0,91 », « floue »). Un clic simple sélectionne la suggestion et en
affiche l'aperçu, sans remplacer ni modifier le marqueur d'origine. **Ctrl+clic**
ajoute ou retire des candidates de cette sélection, indépendante de la sélection
des marqueurs dans Strip et Board. Aucune nouvelle inférence n'est nécessaire.

Le bouton **Suggestions**, près de « Video 1 », ouvre le panneau pour l'image
sélectionnée. Par défaut, le double-clic conserve aussi ce rôle. Dans l'en-tête
du panneau, **Open on selection** permet de suivre automatiquement chaque image
sélectionnée dans Strip, Board ou Pages. Décoché, le panneau s'ouvre sur demande.

**Detach** déplace le même panneau dans une fenêtre redimensionnable, utilisable
sur un autre écran. Les sélections et les actions sur les suggestions restent
liées à la revue de travail. Agrandir la fenêtre réadapte la taille des images.
**Full screen** ou **F11** occupe tout l'écran ; Échap revient à la fenêtre.
**Dock**, ou la fermeture de cette fenêtre, rattache le panneau sous la revue
en retrouvant sa hauteur précédente. Une fenêtre détachée en mode automatique
reste présente avec une explication si la sélection n'a pas de suggestions.

Le choix **Rows**, dans l'en-tête de Suggestions, propose **Scroll** et de une
à six rangées. **Scroll** conserve la bande horizontale actuelle, avec de grands
aperçus et défilement. Choisir un nombre de rangées fait tenir toutes les
candidates dans le cadre : MP calcule les colonnes nécessaires et adapte la
largeur et la hauteur des vignettes à la place disponible, en conservant le
format d'aperçu choisi. Il n'est alors plus nécessaire de faire défiler les
images. S'il y a moins de candidates que de rangées demandées, seules les
rangées utiles sont occupées. Le nombre de rangées reste le même lors du
redimensionnement ; les images gardent leur ordre.

Les choix d'ouverture automatique, de détachement et de rangées sont des
préférences de vue, mémorisées entre les sessions et dans les projets `.vispamp`.
Ils ne changent ni l'analyse, ni le profil, ni les réglages de sélection des
marqueurs. Changer de disposition conserve les sélections et les actions
d'ajout ou de remplacement.

Le clic droit conserve la sélection multiple si la suggestion visée en fait
partie ; sur une autre candidate, il cible cette candidate seule. **Add Extra
marker** et **Add Core marker** créent des repères supplémentaires pour les
candidates sélectionnées. L'image et le rôle du marqueur d'origine restent
intacts, et ce marqueur reste la sélection principale après l'ajout. Les images
ajoutées apparaissent dans Strip et Board et rejoignent la page et l'ordre de
lecture de la préparation. **Start a new page here** permet aussi d'ajouter un
début de page. Une image déjà occupée par une proposition ou un marqueur manuel
ne peut pas être ajoutée
deux fois. Ces ajouts restent présents lors des recalculs de seuils et sont
enregistrés dans le projet `.vispamp`. Le rôle choisi peut ensuite être changé
avec les pastilles habituelles. Les filtres qui masqueraient l'ajout passent à
« All images » pour le rendre visible.

Pour remplacer volontairement l'image du marqueur d'origine, choisir une seule
suggestion puis utiliser **Use as replacement**, **Entrée** ou un double-clic.
Ce remplacement est distinct des actions d'ajout. Le menu contextuel affiche un
survol visible des actions disponibles et un style atténué pour celles qui sont
désactivées. La sélection, l'ajout multiple et le remplacement fonctionnent aussi
dans la fenêtre Suggestions détachée.

Une séparation horizontale déplaçable sépare la revue des Suggestions, en Bande
comme en Planche. Remonter cette barre agrandit le panneau et ses images ; en
mode **Scroll**, les candidates défilent horizontalement quand elles dépassent
sa largeur. Avec un nombre de rangées, les vignettes s'ajustent pour rester
toutes visibles. La hauteur
est partagée entre les deux modes, conservée lors de la fermeture du panneau et
enregistrée dans le projet `.vispamp`. Le zoom et le déplacement de Planche restent
inchangés.

Dans Suggestions en mode **Scroll**, maintenir le bouton central de la souris
et glisser déplace la rangée horizontalement, y compris en commençant sur une
image ou son libellé.
La barre de défilement suit le mouvement ; relâcher le bouton rend les clics de
sélection et le menu contextuel habituels.

Chaque vue conserve séparément son zoom et son cadrage lors du passage de Bande à
Planche et inversement. Le projet `.vispamp` enregistre les deux vues, y compris
les colonnes de Bande, pour retrouver la même disposition à la réouverture. Le
point central est conservé même si la taille de la fenêtre a changé. Les anciens
projets sans ces informations utilisent les vues par défaut.

## Cadres et sélection multiple

En Bande comme en Planche, le cadre de statut conserve sa couleur vert / bleu /
cyan et une épaisseur de 3 px. La sélection ajoute un contour blanc extérieur de
2 px, séparé par un espace sombre : elle ne remplace plus le cadre de statut.
Les aperçus de suggestions et le retour « Kept » conservent aussi cette couleur.

Un clic simple sélectionne une image. Ctrl+clic ajoute ou retire une image du
groupe, y compris dans l’arbre Pages. Le groupe reste sélectionné en passant de
Bande à Planche. Le volet Adjust indique le nombre d’images sélectionnées et
signale les marqueurs manuels en lecture seule.

Maj+clic sélectionne toutes les images entre l'image de départ et l'image
cliquée, bornes incluses, dans l'ordre chronologique de la vidéo. Les Maj+clic
suivants gardent le même point de départ pour agrandir ou réduire la plage.
Ctrl+Maj+clic ajoute cette plage au groupe existant. L'ordre reste chronologique
même si les images ont été réorganisées manuellement entre les pages. Les filtres
de Strip et Board s'appliquent aux plages de ces vues ; dans l'arbre Pages, toutes
les lignes d'images restent sélectionnables. Un clic avec Maj ou Ctrl ne déclenche
pas de glisser-déposer.

Les pastilles Page start / Core / Extra changent le statut de toutes les
propositions sélectionnées en une opération. Suppr retire toutes les propositions
sélectionnées de la préparation ; le clic droit sur une proposition du groupe
offre les mêmes actions. Les marqueurs posés à la main restent protégés. La touche
Suppr garde son rôle habituel dans les champs de saisie. Un clic simple revient
à une sélection unique ; Ctrl+clic sur la dernière image permet de tout désélectionner.

## Planche

Même colonne Pages, même encadré Timeline et même colonne d'outils.

Le centre est une page blanche au format choisi, posée sur le fond sombre. Les images de la page sélectionnée y sont rangées en ordre de lecture, dans des cases à gouttière régulière. Le vert ouvre la page. Les bleus portent la lecture. Les cyan sont des réserves, plus petites si la place manque. C’est un aperçu très simple de la page, pas la mise en page de VISPA. Rien n’est écrit vers VISPA ni vers Cue depuis cette vue.

Formats, dans cet ordre : A5, A4, B5, Personnalisé.

- A5 : 148 × 210 mm
- A4 : 210 × 297 mm
- B5 : 176 × 250 mm
- Personnalisé : deux champs « Largeur » et « Hauteur », en millimètres. Ils sont actifs seulement dans ce cas. Les autres formats les laissent visibles et inactifs, comme sur l’image planche.

Orientation : « Portrait » ou « Paysage ». Elle échange largeur et hauteur pour tous les formats, y compris Personnalisé. Le choix du format et de l’orientation est gardé pour la session. Il ne change aucune règle de marqueur.

Dans les outils, une légende du type « Page 12 · A5 · portrait ».

Le groupe de format de page contient aussi « Frame format » et une case
« Labels ». La colonne défile verticalement si la fenêtre est basse.
« Labels » masque les badges Page/Core/Extra de la Planche tout en conservant les
contours colorés et les signes de sélection. Le format de cadre propose Source,
16:9, 4:3, 3:2, 1:1, 2:3, 9:16 et Custom (proportions largeur:hauteur).
Source montre l'image entière ; les autres formats utilisent un recadrage centré
sans déformation. Le ratio s'applique aux images de Planche, Bande et Suggestions,
uniquement pour la prévisualisation : les sources et les positions des marqueurs
restent identiques. Le format et l'affichage des badges sont mémorisés dans le
projet et dans les préférences de session.

Le contrôle commun **Preview quality**, près de Suggestions dans la colonne droite,
propose **Low / Medium / High** pour Bande, Planche et Suggestions. **Medium**, par
défaut, utilise le rendu lissé de l'ancienne Bande ; Planche partage désormais ce
même moteur. Low privilégie la rapidité ; High utilise un rééchantillonnage Lanczos
adapté au zoom et à la densité de l'écran. Les caches de sources et de rendus sont
bornés en mémoire. Le détail disponible dépend des vignettes déjà extraites.
Le choix s'applique immédiatement et se conserve dans les préférences et dans
`.vispamp`, sans recalcul de sélection.

Valider une suggestion ou ajouter des images Core/Extra conserve le zoom et le
cadrage de la page en cours, aussi pour un ajout groupé, un remplacement du début
de page ou une annulation. La sélection et les caméras de la vue cachée restent
indépendantes. Le changement manuel de page, de filtre ou d'analyse garde son
comportement de cadrage automatique.

Un clic droit sur une proposition en Bande ou en Planche permet « Delete marker
proposal ». Le retrait modifie la préparation locale et prend effet dans Resolve
au prochain placement. Les marqueurs posés à la main restent protégés. La
proposition retirée ne réapparaît pas lors d'un recalcul de seuils ; ces exclusions
sont enregistrées dans le projet. Ajouter explicitement cette image depuis une
suggestion la rétablit. Une nouvelle analyse commence une nouvelle préparation.

Le même menu permet maintenant d'attribuer directement les rôles « Page start »,
« Core » ou « Extra ». Les pastilles du volet Adjust portent ces rôles, plutôt
que les noms des couleurs. Le rôle choisi à la main est conservé au recalcul.

Une proposition peut être glissée depuis Bande, Planche ou une ligne de la colonne
Pages vers cette même colonne. Ctrl+clic permet de sélectionner plusieurs images ;
glisser une image déjà sélectionnée transfère tout le groupe éditable, dans son
ordre de lecture actuel. Un clic simple sans glissement revient à une seule image.
Survoler le titre d'une page pendant un glissement surligne toute sa ligne en
ambre, avec une flèche d'entrée à droite. Cette indication se distingue du survol
normal et de la sélection ; elle disparaît dès que la cible change ou que le
glissement se termine. Après environ **0,65 seconde** sur le titre d'une page
fermée, celle-ci se déplie automatiquement sans changer la sélection. On peut
alors descendre entre ses images pour choisir une insertion précise. Quitter le
titre avant ce délai annule l'ouverture ; une page déjà ouverte ne se replie pas.
Déposer directement sur le titre ajoute toujours le groupe à la fin de la page.
Déposer dans les enfants d'une page dépliée affiche une ligne d'insertion avant
ou après l'image survolée. La
liste défile automatiquement près de ses bords. Les marqueurs manuels ne se
déplacent pas. L'ordre et les groupes choisis sont conservés dans `.vispamp`, y
compris après recalcul ou changement d'image par une suggestion. Le bouton
« Automatic pages » permet de revenir aux groupes déduits des débuts de page.

Les flèches **Undo / Redo**, à côté du titre Pages, annulent et rétablissent les
20 dernières opérations éditoriales : déplacement simple ou groupé, suppression,
ajout de suggestions, remplacement, rôle et retour à l'ordre automatique.
**Ctrl+Z** annule ; **Ctrl+Y** ou **Ctrl+Shift+Z** rétablit, aussi depuis Suggestions
détaché. Une opération sur un groupe compte pour une seule action. Strip et Board
se mettent à jour ensemble ; l'historique reste local à MP et ne réécrit jamais
Resolve. Les champs de texte gardent leur propre annulation.

Sauvegarder conserve l'historique de la session. Ouvrir un autre projet ou une
nouvelle analyse le remet à zéro ; un recalcul qui régénère les propositions
établit également une nouvelle base. Les réglages, le zoom et la simple sélection
ne sont pas des opérations éditoriales ; l'historique n'est pas enregistré dans
le fichier `.vispamp`.

Cet ordre est un ordre de lecture pour la préparation : les frames sources et
les rôles ne changent pas pendant le geste. Le bandeau le précise et la
confirmation de placement rappelle que les marqueurs Resolve restent aux
timecodes sources. Le placement ne transmet pas un ordre de lecture arbitraire
à un exporteur qui regroupe uniquement les marqueurs chronologiquement.

### Sens des réglages de sélection

Dans **Settings › Analysis › Long shots**, **Decompose long shots** active la
recherche de cadrages internes dans les plans plus longs que **Decompose shots
longer than (s)**, réglé par défaut sur **4.30 secondes** (4,3 secondes décimales).
Le seuil déclenche une recherche de changements visuels persistants, et non un
marqueur toutes les 4,3 secondes : un plan statique reste entier. Chaque partie
détectée conserve la préférence pour une image de fin de plan. Les règles standard
et les profils personnels bénéficient de cette décomposition, dans les limites
de qualité, d'espacement et de volume déjà configurées.

Ces réglages sont conservés avec les préférences, les fichiers de réglages et les
projets `.vispamp`. **Analyze** doit être relancé après leur modification, y
compris pour une analyse plus ancienne ; **Recalculate** ne peut pas découvrir de
nouvelles parties à partir des seules candidates déjà extraites.

« Sharpness » est un seuil de netteté mesurée des candidats, sans accentuation de
l'aperçu. Le relever écarte davantage d'images douces, en particulier parmi les
Extras. Pour une réplique, le repli configuré peut conserver une image quand
aucune candidate ne passe le filtre.

« Open mouth » est le seuil du score visuel de bouche ouverte. Le score doit
aussi dépasser celui de bouche fermée ; augmenter 0,20 vers 0,80 rend la
sélection plus stricte. Ce seuil ne représente ni une ouverture physique en
pourcentage ni un volume audio. Si aucune image ne convient, le repli peut
conserver une image portant « Mouth not verified ».

Ce curseur fixe un seuil de reconnaissance, pas le poids de la bouche face à la
fin du plan : le monter admet moins d'images, le baisser en admet davantage avec
un risque de confusion accru. Pendant une réplique, une bouche ouverte qui
passe les filtres de qualité dans la région de fin est prioritaire sur les
images fermées, avant le classement personnel. Une image de dialogue vérifiée
et de qualité reste aussi prioritaire lors de la réduction aux limites par page.
Hors dialogue, la préférence de fin de plan est conservée.

**Recalculate** utilise uniquement les candidates déjà mesurées. Il peut changer
les choix et les rôles, mais ne peut pas retrouver une bouche qui n'a jamais
été examinée ; une nouvelle recherche de candidates demande **Analyze**.

### Découpage des dialogues

L'analyse de **Audio 1** complète la détection des silences de Silero par un
modèle local recherchant des changements de voix probables. Un échange sans
silence peut ainsi fournir plusieurs tours de parole. MP répartit les images
examinées entre ces passages, puis privilégie les bouches ouvertes admissibles
pendant le dialogue, en standard comme avec un profil personnel. Les limites
de qualité, d'espacement et de volume restent applicables : un tour de parole
ne force pas à lui seul l'ajout d'un marqueur.

Un changement de voix n'identifie pas le personnage à l'écran. Une voix hors
champ, une narration et les plans de réaction restent possibles. Cette
extension ne transcrit pas les paroles, ne lit pas les sous-titres et n'attribue
pas de noms de personnages. Si le modèle de changements de voix est
indisponible ou échoue, MP conserve le découpage par activité vocale et signale
ce repli dans le résultat de l'analyse.

Pour un chapitre analysé avant cette extension, relancer **Analyze** afin de
rechercher les changements de voix et les nouvelles candidates. Les changements
mesurés sont conservés dans les projets `.vispamp` ; **Recalculate** les réutilise
ensuite avec les réglages de parole courants, sans relancer le modèle audio.
Aucun réentraînement d'Avatar n'est nécessaire pour bénéficier de ce découpage.

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

Les autres réglages déjà branchés dans `ui.py` (compression de l’histoire, silences, portion de fin de plan, plan d’action, In/Out, repli de bouche, réinitialiser, télécharger les modèles) ne disparaissent pas. Ils passent derrière un bouton « Réglages », hors de l’écran de travail. Les seuils de sélection recalculent les candidates existantes sans réinférence ; les réglages qui changent les images examinées, dont la décomposition des plans longs, nécessitent une nouvelle analyse.

### Budget global et compression

Réglages › Pages réunit le budget **Global markers** et la jauge de compression.
À 50 %, la référence par défaut est **12 minimum / environ 30 cible / 45 maximum
par minute**. Ces taux servent uniquement à calculer une fourchette pour toute
la durée analysée : 20 minutes donnent 240 à 900 marqueurs, avec une cible souple
autour de 600. Il n'existe aucun quota à remplir pour chaque minute : une minute
peut contenir 12 images et une autre 40 selon les scènes.

La jauge déplace ensemble le minimum, la cible et le maximum. À 0 %, le volume
de référence est doublé ; à 100 %, il est divisé par deux. Modifier les chiffres
repositionne la jauge selon le volume global. Les proportions d'une fourchette
personnalisée sont conservées lorsque la jauge est déplacée. Elle continue aussi
de guider le nombre de pages dans les bornes de pages existantes.

**Automatic totals from duration** calcule les totaux depuis l'In/Out analysé,
ou la timeline entière, trous compris, quand aucune plage n'est active. Le calcul
utilise les unités de la timeline et sa cadence réelle, y compris les champs en
50i. Minimum et maximum sont arrondis au supérieur, la cible au plus proche.
Décocher ce mode permet de saisir directement les trois totaux ; au premier
passage manuel, les valeurs calculées sont reprises, puis les valeurs manuelles
sont mémorisées séparément des taux.

Page start, Core et Extra comptent chacun comme une image, sans compter deux
fois un début de page. Les marqueurs manuels de ces rôles sont inclus et protégés.
La sélection conserve son résultat naturel lorsqu'il est déjà à environ 10 %
de la cible globale, dans les bornes minimum/maximum. Sinon elle le complète ou
le réduit avec les candidats mesurés disponibles. Netteté, bouche, flou,
espacements, doublons et limites par page restent prioritaires. Un minimum ou un
maximum impossible est signalé dans le bilan de la préparation, qui tient aussi
compte des suppressions et ajouts manuels.

Les modifications recalculent la sélection sans refaire l'analyse. Réglages et
projets sauvegardent ces valeurs. Les anciens projets dépourvus de ce budget
conservent leur compression et leur préparation ; le budget y reste désactivé
jusqu'à son activation explicite.

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

- « Lire la timeline » lit la vidéo 1 et l’audio 1, quels que soient leurs noms. Les pistes du dessus restent ignorées. Les conventions de nommage de l’exporteur Cue ne déclenchent pas d’avertissement dans MP.
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

Le menu « Project » propose « Open project… » (Ctrl+O), « Open Recent Project », « Save project » (Ctrl+S),
« Save project as… » (Ctrl+Maj+S) et « DaVinci project folder… ».

« Open Recent Project » conserve les dix derniers fichiers `.vispamp` ouverts ou
sauvegardés avec succès, le plus récent en tête, après redémarrage. Les noms
identiques affichent leur dossier ; l'infobulle donne toujours le chemin complet.
Les fichiers manquants sont signalés et désactivés. « Clear recent projects »
efface uniquement cette liste. Ouvrir un récent suit les mêmes confirmations de
sauvegarde et vérifications Resolve que « Open project… ».

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
