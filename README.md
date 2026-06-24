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
| **CU5a** | Identification automatique des biomarqueurs en oncologie | 🟡 Pipeline prêt |
| **CU5b** | Analyse de la réponse aux traitements en oncologie | 🟡 Pipeline prêt |

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

### CU5a — Biomarqueurs en oncologie *(pipeline prêt)*

- [x] **Tesseract** v5.5 (+ langue `fra`) installé et `TESSERACT_CMD` renseigné dans `.env` — OCR des scans de génétique validé sur la base
- [ ] Vérifier l'accès au lecteur réseau `S:\Envoi-EDS-PMSI` (RSS, pour la localisation tumorale)
- [ ] Lancer `python WP5_CU5a/fetch_pool.py` puis `python WP5_CU5a/extract_cu5a.py`
- [ ] Contrôler l'équilibrage par localisation dans `metadata_cu5a.csv` (ajuster `rss_years` si peu de matchs)
- [ ] Annoter les 150 CR avec **INCEpTION** (templates CU5a fournis) puis livrer

### CU5b — Réponse aux traitements en oncologie *(pipeline prêt)*

- [ ] Confirmer le périmètre des UF d'oncologie (`oncology_uf_codes` dans `WP5_CU5b/config.py` — par défaut 324A/324E/324B)
- [ ] Lancer `python WP5_CU5b/fetch_pool.py` puis `python WP5_CU5b/extract_cu5b.py`
- [ ] Annoter les CR avec **INCEpTION** (templates CU5b fournis) puis livrer

---

## Prérequis

- Python 3.10+
- Accès au serveur Easily (`srvapp600`) via le réseau Foch
- Driver ODBC SQL Server installé (`SQL Server Native Client` ou `ODBC Driver 17/18 for SQL Server`)
- Java (pour la conversion PDF → TXT) — chemin à configurer dans `.env`
- Accès au partage réseau `S:\Envoi-EDS-PMSI` (fichiers RSS PMSI) pour CU2 et CU5a
- *(CU5a, optionnel)* **Tesseract OCR** + données de langue `fra` pour océriser les scans de génétique
  ([installeur Windows](https://github.com/UB-Mannheim/tesseract/wiki)) ; si `tesseract.exe` n'est pas
  dans le `PATH`, renseigner `TESSERACT_CMD` dans `.env`

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
TESSERACT_CMD=<chemin_vers_tesseract.exe> # optionnel (CU5a OCR), si pas dans le PATH
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
| Texte | anapath = couche native (pdfplumber) ; génétique = **scans → OCR** (Tesseract), suffixe `_ocr` |
| Équilibrage | par type de cancer — localisation déduite des codes CIM-10 `C` via les **RSS PMSI** |
| Format de sortie | `.txt` — 1 fichier par CR |
| Métadonnées | `metadata_cu5a.csv` (type, localisation, OCR) — obligatoire : N/A |
| Annotation | Manuelle avec INCEpTION (templates CU5a fournis) — après extraction |

```bash
# Étape 1 — pool de candidats (anapath + génétique)
python WP5_CU5a/fetch_pool.py
# Étape 2 — localisation (RSS) + échantillon équilibré 150 + extraction texte/OCR
python WP5_CU5a/extract_cu5a.py
```

**Sorties :**
```
WP5_CU5a/output/
├── txt/                  # 150 fichiers .txt (suffixe _ocr si océrisé)
├── metadata_cu5a.csv     # file_id, type, localisation, fréquence, ocr, date
└── ipp_cu5a.csv          # IPP patients — usage interne (non livré)
```

> Si le lecteur `S:\` (RSS) est indisponible, l'extraction se poursuit sans stratification (localisation = `Inconnue`).
> Sans Tesseract installé, les scans de génétique sans couche texte sont ignorés (le reste fonctionne).

---

### CU5b — Analyse de la réponse aux traitements en oncologie

**Objectif** : constituer un jeu de CR de consultation d'oncologie pour évaluer un modèle de classification de la réponse au traitement (4 classes + ND/NA).

| Paramètre | Valeur |
|-----------|--------|
| Volume cible | **500 CR** (min 100, max 1000) |
| Critère temporel | CR datant de 2010 ou après |
| Source (Easily) | `doc_type_code = 7` (CR consultation) + service d'oncologie |
| Filtre oncologie | doc → VENUE → SEJOUR avec `sej_uf_medicale_code ∈ {324A, 324E, 324B}` (configurable) |
| Texte | couche native (pdfplumber) ; OCR de secours si scan |
| Format de sortie | `.txt` — 1 fichier par CR |
| Métadonnées | `metadata_cu5b.csv` (service, date, ocr) — obligatoire : N/A |
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
├── txt/                  # ~500 fichiers .txt
├── metadata_cu5b.csv     # file_id, service, date, ocr
└── ipp_cu5b.csv          # IPP patients — usage interne (non livré)
```

> ⚠️ Ne jamais livrer `ipp_cu5a.csv` ni `ipp_cu5b.csv` au Health Data Hub.

📄 **Méthodologie détaillée** (choix de sélection, stratification par localisation, OCR, anonymisation) : [docs/methodologie_extraction_CU5.md](docs/methodologie_extraction_CU5.md)

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
│   └── methodologie_extraction_CU5.md  # Méthodologie CU5a/CU5b (sélection, strat., OCR)
├── utils/
│   ├── pdf_converter.py         # Conversion PDF → TXT (pdfplumber / jar Java)
│   ├── ocr.py                   # OCR des scans (PyMuPDF + Tesseract) — CU5a
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
│   ├── config.py                # Paramètres CU5a (types 5/127, RSS, OCR)
│   ├── fetch_pool.py            # Étape 1 : SQL → pool_metadata.csv
│   ├── extract_cu5a.py          # Étape 2 : localisation RSS + 150 CR équilibrés + OCR
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
