# Méthodologie d'extraction — CU1

> Projet PARTAGES (Health Data Hub) — Hôpital Foch
> Guide de référence : *Guide de préparation des données par CU* v29.01.26 (section 4).

Ce document explique **comment** le jeu de données CU1 a été constitué : la source, les choix de
sélection, la **stratification** (représentativité), la validation de la couche texte, et l'anonymisation.

---

## 1. Objectif

**CU1 — Pseudonymisation des CR médicaux.** Constituer un échantillon de comptes rendus médicaux,
représentatif de l'activité de l'établissement, pour évaluer un modèle d'**extraction des entités
identifiantes** (noms, dates, adresses…) en vue de la pseudonymisation.

| Paramètre | Valeur |
|---|---|
| Volume cible | **400** (min 100, max 1000) |
| Profondeur | CR datés **≥ 2015** (moins de 10 ans) |
| Types de CR | **Tous** les CR médicaux, hors documents non cliniques |
| Représentativité | Échantillon **stratifié proportionnel** (année × sexe × tranche d'âge) |
| Livrable | CR + métadonnées ; annotation manuelle ensuite (INCEpTION, JSON UIMA CAS) |

Métadonnée **obligatoire** (guide) : la **strate** de chaque document et, si possible, la **fréquence
de cette strate** dans la population globale des documents de l'établissement.

---

## 2. Source de données — EDS Easily (SQL Server)

Connexion `pyodbc` au serveur `srvapp600`, utilisateur `SITE_READER_BO` (lecture seule).

| Table | Usage |
|---|---|
| `METADONE.metadone.DOCUMENTS` | Métadonnées des documents (`doc_nom`, dates, `doc_app_id`, `doc_pat_id`…) |
| `NOYAU.patient.PATIENT` | Patients (`pat_ipp`, `pat_sexe`, `pat_date_naissance`) |
| `STOCKAGE.stockage.FILES` | Contenu binaire (`fil_data` = PDF) |

---

## 3. Sélection des documents

### 3.1 Choix clé : inclure *tous* les CR médicaux, par **exclusion**

Contrairement au CU5 (qui cible des types précis via `doc_type_code`), le CU1 vise la
**représentativité de l'ensemble des CR médicaux**. La sélection procède donc par **exclusion** des
documents non cliniques, via des motifs sur `doc_nom` (`doc_exclusion_patterns` dans
`WP1_CU1/config.py`) :

> arrêt de travail · transport · protocole de soin · ordonnance · prescription · consentement ·
> facture · administratif

### 3.2 Filtres de la requête (`fetch_pool.py`)

```
date(CR) ∈ [2015-01-01 ; 2025-12-31]          -- doc_realisation_date sinon doc_creation_date
ET doc_supprime ≠ 'true'
ET pat_ipp non nul
ET TRY_CAST(doc_app_id AS INT) > 0            -- applications source valides
ET NOT ( doc_nom LIKE l'un des motifs d'exclusion )
ET fil_data non nul                            -- un binaire PDF doit exister
ORDER BY NEWID()                               -- tirage aléatoire côté SQL
```

La date du CR est calculée ainsi : `doc_realisation_date` si présente **et** ≥ 2003, sinon
`doc_creation_date` (repli pour les documents anciens mal datés).

On pré-tire un **pool aléatoire** de `sql_pool_size = 20 000` documents côté SQL (le `ORDER BY NEWID()`),
afin de stratifier ensuite côté Python sans charger toute la base.

---

## 4. Stratification (représentativité de l'activité)

### 4.1 Définition de la strate

Chaque document reçoit une strate **`{année}_{sexe}_{tranche_âge}`** (ex. `2019_Homme_50-54ans`),
calculée par `compute_strate()` :

- **année** : année de la date du CR.
- **sexe** : `pat_sexe` normalisé — `1/M/H/MASCULIN → Homme`, `2/F/FEMININ → Femme`, sinon `Inconnu`.
- **tranche d'âge** : âge à la date du CR = `(date_CR − date_naissance)`, découpé selon
  `age_bins`/`age_labels` :

  `0-17 · 18-29 · 30-39 · 40-49 · 50-54 · 55-59 · 60-64 · 65-69 · 70-79 · 80+`

### 4.2 Échantillonnage **proportionnel** (≠ équilibré)

C'est la différence majeure avec le CU5a. `stratified_sample()` **conserve les proportions** des
strates observées dans le pool :

```
allocation(strate) = round( fréquence(strate) × cible )
```

L'écart d'arrondi est réaffecté à la strate la plus représentée, puis on tire aléatoirement le
nombre alloué dans chaque strate. L'échantillon **reflète donc l'activité réelle** (une strate
fréquente reste fréquente), conformément à l'attendu « représentativité » du guide CU1.

> Différence avec CU5a : CU1 = **proportionnel** (représentatif) ; CU5a = **équilibré** (égalise les
> localisations pour éviter la surreprésentation d'un type de cancer).

### 4.3 Métadonnée `frequence_strate_population`

Pour chaque document livré, on enregistre la **fréquence de sa strate dans le pool global**
(`value_counts(normalize=True)`), qui sert de proxy de la fréquence dans la population des documents
de l'établissement — c'est la métadonnée obligatoire du guide.

---

## 5. Validation de la couche texte (pas d'OCR)

Le CU1 ne conserve que des CR **réellement textuels**. Pour chaque candidat (`_check_one`) :

1. en-tête `%PDF` présent ;
2. taille ≥ **2048 octets** ;
3. **couche texte** ≥ **100 caractères** extraits par `pdfplumber` (`_has_text_layer`).

Les **scans sans couche texte sont rejetés** (`no_text_layer`) — le CU1 **n'applique pas d'OCR**
(contrairement au CU5a). Pour compenser les rejets, on tire un **sur-échantillon**
(`oversample_factor = 3.0`) de candidats, on valide en parallèle (`ThreadPoolExecutor`), puis on
retient exactement `target_count` documents valides.

---

## 6. Architecture en 2 étapes

1. **`fetch_pool.py`** — une requête SQL → `output/pool_metadata.csv` (pool aléatoire de 20 000 docs).
   À ne relancer que pour rafraîchir le pool.
2. **`extract_cu1.py`** — lit le pool, calcule les strates, sur-échantillonne, télécharge les binaires
   par lots, valide la couche texte, sauvegarde la sélection finale.

```bash
python WP1_CU1/fetch_pool.py
python WP1_CU1/extract_cu1.py
```

---

## 7. Sorties & anonymisation

```
WP1_CU1/output/
├── raw_pdf/  {file_id}.pdf      # CR validés (couche texte garantie)
├── metadata_cu1.csv            # file_id, filename, strate, frequence_strate_population, doc_date, departement_code, pdf_size_kb
└── ipp_cu1.csv                 # IPP patients — usage INTERNE, NE PAS livrer
```

- **`file_id`** = `SHA-256(doc_id)` tronqué à 12 caractères → identifiant anonyme et stable.
- **`ipp_cu1.csv`** : à **ne jamais livrer** au Health Data Hub.
- `output/` et `*.pdf` sont exclus du dépôt (`.gitignore`) : aucune donnée patient versionnée.

> **Étape aval — conversion `.txt`** : le format attendu pour l'annotation est `.txt` (1 fichier/CR).
> La validation de la couche texte garantit que les PDF exportés sont convertibles ; la conversion
> elle-même (puis la pré-annotation *pseudoFoch* et l'annotation INCEpTION) constitue l'étape suivante.

---

## 8. Paramètres clés (`WP1_CU1/config.py`)

| Paramètre | Valeur | Rôle |
|---|---|---|
| `target_count` / `min` / `max` | 400 / 100 / 1000 | Volume de l'échantillon |
| `date_min` / `date_max` | 2015-01-01 / 2025-12-31 | Fenêtre temporelle |
| `doc_exclusion_patterns` | (voir §3.1) | Documents non cliniques exclus |
| `age_bins` / `age_labels` | 10 tranches | Découpage d'âge des strates |
| `sql_pool_size` | 20 000 | Taille du pool aléatoire SQL |
| `oversample_factor` | 3.0 | Marge pour absorber les rejets |
| `max_workers` | 6 | Parallélisme de validation |
| `col_sexe` / `col_date_naissance` | `pat_sexe` / `pat_date_naissance` | Colonnes patient |

---

## 9. CU1 vs CU5 — différences de conception

| | **CU1** | **CU5a** | **CU5b** |
|---|---|---|---|
| Cible documentaire | tous CR médicaux (par exclusion) | anapath + génétique (`doc_type_code` 5/127) | consultations onco (`doc_type_code` 7 + UF) |
| Échantillonnage | **proportionnel** (représentatif) | **équilibré** par localisation | aléatoire |
| Stratification | année × sexe × âge | type de cancer (CIM-10 via RSS) | — |
| Scans / OCR | rejetés (pas d'OCR) | **OCR** (Tesseract) si scan | OCR de secours |
| Sortie | PDF validés | `.txt` (+ `_ocr`) | `.txt` (+ `_ocr`) |

---

## 10. Limites connues

- **Rejet des scans** : les CR sans couche texte sont écartés (pas d'OCR au CU1). L'échantillon est
  donc constitué de CR nativement textuels.
- **Exclusions par nom** : le filtrage des documents non cliniques repose sur `doc_nom` (saisie libre) ;
  des cas limites peuvent subsister.
- **Datation** : `doc_realisation_date` privilégiée, repli sur `doc_creation_date`.

---

## 11. Reproductibilité

Les tirages aléatoires utilisent `random_state = 42` ; à pool et paramètres constants, l'extraction
est reproductible. Pré-requis : accès Easily depuis le réseau Foch.
