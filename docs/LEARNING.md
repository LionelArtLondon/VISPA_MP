# Apprentissage personnel de VISPA MP

Le bouton **Learning**, dans l'en-tête, permet de constituer des
références puis d'entraîner un profil de sélection local. Les modèles visuels et
de parole existants restent en place. Un petit modèle apprend à classer les
images candidates selon les choix validés de l'utilisateur, séparément pour
Core, Extra et début de page.

L'attribution Core/Extra peut aussi être apprise à partir des rôles explicitement
validés. Elle utilise un modèle distinct du classement des images : une bonne
image Extra n'est pas une mauvaise image Core. Aucun réglage supplémentaire
n'est nécessaire.

Le découpage des dialogues est commun au standard et aux profils personnels.
En complément des silences, un modèle local repère des changements de voix
probables pour répartir les candidates entre les tours de parole et mieux
chercher les bouches ouvertes. Il ne reconnaît pas les noms des personnages et
ne garantit pas que la voix soit celle du personnage visible : les voix hors
champ et les réactions restent possibles. Les anciens profils Avatar restent
compatibles ; relancer **Analyze** sur le chapitre suffit pour obtenir ce
nouveau contexte, sans réentraîner ni réimporter les références existantes.
Les caractéristiques de parole utilisées par l'apprentissage restent
compatibles et les rôles validés conservent leur priorité.

## Voir et choisir le profil actif

Le bloc **Selection profile**, toujours visible sous Strip et Board, affiche
**Active: MP standard rules** ou **Active: nom du profil**. Cette indication
décrit le classement réellement utilisé pour les propositions et les nouvelles
analyses. **Profiles…** ouvre le même choix dans **Settings › Profiles**.

Choisir un profil dans la liste, ou **Load profile…** pour ouvrir un fichier
JSON, prépare un choix sans l'activer. Le message **Selected, not applied**
signale ce choix en attente. **Use selection** l'applique, recalcule la
sélection à partir des mesures existantes et mémorise le choix. L'indication
Active reste celle du profil précédent jusqu'à cette action. L'entraînement
et la sauvegarde d'un profil ne l'activent pas automatiquement.

Le profil change la priorité entre les images admissibles : le classement
personnel passe avant les préférences visuelles standard. Les filtres, les
fourchettes de marqueurs, la compression, les limites par page et les corrections
manuelles gardent leur fonctionnement. Aucune valeur de réglage n'est remplacée
lors d'un changement de profil. Les préférences visuelles souples, comme le poids
de l'expression, peuvent être moins déterminantes quand le classement personnel
est actif. Choisir **MP standard rules**, puis **Use selection**, revient au
classement standard avec les réglages courants ; cela ne réinitialise pas MP.

Un profil intégré à un projet `.vispamp` est indiqué dans la liste et reste
utilisable sans son fichier d'origine. Pendant une analyse ou un import, les
commandes de changement de profil sont désactivées. Aucun choix de profil ne
place de marqueurs dans Resolve.

### Comparer dans deux fenêtres

Après l'analyse d'un chapitre, choisir un profil personnel dans **Selection
profile**, puis **Compare**. Le profil peut être simplement sélectionné, sans
être activé ; si les règles standard sont sélectionnées mais qu'un profil est
encore actif, la comparaison utilise ce profil actif.

Deux fenêtres de consultation s'ouvrent côte à côte : **MP standard rules** et
le nom du profil personnel. Elles utilisent les mêmes mesures et réglages,
sans relancer l'extraction ou les modèles d'images. La revue de travail, le
profil actif et les préférences restent inchangés. Ces fenêtres ne se
connectent pas à Resolve, n'enregistrent pas de préférences et ne placent pas
de marqueurs.

La comparaison reconstruit deux sélections automatiques : les ajouts,
changements de rôles, exclusions et déplacements manuels faits dans MP sont
écartés des deux vues. Ils restent conservés dans la revue de travail. Les
marqueurs manuels déjà présents dans Resolve restent protégés. Examiner les
pages et les images dans chaque fenêtre ; les deux vues sont indépendantes.
Fermer les fenêtres de comparaison ramène au travail courant. Une nouvelle
comparaison remplace la paire précédente.

## Ajouter des chapitres de référence

1. Ouvrir dans Resolve un projet et une timeline dont les marqueurs sont
   terminés, avec les médias sources accessibles sur Vidéo 1. Lancer le pont
   Workspace › Scripts › VISPA_MP s'il n'est pas déjà connecté.
2. Dans Learning, cocher que les choix ont été revus et approuvés. Donner si
   besoin un nom au chapitre et un groupe commun à toutes ses versions.
   Pour écarter générique et résumé, placer les points In et Out autour de la
   partie utile dans Resolve et cocher **Import only Resolve In/Out range**.
3. Choisir **Import current Resolve timeline**. Vérifier le nom de la timeline
   et le nombre de marqueurs dans la confirmation.
4. Répéter pour d'autres chapitres. **Import reviewed .vispamp…** permet aussi
   d'importer une préparation validée sans reconnecter Resolve.

L'import lit les marqueurs et extrait leurs images exactes, même lorsqu'elles
ne figuraient pas parmi les candidats automatiques. Les verts constituent des
images Core et des débuts de page ; les bleus des Core ; les cyan des Extras.
Les marqueurs créés automatiquement par MP sont ignorés par défaut. L'option
pour les inclure s'utilise après validation humaine de ces marqueurs.

Une réimportation de la même timeline remplace sa référence précédente. Les
références contiennent des caractéristiques mesurées et les rôles validés,
sans copie de la vidéo. Les images extraites restent dans le cache local. Un
projet `.vispamp` peut servir hors ligne si ses images marquées sont présentes
dans son analyse enregistrée.

Les clips doivent pouvoir être reliés sans ambiguïté aux images sources. Les
ralentis/accélérés, les chevauchements non résolus et les changements de cadence
qui ne permettent pas de vérifier l'image exacte sont refusés avec une
explication. L'import ne change ni la timeline Resolve ni la revue MP ouverte.

L'option In/Out de Learning est indépendante de celle de l'analyse normale.
Lorsqu'elle est cochée, les marqueurs et les exemples d'apprentissage hors de
la plage sont exclus. Les deux points doivent être définis et valides, sinon
l'import donne une explication et ne sauvegarde pas de référence incomplète.
L'extraction peut encore lire la vidéo source complète pour repérer les plans ;
seuls les exemples de la plage sont mesurés pour l'apprentissage. Une référence
déjà importée sur toute la timeline doit être réimportée pour bénéficier de
cette exclusion.

### Importer plusieurs projets Resolve en lot

1. Dans chaque projet, préparer une timeline appelée exactement
   **Personal Learning**. Elle peut être une copie de la timeline validée ;
   les autres timelines peuvent rester dans le projet. Définir les In/Out
   sur cette copie, puis enregistrer le projet dans Resolve.
2. Dans MP, ouvrir **Learning › Batch import Resolve projects…**. La liste
   présente les projets de la bibliothèque actuellement connectée, avec leurs
   dossiers. **Connected library** affiche son nom et son type pour vérifier la
   connexion. **Refresh project library** recharge cette liste sans ouvrir de
   projet. Si l'ancien pont ne reconnaît pas cette commande, relancer
   **Workspace › Scripts › VISPA_MP** dans Resolve puis réessayer.
3. Cocher les projets voulus, confirmer que les marqueurs ont été validés et
   garder **Personal Learning** comme nom de timeline commun. **Use each
   timeline's In/Out range**, activé par défaut, utilise les points propres à
   chaque chapitre ; le désactiver importe les timelines entières.
4. Enregistrer le travail Resolve en cours, puis cliquer **Import selected
   projects**. MP ouvre chaque projet, sélectionne la timeline exacte, extrait
   et sauvegarde sa référence avant de passer au suivant. Le nom de la
   référence est celui du projet, puisque les timelines portent le même nom.

Les cases de sélection ont leur propre colonne. La touche Espace coche ou
décoche la ligne courante, même après un clic sur le nom du projet. Agrandir
la fenêtre par son coin inférieur droit donne plus de hauteur à la liste des
projets ; le bilan conserve sa hauteur.

Une timeline absente ou portant un nom ambigu, un In/Out invalide ou un média
inexploitable est signalé dans le bilan du chapitre. Les autres projets sont
ensuite traités. Une perte de connexion arrête le lot. **Cancel operation**
conserve les références déjà terminées et évite d'ouvrir les projets suivants.
Resolve reste sur le dernier projet ouvert ; MP conserve la revue courante.
Le traitement n'enregistre ni ne force la fermeture d'un projet Resolve.

Une erreur de lecture de bibliothèque n'est pas présentée comme une bibliothèque
vide : le statut et le rapport conservent son explication. Une bibliothèque
effectivement vide est signalée après une lecture réussie. Vérifier la
bibliothèque sélectionnée dans le gestionnaire de projets Resolve, puis
rafraîchir ; MP n'a pas besoin du dossier physique où Resolve stocke sa base.

Il n'est pas nécessaire de supprimer les autres timelines. Sans nom commun,
laisser le champ vide est accepté uniquement pour les projets contenant une
seule timeline. Une copie de timeline possède une nouvelle identité : elle
crée une nouvelle référence et ne remplace pas celle de la timeline d'origine.

Un fichier `.drp` absent de la bibliothèque doit d'abord être importé dans le
gestionnaire de projets Resolve (**Import Project…**, ou glisser le fichier
dans le gestionnaire). Il peut rester dans son dossier de chapitre habituel ;
les fichiers récents ne constituent pas la liste utilisée par MP. Le lot ne
crée pas automatiquement de projets à partir de fichiers `.drp`.

## Entraîner et utiliser un profil

**Train and save profile** entraîne le profil et enregistre automatiquement le
modèle et son rapport dans la bibliothèque locale. Les chapitres de référence
sont eux-mêmes enregistrés dès que leur import se termine ; il n'est pas
nécessaire d'attendre l'entraînement pour les conserver. Avec
plusieurs groupes de chapitres, un groupe entier est gardé hors entraînement
pour comparaison ; le groupe peut être choisi explicitement. Avec un seul
groupe, un profil peut être entraîné mais le rapport indique l'absence de
validation indépendante. Les versions partageant les mêmes médias ne doivent
pas être réparties entre entraînement et validation : MP détecte les chemins
sources communs et demande de les placer dans le même groupe.
Les copies ou nouveaux exports d'une même vidéo sous des chemins différents
doivent être regroupés manuellement : cette vérification ne recherche pas les
doublons par le contenu complet des fichiers vidéo.

### Choisir et contrôler les références

La case à gauche de chaque chapitre permet de l'inclure ou de l'écarter des
prochains entraînements et comparaisons, sans le supprimer. Ce choix est
mémorisé. Une réimportation conserve cette sélection et le groupe corrigé ; un
groupe explicitement renseigné au moment de l'import remplace le précédent.
Les profils déjà entraînés restent ceux enregistrés lors de leur création.

Pour retirer des références, sélectionner leurs lignes (Ctrl ou Maj pour en
sélectionner plusieurs), puis **Remove reference…**, à côté d'Inspect et Edit
source group. Confirmer la liste des chapitres. Cette action les retire des
prochains entraînements, sans changer Resolve, la revue courante ou les profils
déjà entraînés. Leurs fichiers JSON sont conservés dans
`cache/learning/reference_archive/` ; les médias et aperçus ne sont pas effacés.
Décocher une référence suffit pour l'exclure temporairement sans la retirer.

Sélectionner un ou plusieurs chapitres puis **Edit source group…** pour corriger
leur groupe après import. Toutes les versions d'un même chapitre doivent
partager le même groupe. Si un même chemin vidéo apparaît dans plusieurs
groupes inclus, le bilan le signale et l'entraînement ou la comparaison demande
de corriger le regroupement.

Sélectionner un chapitre puis **Inspect reference…**, ou double-cliquer son nom,
pour vérifier visuellement les exemples importés. Les filtres isolent les Core,
les Extras, les débuts de page ou les alternatives non marquées. Un clic sur une
vignette affiche l'image agrandie, son rôle et son repère temporel. La grille
avance par lots de 24 images pour rester utilisable sur un chapitre long.
**Copy example details** copie les informations de l'exemple sélectionné pour
accompagner un retour de test.

L'inspection lit uniquement les vignettes déjà extraites et ne change pas les
références ni le travail ouvert. Une ancienne référence sans chemin de vignette,
ou un cache supprimé, conserve ses caractéristiques d'apprentissage ; un message
signale l'aperçu indisponible. Réimporter le chapitre approuvé pour reconstituer
ses aperçus. Les images ne sont pas incorporées dans les fichiers JSON des
références et ne sont pas réextraites pendant l'inspection.

Le bilan sous la liste compte les débuts de page, les Core et les Extras des
références incluses. Il affiche le rapport Extras/Core et la moyenne de chaque
rôle par page observée. Ces pages sont délimitées chronologiquement par les
marqueurs verts ; les images avant le premier vert sont écartées de ces
moyennes, et la dernière page peut être partielle. Ces chiffres décrivent les
exemples importés, sans modifier les réglages de sélection. L'absence d'exemples
pour un rôle est signalée : il faut alors ajouter des chapitres où ce rôle a été
validé pour pouvoir l'apprendre.

### Comparer sur chaque chapitre

**Validate across chapters** est disponible avec au moins deux groupes inclus.
Chaque groupe est tenu à l'écart à son tour et un modèle neuf est entraîné
uniquement sur les autres. Le rapport montre les résultats Core, Extra et début
de page pour chaque chapitre, puis leur moyenne avec le même poids par groupe.
Les rôles sans comparaisons exploitables sont signalés et écartés de la moyenne,
avec le nombre de chapitres effectivement évalués.

Cette comparaison mesure l'accord sur des préférences entre candidats face aux
pondérations visuelles de référence. Elle ne compare pas la qualité complète
d'une planche ni le profil déjà actif dans MP. Elle ne crée ni n'active un profil.
Une progression sur ces scores sert d'indice à vérifier ensuite sur une vraie
préparation de marqueurs.

Ces comparaisons historiques portent sur le classement des candidates dans
chaque rôle. L'évaluation de l'attribution Core/Extra est distincte et figure
dans le rapport du profil après **Train and save profile**, sur son groupe
réservé hors entraînement.

Le dernier rapport est enregistré localement dans
`cache/learning/validation/last.json`. **View validation report** permet de le
rouvrir après redémarrage et **Save report as…** d'en conserver une copie JSON.
Le rapport décrit les chapitres présents lors de son calcul : relancer la
comparaison après modification des références ou de leurs groupes. Une
annulation conserve le dernier rapport terminé.

Le rapport mesure l'accord sur des préférences entre images candidates,
comparé à des pondérations visuelles de référence. Il ne mesure pas la qualité
éditoriale d'une planche complète. Une image non marquée est une alternative
faible, pas une erreur confirmée. Les poses quasi identiques sont écartées des
comparaisons. Un rôle sans comparaisons exploitables continue d'utiliser les
règles standard.

L'entraînement n'active pas automatiquement le résultat. Choisir le profil puis
**Use selected profile** pour recalculer la sélection. Le choix **Standard
rules** désactive le profil. Les seuils de netteté, de flou et de bouche, les
espacements, les limites par page et la protection des marqueurs manuels
continuent de s'appliquer. Les images ajoutées, les rôles choisis à la main,
les exclusions et l'ordre de lecture manuel restent prioritaires.
Le profil apprend le classement des candidats admissibles et, lorsque les
références contiennent les deux rôles, une préférence d'attribution Core/Extra.
Il ne remplace pas la segmentation des plans ni les limites de volume. Les
limites de région, notamment la fin de plan pour l'image Core, restent celles
des réglages de sélection.

### Améliorer les rôles avec des corrections

Dans un même cadrage où seuls quelques objets ou un geste bougent, plusieurs
images peuvent rester utiles sans avoir toutes le rôle Core. Après sélection,
MP conserve les points clés et peut classer les étapes intermédiaires en Extra,
sans ajouter ni retirer d'image et sans déplacer les débuts de page. Ce
traitement standard s'applique aussi avec un profil personnel. Il ne force pas
un quota de deux Core : les répliques, les changements de cadrage, les choix
manuels et le minimum de Core par page restent protégés.

Pour apprendre une correction précise :

1. Dans la préparation de travail, faire un clic droit sur les images à corriger
   et choisir **Core** ou **Extra**, puis vérifier le chapitre.
2. Sauvegarder la préparation `.vispamp` et l'importer avec **Import reviewed
   .vispamp…**, après confirmation que ses choix ont été approuvés.
3. Réentraîner avec **Train and save profile**, contrôler le rapport puis
   activer le nouveau profil avec **Use selected profile**.

Le modèle d'attribution apprend uniquement les images marquées Core (début de
page compris) ou Extra ; les candidates non marquées ne sont pas utilisées
comme exemples de rôle. Les groupes de chapitres d'entraînement et de validation
restent séparés. Le rapport distingue son accord équilibré Core/Extra des
comparaisons de classement ; ce score ne mesure pas la qualité d'une planche.
Les préférences apprises guident les étapes intermédiaires admissibles, sans
forcer un changement de rôle contre les protections éditoriales.

Les profils déjà enregistrés restent compatibles et gardent leurs classements.
Ils utilisent la règle contextuelle standard jusqu'à un réentraînement ajoutant
le modèle d'attribution. Les références déjà importées conservent leurs rôles :
il n'est pas nécessaire de tout réimporter pour entraîner cette extension.
Un retour textuel ou une capture précise les critères et peut guider une règle
vérifiable ; il ne modifie pas directement les poids d'un profil et ne remplace
pas des rôles approuvés sur les images sources.

Le profil actif est embarqué dans le projet `.vispamp` : sa réouverture ne
dépend pas d'un chemin de profil présent sur un autre ordinateur. Les profils
peuvent aussi être chargés depuis leur fichier JSON. Un profil manquant au
démarrage entraîne un retour signalé aux règles standard.

Après l'entraînement, **Save profile as…** enregistre une copie du profil
sélectionné dans le dossier choisi. Ce fichier JSON conserve les paramètres
appris et le rapport ; il peut être rouvert avec **Load profile…**. Cette copie
n'entraîne pas un nouveau modèle et n'active pas le profil. Le bouton est
disponible lorsqu'un profil entraîné est sélectionné, y compris un profil
embarqué dans un projet `.vispamp`. **Standard rules** n'est pas un profil à
exporter. Le statut confirme le nom du fichier après une sauvegarde réussie.

## Stockage et fonctionnement

- Références : `cache/learning/references/*.json`.
- Profils : `cache/learning/profiles/*.json`.
- Dernière comparaison entre chapitres : `cache/learning/validation/last.json`.
- Ces dossiers sont ignorés par Git ; les données ne sont pas envoyées à un
  service externe.
- Les profils sont des fichiers JSON numériques validés, jamais des objets
  Python exécutables. Une version de caractéristiques incompatible est refusée.
- Extraction et entraînement tournent en arrière-plan et peuvent être annulés.

Le modèle utilise des caractéristiques relatives de netteté, de bouche,
d'expression, de composition, de mouvement et de position dans un plan ou une
réplique. Il n'utilise pas le nom du chapitre ni le timecode absolu comme
caractéristique. L'apprentissage compare des paires d'images avec une
régularisation autour de pondérations visuelles de départ ; le volume des
comparaisons est borné pour conserver un entraînement local utilisable.

Les corrections futures n'entraînent rien en silence : réimporter explicitement
un chapitre approuvé, puis entraîner un nouveau profil. L'ordre éditorial libre
d'une préparation est conservé dans la référence mais n'est pas actuellement
appris comme un moteur de mise en page ; les marqueurs Resolve conservent leur
ordre chronologique.

## Premier essai conseillé

1. Importer trois à cinq chapitres déjà terminés, dont des scènes d'action avec
   les Extras choisis à la main et des scènes de dialogue. Deux groupes
   suffisent techniquement pour comparer ; davantage de chapitres variés
   permettent de mieux observer la stabilité des résultats.
2. Vérifier les groupes de sources et les comptes Core/Extra dans le bilan.
   Utiliser **Inspect reference…** pour contrôler quelques images et leurs rôles,
   puis écarter les préparations incomplètes ou les choix encore provisoires.
3. Lancer **Validate across chapters**. Examiner le score de chaque rôle et les
   chapitres où il régresse, ainsi que les comparaisons manquantes.
4. Nommer le profil et choisir **Train and save profile**, consulter sa propre comparaison sur le groupe réservé,
   puis l'activer explicitement pour un essai sur un autre chapitre.
   **Save profile as…** permet de garder une copie à l'emplacement de son choix.
5. Enregistrer la préparation standard avant de comparer les propositions
   personnalisées. Vérifier les images retenues et les Extras à l'œil : les
   scores de classement ne remplacent pas ce contrôle éditorial.

L'apprentissage du rythme, du nombre total d'images et des limites de pages reste
une évolution distincte. L'attribution Core/Extra réévalue les rôles des images
retenues, sans imposer leurs quantités à l'utilisateur.
