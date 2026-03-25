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
| **CU5a** | Structuration de données cliniques | 🔴 Non démarré |
| **CU5b** | Structuration de données cliniques (variante) | 🔴 Non démarré |

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

### CU5a / CU5b — Structuration de données cliniques *(à démarrer)*

- [ ] Lire le guide PARTAGES v29.01.26 — sections CU5a et CU5b
- [ ] Identifier les sources de données (biologie, imagerie, NLP ?)
- [ ] Créer `WP5_CU5a/` et `WP5_CU5b/`

---

## Prérequis

- Python 3.10+
- Accès au serveur Easily (`srvapp600`) via le réseau Foch
- Driver ODBC SQL Server installé (`SQL Server Native Client` ou `ODBC Driver 17/18 for SQL Server`)
- Java (pour la conversion PDF → TXT) — chemin à configurer dans `.env`
- Accès au partage réseau `S:\Envoi-EDS-PMSI` (fichiers RSS PMSI) pour CU2

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
├── txt/               # Fichiers .txt (1 par CR)
│   ├── a3f2b1c4d5e6.txt
│   └── ...
├── metadata_cu1.csv   # Métadonnées avec strates
└── ipp_cu1.csv        # IPP patients — usage interne (non livré à PARTAGES)
```

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

---

## Structure du projet

```
PARTAGES-Foch/
├── .env                         # Variables d'environnement (non versionné)
├── requirements.txt
├── README.md
├── utils/
│   ├── pdf_converter.py         # Conversion PDF → TXT via jar Java
│   └── rss_parser.py            # Parser RSS PMSI format groupé 120 (ATIH 2020)
├── WP1_CU1/
│   ├── config.py                # Paramètres CU1 + connexion DB
│   ├── fetch_pool.py            # Étape 1 : SQL → pool_metadata.csv
│   ├── extract_cu1.py           # Étape 2 : extraction des 400 CR
│   └── output/                  # Généré à l'exécution (non versionné)
└── WP2_CU2/
    ├── config.py                # Paramètres CU2 + connexion DB
    ├── fetch_rss.py             # Étape 1 : RSS → pool_rss.csv
    ├── extract_cu2.py           # Étape 2 : extraction itérative du dataset
    └── output/                  # Généré à l'exécution (non versionné)
```

---

## Calendrier PARTAGES (guide v29.01.26)

| Étape | Échéance |
|-------|----------|
| Infrastructure GPU | Mai 2026 |
| Cadre réglementaire | Juin 2026 |
| Extraction + annotation | Fin septembre 2026 |
