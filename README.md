# RailFine Analytics — France & Belgique

Application **locale** pour explorer le réseau ferroviaire français et belge, importer vos amendes
(SNCF, SNCB...) et comprendre **où, quand et sur quelles lignes** elles ont été dressées.

- Carte interactive (MapLibre) : lignes physiques, gares, itinéraires commerciaux par catégorie
  (TER, TGV, Intercités, Transilien, RER, SNCB), recherche de gare, fiches, plein écran, légende,
  calcul de trajet entre deux gares, chargement progressif par tuiles vectorielles.
- Import de documents : PDF natifs, PDF scannés, JPG/JPEG/PNG, import multiple, **OCR local
  (Tesseract)**, formulaire de validation avec champs incertains signalés, saisie manuelle,
  détection des doublons.
- Statistiques : nombre / montant total / montant moyen et médian, classements par ligne, train,
  gare, horaire, jour, mois, motif, transporteur, pays ; filtres ; exports CSV / JSON.
- Amendes sur la carte : tronçons colorés selon le nombre, le montant total, le montant moyen, le
  créneau horaire dominant ou l'évolution dans le temps (curseur mensuel).
- Aucune donnée personnelle ne quitte l'ordinateur. Pas de compte, pas de service payant.

---

## 1. Installation

Prérequis : **Python 3.11+**, **Node.js 18+** (uniquement pour compiler l'interface), **Tesseract**
(pour lire les scans et photos ; les PDF natifs fonctionnent sans).

### Tesseract (OCR local)

| Système | Commande |
|---|---|
| Windows | Installer depuis https://github.com/UB-Mannheim/tesseract/wiki (cocher les langues *French* et *Dutch*). Si `tesseract` n'est pas dans le PATH : `set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` |
| macOS | `brew install tesseract tesseract-lang` |
| Debian / Ubuntu | `sudo apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-nld` |

### Application

```bash
git clone <ce dépôt> && cd sncf
python -m venv .venv
# Windows : .venv\Scripts\activate      macOS/Linux : source .venv/bin/activate
pip install -e ".[dev]"

cd frontend && npm install && npm run build && cd ..
```

### Données ferroviaires de référence (une fois, puis de temps en temps)

```bash
railfine data update
```

Télécharge les sources ouvertes (voir section 4), construit la base `data/reference/rail.sqlite`
et le graphe du réseau. Chaque source est indépendante : si l'une est indisponible, elle est
signalée et les autres sont importées quand même. Options :

```bash
railfine data update --groups base,sncf,infrabel,gtfs      # défaut
railfine data update --groups osm                          # OpenStreetMap (volumineux, facultatif)
railfine data update --gtfs-sncf export.zip --gtfs-sncb sncb.zip   # GTFS téléchargés à la main
railfine data status
```

La même mise à jour est disponible dans l'interface (Paramètres > Référentiel ferroviaire).

## 2. Lancement

```bash
railfine serve            # http://127.0.0.1:8000
```

Sous Windows, `start.bat` fait la même chose. Le serveur n'écoute que sur `127.0.0.1` :
vos amendes ne sont pas accessibles depuis le réseau.

Développement de l'interface (rechargement à chaud) : `railfine serve` dans un terminal,
`cd frontend && npm run dev` dans un autre, puis http://127.0.0.1:5173.

### Données d'exemple FICTIVES

Pour essayer l'application avant d'importer vos documents : Paramètres > *Charger des amendes
fictives* et *Importer des documents fictifs* (ou `railfine demo load`, `railfine demo documents`).
Elles sont marquées « exemple » partout, exclues d'un clic des statistiques, et supprimables
(`railfine demo remove`). Les gares citées sont réelles, les amendes ne le sont pas.

## 3. Utilisation

| Page | Rôle |
|---|---|
| Tableau de bord | Chiffres clés, évolution, heures, principaux classements, tâches restantes |
| Carte ferroviaire | Réseau, gares, itinéraires, amendes ; panneau latéral (Amendes, Couches, Détails, Itinéraire) |
| Mes amendes | Liste filtrable, fiche détaillée, correction, correspondance cartographique, document source |
| Importer | Dépôt de fichiers, suivi de l'analyse, validation des champs extraits, saisie manuelle |
| Statistiques | Filtres (période, pays, transporteur, ligne, gare, type de train, motif, statut), classements, graphiques, exports |
| Paramètres | OCR, carte, mise à jour des données, GTFS manuel, sauvegarde/restauration, exemples, effacement |

### Import et validation

1. Déposez un ou plusieurs fichiers. Le **type réel** est vérifié (signature binaire), la taille
   limitée (20 Mo par défaut), un fichier déjà importé est reconnu (empreinte SHA-256).
2. Le texte des PDF natifs est lu directement ; les pages sans texte et les images passent par
   l'OCR Tesseract **local**.
3. Les champs sont détectés avec un indice de confiance et l'extrait justificatif. Les champs
   incertains sont surlignés ; un champ non trouvé reste vide (rien n'est inventé).
4. Un document contenant plusieurs numéros de dossier est découpé en plusieurs amendes ; vous
   pouvez aussi ajouter une amende supplémentaire à un document.
5. Validez : le numéro de dossier sert à détecter les doublons (même numéro = doublon certain ;
   même date + heure/montant/gares = doublon probable).

### Correspondance avec la carte (du plus fiable au moins fiable)

| Statut | Signification |
|---|---|
| `train_confirmed` | numéro de train trouvé dans les horaires GTFS **à la date de l'amende**, desservant les gares : le tracé suit ses arrêts |
| `manual` | trajet imposé par vous (gares intermédiaires « via ») |
| `path_inferred` | gares connues, tracé **présumé** = plus court chemin sur le réseau physique (à confirmer) |
| `train_route` | train identifié mais portion parcourue inconnue |
| `od_only` | gares identifiées, aucun tracé calculable (relation affichée en pointillé, ce n'est pas une voie) |
| `station_only` | une seule gare identifiée |
| `none` | non géolocalisée : l'amende reste comptée dans les statistiques générales |

Les homonymes (« Saint-Denis », « Lille »...) ne sont jamais tranchés au hasard : l'application
propose les candidats et vous choisissez. Vous pouvez valider une correspondance, imposer des
gares de passage, ou désactiver la géolocalisation d'une amende.

### Lire les statistiques

- Chaque classement existe **par nombre**, **par montant total** et **par montant moyen**.
- Ces chiffres décrivent vos amendes, **pas un risque** : sans le nombre total de vos trajets par
  ligne ou par horaire, aucun taux de verbalisation ne peut être calculé.
- Une concentration est une corrélation (elle peut refléter vos habitudes), pas une causalité.
- Une amende dont le trajet emprunte plusieurs lignes physiques compte pour chacune : les totaux
  par ligne ne s'additionnent pas.

## 4. Sources de données, licences et limites

Trois objets distincts sont gérés séparément :
**ligne physique** (infrastructure, ex. ligne RFN 830000), **itinéraire commercial**
(ex. « TER K12 Lyon – Grenoble »), **circulation** (un train identifié par son numéro, avec ses
arrêts et ses dates).

| Source | Contenu | Licence | Mise à jour | Limites |
|---|---|---|---|---|
| SNCF Réseau — *Formes des lignes du RFN*, *Lignes par statut*, *Lignes LGV et par écartement* (data.sncf.com, API Opendatasoft v2.1) | lignes physiques, code ligne, statut, LGV | Licence Ouverte / ODbL selon jeu | semestrielle à annuelle | précision décamétrique (1/50 000), pas de dessertes |
| SNCF — *Gares de voyageurs*, *Liste des gares* | gares, codes UIC, segment DRG | ODbL / Licence Ouverte | plusieurs fois par an | « liste des gares » inclut des points sans voyageurs |
| SNCF Voyageurs — GTFS TER, Intercités, TGV | itinéraires commerciaux, numéros de train, arrêts, dates | ODbL | quotidienne à hebdomadaire | **horaires théoriques** sur une fenêtre de quelques semaines/mois, pas de temps réel, pas de tracés (reconstruits sur le réseau) |
| Infrabel Open Data | lignes belges (numéros Infrabel), points opérationnels | licence Infrabel open data | plusieurs fois par an | identifiants de jeux changeants (recherche automatique en secours) |
| SNCB — GTFS | itinéraires et circulations belges | conditions SNCB | hebdomadaire | accès parfois soumis à enregistrement : import manuel possible |
| OpenStreetMap (Overpass) | voies `railway=rail`, relations `route=train` | ODbL | continue | complétude variable ; requêtes lourdes, à lancer avec modération |
| Trainline EU stations (GitHub) | gares FR/BE avec UIC | ODbL | irrégulière | contient quelques arrêts d'autocars ; « gare principale » peu fiable |
| iRail stations (GitHub) | gares belges, noms FR/NL/DE/EN, fréquentation | CC0 | irrégulière | — |
| Natural Earth 1:10m | frontières (fond hors ligne) et **réseau de secours** | domaine public | pluriannuelle | réseau très généralisé, sans nom de ligne : n'est utilisé que si aucune source officielle n'est importée pour le pays |
| Fond CARTO Dark Matter (en ligne, désactivable) | fond de carte | © OSM, © CARTO | — | reçoit uniquement la zone affichée |
| OpenRailwayMap (en ligne, facultatif) | calque d'infrastructure détaillée | CC-BY-SA | — | à activer dans Paramètres |

L'application **ne prétend pas** disposer d'horaires en temps réel ni de la liste exhaustive des
circulations : seules les sources ci-dessus, à la date de leur import, sont utilisées. La date de
chaque import et son résultat sont affichés dans Paramètres.

> Note sur l'environnement de développement de cette version : le conteneur de développement
> n'avait pas accès aux portails data.sncf.com, opendata.infrabel.be, Overpass ni data.gouv.fr
> (politique réseau). Les importeurs de ces sources ont donc été écrits d'après leurs formats
> documentés et testés sur des fichiers de format équivalent ; les sources GitHub (Trainline,
> iRail, Natural Earth) ont été importées réellement. Lancez `railfine data update` sur votre
> machine : si un identifiant de jeu a changé, le rapport l'indique et la recherche plein texte du
> catalogue prend le relais.

## 5. Architecture

```
backend/railfine/
  config.py            chemins (data/reference vs data/user), paramètres persistés
  categories.py        vocabulaires : types de trains, motifs, statuts, statuts de géolocalisation
  reference/           DONNÉES DE RÉFÉRENCE
    sources.py           registre documenté des sources (licence, fréquence, limites)
    importers/           SNCF Open Data, Infrabel, OSM/Overpass, GTFS, Trainline, iRail, Natural Earth
    store.py             SQLite + R*Tree : lines (physique), routes (commercial), trains (circulations), stations
    normalize.py         normalisation des noms (accents, abréviations, FR/NL)
    matching.py          appariement des gares, homonymes, confiance
    graph.py             graphe du réseau physique, plus court chemin (A*)
    tiles.py             tuiles vectorielles MVT générées à la volée (simplifiées par zoom)
  ingest/              IMPORT DES DOCUMENTS
    filetypes.py         vérification du type réel, noms sûrs
    textextract.py       texte PDF (pdfium) + OCR Tesseract local
    parser.py            détection des champs avec confiance, découpage multi-amendes
    jobs.py              traitement en arrière-plan
  user/                DONNÉES PERSONNELLES
    store.py             documents, brouillons, amendes, liens, tracés (SQLite)
    geomatch.py          rattachement amende -> gares / train / itinéraire / lignes
    service.py           validation des saisies, doublons
    backup.py            sauvegarde / restauration / effacement
  analytics/           RÉSULTATS D'ANALYSE
    stats.py             statistiques pandas, classements, filtres
    mapdata.py           couches cartographiques des amendes
  api/                 routes FastAPI
  main.py, cli.py      application, ligne de commande
frontend/src/          React + TypeScript + MapLibre GL + ECharts
  map/                 style et couches de la carte (composants cartographiques)
  pages/, components/  interface
data/                  (non versionné) reference/ = référentiel, user/ = vos données
```

Choix techniques : FastAPI, SQLite (avec index spatial R*Tree, sans dépendance PostGIS),
pandas, shapely, pypdfium2 (lecture PDF sans exécution de contenu), Tesseract en sous-processus,
rapidfuzz ; React 19, MapLibre GL 5 (WebGL, tuiles vectorielles), ECharts 5.

## 6. Sécurité et confidentialité

- Stockage local uniquement (`data/user/`), serveur limité à `127.0.0.1`, en-têtes `Host`
  contrôlés (anti DNS-rebinding), en-tête obligatoire sur les requêtes modifiantes (anti-CSRF),
  politique de sécurité du contenu (CSP) stricte.
- Fichiers importés : type réel vérifié, taille et nombre de pages limités, nom d'origine jamais
  utilisé comme chemin (stockage par empreinte SHA-256), aucune exécution de macros ou de
  JavaScript PDF (pdfium sans environnement de formulaires), contenu actif signalé, protection
  contre les images « bombes de décompression ».
- Minimisation : nom, adresse et identité figurant sur les documents ne sont pas extraits ; le
  numéro de dossier n'est conservé que sous forme d'empreinte HMAC salée (3 derniers caractères
  affichés) ; le texte extrait est effacé après validation (option).
- Suppression d'un document (avec ou sans ses amendes), effacement complet, sauvegarde ZIP et
  restauration contrôlée (entrées autorisées uniquement, intégrité SQLite vérifiée).
- Le fond de carte en ligne ne reçoit que les coordonnées des tuiles affichées ; il se désactive
  dans Paramètres (fond hors ligne Natural Earth).

## 7. Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `RAILFINE_DATA_DIR` | `./data` | dossier des données |
| `RAILFINE_HOST` / `RAILFINE_PORT` | `127.0.0.1` / `8000` | écoute du serveur |
| `TESSERACT_CMD` | `tesseract` | chemin de l'exécutable Tesseract |
| `RAILFINE_ALLOWED_HOSTS` | — | noms d'hôte supplémentaires autorisés |

Les autres réglages (langues OCR, taille maximale, conservation du texte, fond de carte,
OpenRailwayMap, seuil d'appariement des gares, trajets présumés) sont dans Paramètres et
`data/user/settings.json`.

## 8. Tests

```bash
python -m pytest            # backend : extraction, OCR, appariement, graphe, statistiques, API
cd frontend && npm run typecheck
```

Les tests utilisent un réseau et des documents **synthétiques** (dossier `backend/tests/`),
jamais vos données. Les tests OCR sont ignorés si Tesseract n'est pas installé.

## 9. Limites connues

- Sans GTFS importé, les numéros de train ne peuvent pas être reliés à un parcours : les trajets
  sont alors présumés (plus court chemin) et signalés comme tels.
- Un GTFS ne couvre qu'une période : une amende ancienne peut viser un train qui n'y figure plus
  (la correspondance est alors marquée « date non vérifiée »).
- La qualité de l'OCR dépend du scan ; vérifiez toujours les champs surlignés.
- Les formats de documents d'amendes varient : l'extracteur reconnaît les libellés usuels
  (FR/NL) ; un document atypique demandera plus de corrections manuelles.
