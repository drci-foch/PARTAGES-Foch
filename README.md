# PARTAGES — Hôpital Foch

Préparation des données pour l'évaluation des modèles du projet [PARTAGES](https://www.health-data-hub.fr/projets/partages) (Health Data Hub).

Foch évalue les cas d'usage : **CU1, CU2, CU3, CU5a, CU5b**.

---

## Avancement

| CU | Titre | Statut |
|----|-------|--------|
| **CU1** | Pseudonymisation des CR médicaux | 🟡 Extraction terminée — annotation en attente |
| **CU2** | Codage CIM-10 depuis CRH | 🟡 Pipeline prêt — en attente liste GHM |
| **CU3** | Résumé automatique des CR médicaux | 🔴 Non démarré |
| **CU5a** | Identification automatique des biomarqueurs en oncologie | 🟡 Extraction terminée — annotation en attente |
| **CU5b** | Analyse de la réponse aux traitements en oncologie | 🟡 Extraction terminée — annotation en attente |

---

## TODO

### CU1 — Pseudonymisation *(extraction terminée)*

- [ ] Lancer **pseudoFoch** sur les fichiers `WP1_CU1/output/txt/` pour générer un pré-annotation automatique
- [ ] Annoter manuellement les 400 CR avec **INCEpTION** (format JSON UIMA CAS)
- [ ] Vérifier la couverture des strates après annotation (voir `metadata_cu1.csv`)
- [ ] Livrer les fichiers annotés au Health Data Hub

### CU2 — Codage CIM-10 *(pipeline prêt)*

- [ ] **Obtenir la liste des GHM** de l'annexe PARTAGES auprès du porteur de projet
- [ ] Renseigner `ghm_whitelist` dans `WP2_CU2/config.py`
- [ ] Supprimer `WP2_CU2/output/cu2_dataset.csv` si des lignes invalides subsistent
- [ ] Relancer `python WP2_CU2/fetch_rss.py` (si `pool_rss.csv` absent ou obsolète)
- [ ] Relancer `python WP2_CU2/extract_cu2.py`
- [ ] Vérifier le taux de séjours avec texte extrait dans `cu2_stats.csv`
- [ ] Livrer `cu2_dataset.csv` au Health Data Hub *(ne pas livrer `cu2_correspondance_INTERNE.csv`)*

### CU3 — Résumé automatique des CR médicaux

- [ ] Lire le guide PARTAGES v29.01.26 — section CU3
- [ ] Identifier les sources de données disponibles dans Easily selon le format attendu des CR.
- [ ] Créer `WP3_CU3/`

### CU5a — Biomarqueurs en oncologie *(extraction terminée)*

- [x] **Décision OCR** : pas de méthode d'OCR fiable → les documents à océriser (scans, ex. génétique) sont **écartés**, on ne garde que la couche texte native
- [x] Accès au lecteur réseau `S:\Envoi-EDS-PMSI` (RSS) validé — localisation tumorale calculée
- [x] Extraction lancée (`fetch_pool.py` + `extract_cu5a.py`) → **150 CR** (147 anapath + 3 génétique)
- [x] Équilibrage par localisation contrôlé dans `metadata_cu5a.csv` (15 localisations)
- [ ] **Décider du faible volume de génétique** (3/150) : acceptable en l'état, ou investiguer une solution d'OCR fiable pour intégrer les rapports numérisés (Institut Curie)
- [ ] Clarifier les **règles d'annotation** et finaliser les **templates INCEpTION** : liste + normalisation des biomarqueurs (valeurs, unités, statuts IHC/FISH/NGS) ; cas particuliers (documents multi-CR, mentions négatives/absentes)
- [ ] Annoter les 150 CR avec **INCEpTION** (JSON UIMA CAS) puis livrer au Health Data Hub

### CU5b — Réponse aux traitements en oncologie *(extraction terminée)*

- [x] Périmètre des UF d'oncologie **confirmé** (`oncology_uf_codes` = 324A / 324E / 324B)
- [x] Extraction lancée (`fetch_pool.py` + `extract_cu5b.py`) → **500 CR** de consultation (2020–2026)
- [ ] Clarifier les **règles d'annotation** et finaliser les **templates INCEpTION** : classes de réponse (4 classes + ND/NA) et gestion des cas ambigus
- [ ] Annoter les CR avec **INCEpTION** (JSON UIMA CAS) puis livrer au Health Data Hub

---

## Prérequis

- Python 3.10+
- Accès au serveur Easily (`srvapp600`) via le réseau Foch
- Driver ODBC SQL Server installé (`SQL Server Native Client` ou `ODBC Driver 17/18 for SQL Server`)
- Java (pour la conversion PDF → TXT) — chemin à configurer dans `.env`
- Accès au partage réseau `S:\Envoi-EDS-PMSI` (fichiers RSS PMSI) pour CU2 et CU5a

> **CU5a / CU5b — pas d'OCR** : seuls les documents à **couche texte native** sont retenus ; les
> documents à océriser (scans) sont **écartés** faute de méthode d'OCR fiable. Aucun Tesseract requis.

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Renseigner le mot de passe dans `.env` :

```
EASILY_DB_PASSWORD=<mot_de_passe_SITE_READER_BO>
JAVA_PATH=<chemin_vers_java.exe>          # optionnel, valeur par défaut dans config.py
PDF_JAR_PATH=<chemin_vers_le_jar>         # optionnel, valeur par défaut dans config.py
```

---

## Cas d'usage

### CU1 — Pseudonymisation des CR médicaux

**Objectif** : constituer un jeu de données de CR médicaux pour évaluer le modèle de pseudonymisation.

| Paramètre | Valeur |
|-----------|--------|
| Volume cible | 400 CR (min 100, max 1000) |
| Critère temporel | CR datant de 2015 ou après |
| Types de CR | Tous CR médicaux (hors admin, arrêts de travail, transports) |
| Format de sortie | `.txt` — 1 fichier par CR |
| Métadonnées | `metadata_cu1.csv` — strate + fréquence dans la population |
| IPP | `ipp_cu1.csv` — usage interne uniquement |
| Annotation | Manuelle avec INCEpTION (format JSON UIMA CAS) — après extraction |

**Strate** : `{année}_{sexe}_{tranche_age}` — ex. `2019_Homme_50-54ans`

**Lancer l'extraction (2 étapes) :**

```bash
# Étape 1 — à faire une seule fois : récupère les métadonnées de ~20 000 documents
python WP1_CU1/fetch_pool.py

# Étape 2 — extrait les 400 CR finaux (peut être relancé sans retoucher la DB)
python WP1_CU1/extract_cu1.py
```

**Sorties :**
```
WP1_CU1/output/
├── txt/               # Livrable : fichiers .txt (1 par CR)
│   ├── a3f2b1c4d5e6.txt
│   └── ...
├── raw_pdf/           # PDF sources conservés (traçabilité)
├── metadata_cu1.csv   # Métadonnées avec strates
└── ipp_cu1.csv        # IPP patients — usage interne (non livré à PARTAGES)
```

> `extract_cu1.py` produit les `.txt` **et** les PDF. Pour (re)générer les `.txt` depuis des PDF déjà
> extraits : `python WP1_CU1/convert_to_txt.py`.

**Structure de `metadata_cu1.csv` :**

| Colonne | Description |
|---------|-------------|
| `file_id` | Identifiant anonyme du fichier (hash SHA-256 tronqué du doc_id) |
| `filename` | Nom du fichier `.txt` |
| `strate` | Ex. `2019_Homme_50-54ans` |
| `frequence_strate_population` | Fréquence de la strate dans la population globale Foch |
| `doc_date` | Date du CR |
| `departement_code` | Code UF/département source |
| `doc_extension` | Extension source (`pdf`, etc.) |
| `export_success` | `True` si le fichier a été généré avec succès |

📄 **Méthodologie détaillée** (sélection par exclusion, stratification proportionnelle, validation couche texte) : [docs/methodologie_extraction_CU1.md](docs/methodologie_extraction_CU1.md)

---

### CU2 — Codage CIM-10 depuis CRH

**Objectif** : constituer un jeu de données de CRH/CRO avec les codes CIM-10 et CCAM correspondants pour évaluer un modèle de codage automatique.

| Paramètre | Valeur |
|-----------|--------|
| Volume cible | 1 000 séjours (tirage aléatoire) |
| Critère temporel | 2023, 2024, 2025 |
| Filtre | Séjours ambulatoires (durée = 0 jour) |
| Filtre GHM | Liste blanche à configurer (`ghm_whitelist` dans `config.py`) |
| Source RSS | `S:\Envoi-EDS-PMSI` |
| Source documents | METADONE — CRH + CRO |
| Format de sortie | `cu2_dataset.csv` (séparateur `;`) — 5 colonnes |

**Colonnes du dataset livré :**

| Colonne | Description |
|---------|-------------|
| `ID` | Identifiant anonymisé du séjour (hash SHA-256, 16 hex chars) |
| `Spécialité` | Spécialité médicale déduite du préfixe GHM |
| `Texte` | Texte extrait du/des CRH + CRO (séparés par `---`) |
| `Codes CCAM` | Codes CCAM du RSS, séparés par des espaces |
| `CIM-10 DP` | Diagnostic principal du RSS |

**Lancer l'extraction (2 étapes) :**

```bash
# Étape 1 — à faire une seule fois : parse les RSS et filtre les séjours éligibles
python WP2_CU2/fetch_rss.py

# Étape 2 — extraction itérative (reprise automatique si interruption)
python WP2_CU2/extract_cu2.py
```

**Sorties :**
```
WP2_CU2/output/
├── pool_rss.csv                       # Pool de séjours éligibles (fetch_rss)
├── cu2_dataset.csv                    # Dataset livré à PARTAGES
├── cu2_stats.csv                      # Statistiques par spécialité
└── cu2_correspondance_INTERNE.csv     # ID ↔ numero_admin réel — usage interne uniquement
```

> ⚠️ Ne jamais livrer `cu2_correspondance_INTERNE.csv` ni `ipp_cu1.csv` au Health Data Hub.

📄 **Méthodologie détaillée** (sélection des séjours ambulatoires, appariement PMSI ↔ CR, conformité au guide) : [docs/methodologie_extraction_CU2.md](docs/methodologie_extraction_CU2.md)

---

### CU5a — Identification automatique des biomarqueurs en oncologie

**Objectif** : constituer un jeu de CR d'anatomopathologie + génomique tumorale (IHC, FISH, NGS) pour évaluer un modèle d'extraction/normalisation des biomarqueurs.

| Paramètre | Valeur |
|-----------|--------|
| Volume cible | **150 CR** (fixe : min = idéal = max) |
| Critère temporel | CR datant de 2010 ou après |
| Sources (Easily) | `doc_type_code = 5` (CR anapath) + `= 127` (Génétique) |
| Texte | **couche native uniquement** (pdfplumber) ; documents à océriser (scans) **écartés** — pas d'OCR fiable |
| Équilibrage | par type de cancer — localisation déduite des codes CIM-10 `C` via les **RSS PMSI** |
| Format de sortie | `.txt` — 1 fichier par CR |
| Métadonnées | `metadata_cu5a.csv` (type, localisation) — obligatoire : N/A |
| Annotation | Manuelle avec INCEpTION (templates CU5a fournis) — après extraction |

```bash
# Étape 1 — pool de candidats (anapath + génétique)
python WP5_CU5a/fetch_pool.py
# Étape 2 — localisation (RSS) + échantillon équilibré 150 + extraction texte natif
python WP5_CU5a/extract_cu5a.py
```

**Sorties :**
```
WP5_CU5a/output/
├── txt/                  # 150 fichiers .txt (couche texte native)
├── metadata_cu5a.csv     # file_id, type, localisation, fréquence, date
└── ipp_cu5a.csv          # IPP patients — usage interne (non livré)
```

> Si le lecteur `S:\` (RSS) est indisponible, l'extraction se poursuit sans stratification (localisation = `Inconnue`).
> Les documents sans couche texte native (scans à océriser, ex. génétique) sont **écartés** faute d'OCR fiable.

---

### CU5b — Analyse de la réponse aux traitements en oncologie

**Objectif** : constituer un jeu de CR de consultation d'oncologie pour évaluer un modèle de classification de la réponse au traitement (4 classes + ND/NA).

| Paramètre | Valeur |
|-----------|--------|
| Volume cible | **500 CR** (min 100, max 1000) |
| Critère temporel | CR datant de 2010 ou après |
| Source (Easily) | `doc_type_code = 7` (CR consultation) + service d'oncologie |
| Filtre oncologie | doc → VENUE → SEJOUR avec `sej_uf_medicale_code ∈ {324A, 324E, 324B}` (configurable) |
| Texte | **couche native uniquement** (pdfplumber) ; documents à océriser (scans) **écartés** — pas d'OCR fiable |
| Format de sortie | `.txt` — 1 fichier par CR |
| Métadonnées | `metadata_cu5b.csv` (service, date) — obligatoire : N/A |
| Annotation | Manuelle avec INCEpTION (templates CU5b fournis) — après extraction |

```bash
# Étape 1 — pool de consultations d'oncologie
python WP5_CU5b/fetch_pool.py
# Étape 2 — tirage aléatoire 500 + extraction texte
python WP5_CU5b/extract_cu5b.py
```

**Sorties :**
```
WP5_CU5b/output/
├── txt/                  # ~500 fichiers .txt (couche texte native)
├── metadata_cu5b.csv     # file_id, service, date
└── ipp_cu5b.csv          # IPP patients — usage interne (non livré)
```

> ⚠️ Ne jamais livrer `ipp_cu5a.csv` ni `ipp_cu5b.csv` au Health Data Hub.

📄 **Méthodologie détaillée** (choix de sélection, stratification par localisation, exclusion des documents à océriser, anonymisation) : [docs/methodologie_extraction_CU5.md](docs/methodologie_extraction_CU5.md)

---

## Structure du projet

```
PARTAGES-Foch/
├── .env                         # Variables d'environnement (non versionné)
├── requirements.txt
├── README.md
├── docs/
│   ├── methodologie_extraction_CU1.md  # Méthodologie CU1 (exclusion, strat. proportionnelle)
│   ├── methodologie_extraction_CU2.md  # Méthodologie CU2 (séjours ambu, appariement PMSI↔CR)
│   └── methodologie_extraction_CU5.md  # Méthodologie CU5a/CU5b (sélection, strat., exclusion docs à océriser)
├── utils/
│   ├── pdf_converter.py         # Conversion PDF → TXT (pdfplumber / jar Java)
│   └── rss_parser.py            # Parser RSS PMSI format groupé 120 (ATIH 2020)
├── WP1_CU1/
│   ├── config.py                # Paramètres CU1 + connexion DB
│   ├── fetch_pool.py            # Étape 1 : SQL → pool_metadata.csv
│   ├── extract_cu1.py           # Étape 2 : extraction des 400 CR
│   └── output/                  # Généré à l'exécution (non versionné)
├── WP2_CU2/
│   ├── config.py                # Paramètres CU2 + connexion DB
│   ├── fetch_rss.py             # Étape 1 : RSS → pool_rss.csv
│   ├── extract_cu2.py           # Étape 2 : extraction itérative du dataset
│   └── output/                  # Généré à l'exécution (non versionné)
├── WP5_CU5a/
│   ├── config.py                # Paramètres CU5a (types 5/127, RSS)
│   ├── fetch_pool.py            # Étape 1 : SQL → pool_metadata.csv
│   ├── extract_cu5a.py          # Étape 2 : localisation RSS + 150 CR équilibrés (texte natif)
│   └── output/                  # Généré à l'exécution (non versionné)
└── WP5_CU5b/
    ├── config.py                # Paramètres CU5b (type 7, UF oncologie)
    ├── fetch_pool.py            # Étape 1 : SQL (filtre UF onco) → pool_metadata.csv
    ├── extract_cu5b.py          # Étape 2 : tirage 500 CR + extraction texte
    └── output/                  # Généré à l'exécution (non versionné)
```

---

## Calendrier PARTAGES (guide v29.01.26)

| Étape | Échéance |
|-------|----------|
| Infrastructure GPU | Mai 2026 |
| Cadre réglementaire | Juin 2026 |
| Extraction + annotation | Fin septembre 2026 |
