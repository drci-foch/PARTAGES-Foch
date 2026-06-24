# Méthodologie d'extraction — CU5a & CU5b

> Projet PARTAGES (Health Data Hub) — Hôpital Foch
> Guide de référence : *Guide de préparation des données par CU* v29.01.26 (sections 7 et 8).

Ce document explique **comment** les jeux de données CU5a et CU5b ont été constitués : les
sources, les choix de sélection, la stratification par type de cancer, l'OCR, et l'anonymisation.

---

## 1. Objectifs

| | CU5a | CU5b |
|---|---|---|
| Intitulé | Identification automatique des **biomarqueurs** en oncologie | Analyse de la **réponse aux traitements** en oncologie |
| Documents | CR d'**anatomopathologie** + **génomique tumorale** (IHC, FISH, NGS) | CR de **consultation** du service d'**oncologie** |
| Volume | **150** (fixe : min = idéal = max) | **500** (min 100, max 1000) |
| Profondeur | CR datés **≥ 2010** | CR datés **≥ 2010** |
| Livrable | `.txt` (1 fichier / CR) + métadonnées | `.txt` (1 fichier / CR) + métadonnées |
| Suite | Annotation manuelle INCEpTION (format JSON UIMA CAS) | idem |

Les métadonnées « obligatoires » sont **N/A** pour ces deux CU ; la localisation du cancer et la
répartition OCR sont *facultatives* mais fournies ici car elles servent aussi à équilibrer l'échantillon.

---

## 2. Source de données — EDS Easily (SQL Server)

Connexion `pyodbc` au serveur `srvapp600` (base `master`), utilisateur `SITE_READER_BO` (lecture seule).
Tables principales utilisées :

| Table | Usage |
|---|---|
| `METADONE.metadone.DOCUMENTS` | Métadonnées des documents (`doc_type_code`, `doc_venue_id`, dates, `doc_pat_id`…) |
| `STOCKAGE.stockage.FILES` | Contenu binaire (`fil_data` = PDF, `fil_data_fs` = texte natif) |
| `NOYAU.patient.PATIENT` | Patients (`pat_id`, `pat_ipp`) |
| `NOYAU.patient.VENUE` | Venues (`ven_id`, `ven_numero`) — pivot vers le PMSI |
| `NOYAU.patient.SEJOUR` | Séjours (`sej_uf_medicale_code` = UF médicale) |
| `NOYAU.coeur.UF` | Référentiel des unités fonctionnelles (libellés des services) |
| `NOYAU_REFERENTIEL.noyau.TYPE_DOCUMENT` | Référentiel des types de documents (`tdoc_code` → libellé) |

---

## 3. Sélection des documents

### 3.1 Choix clé : filtrer par `doc_type_code`, pas par le nom du document

Le nom de document (`doc_nom`) est saisi librement (variantes, fautes, abréviations) et un filtre
`LIKE '%anapath%'` impose un **balayage complet** de la table `DOCUMENTS` (plusieurs millions de
lignes) — ce qui a provoqué des *timeouts* lors de l'exploration.

À la place, on s'appuie sur **`DOCUMENTS.doc_type_code`** (entier), relié au référentiel
`TYPE_DOCUMENT`. C'est fiable, indexable et stable. Mapping retenu :

| `doc_type_code` | Libellé | Utilisé par |
|---|---|---|
| `5` | Compte-rendu anapath | CU5a |
| `127` | Génétique | CU5a |
| `7` | Compte-rendu consultation | CU5b |

Volumes disponibles (≥ 2010, constatés lors de l'exploration) : anapath ≈ **138 000**,
génétique ≈ **2 500**, consultations ≈ **1,4 M** → largement suffisant pour les cibles.

### 3.2 CU5a — anatomopathologie + génomique

```
doc_type_code ∈ (5, 127)
ET date ≥ 2010-01-01
ET doc_supprime ≠ 'true'
ET pat_ipp non nul
ET (fil_data OU fil_data_fs présent)
```

- **Anapath (5)** : réalisée en interne à Foch → PDF avec **couche texte native**.
- **Génétique (127)** : rapports de séquençage, en partie **scannés** (origine Institut Curie) →
  certains sans couche texte → **OCR nécessaire** (voir §5).

### 3.3 CU5b — consultations d'oncologie

Le défi : ne garder que le **service d'oncologie**. Deux pistes ont été examinées :

- ❌ `DOCUMENTS.doc_cr_code` : c'est le **Centre de Responsabilité** (codes 900, 550, 591…), pas
  l'unité médicale. Le référentiel `CONSTANTE_CR` est vide et ces codes ne correspondent pas aux UF.
- ✅ **Chemin par le séjour** : `document → VENUE (doc_venue_id) → SEJOUR (ven_id) →
  sej_uf_medicale_code`. Ce champ porte bien les codes d'UF oncologie.

Requête (via `EXISTS` pour ne pas dupliquer un document rattaché à plusieurs séjours) :

```
doc_type_code = 7
ET date ≥ 2010-01-01
ET EXISTS (VENUE v JOIN SEJOUR s : v.ven_id = doc_venue_id
           ET s.sej_uf_medicale_code ∈ ('324A','324E','324B'))
```

UF d'oncologie repérées dans `NOYAU.coeur.UF` : `324A`/`324E` (ONCOLOGIE), `324B` (ONCOLOGIE HDJ),
`325B` (prévention cancer), `328A/B/E` (soins de support), `547A` (soins palliatifs onco). Le
périmètre **retenu par défaut = oncologie clinique `324A`, `324E`, `324B`** (paramétrable via
`oncology_uf_codes` dans `WP5_CU5b/config.py`).

---

## 4. Stratification CU5a par type de cancer (localisation tumorale)

Le guide demande un échantillon **équilibré par type de cancer** pour éviter la surreprésentation
d'une localisation.

### 4.1 Problème : pas de CIM-10 dans Easily

Les tables `NOYAU.patient.DIAGNOSTIC`, `DIAGNOSTIC_NEW` et `DIAGNOSTIC_HISTO` sont **vides** côté
`SITE_READER_BO`. La localisation tumorale doit donc venir d'ailleurs : les **fichiers RSS PMSI**.

### 4.2 Source CIM-10 : RSS PMSI (lecteur `S:\Envoi-EDS-PMSI`)

`utils/rss_parser.py` parse le format **RSS groupé 120** (ATIH 2020). Pour chaque séjour, on récupère
le diagnostic principal (DP), relié (DR) et associés (DA) — tous des codes CIM-10 — avec pour clé le
**numéro administratif de séjour** (`numero_admin`).

> Liaison RSS ↔ Easily : `RSS.numero_admin = VENUE.ven_numero`.

### 4.3 Des codes CIM-10 vers une localisation

On ne conserve que les codes commençant par **`C`** (tumeurs malignes, CIM-10 `C00`–`C97`), puis on
les regroupe en **localisations** via `cim_localisation_map` (`WP5_CU5a/config.py`) :

| Tranche | Localisation |
|---|---|
| C00–C14 | Lèvre, cavité buccale, pharynx |
| C15–C26 | Appareil digestif |
| C30–C39 | Appareil respiratoire et thorax |
| C40–C41 | Os et cartilage |
| C43–C44 | Peau |
| C45–C49 | Tissus mésothéliaux et mous |
| C50 | Sein |
| C51–C58 | Organes génitaux féminins |
| C60–C63 | Organes génitaux masculins |
| C64–C68 | Voies urinaires |
| C69–C72 | Œil, encéphale, SNC |
| C73–C75 | Thyroïde et glandes endocrines |
| C76–C80 | Sièges mal définis / secondaires |
| C81–C96 | Tissu lymphoïde et hématopoïétique |
| autre `C` | Autre cancer (C divers) |

### 4.4 Profil cancéreux par patient

Pour chaque patient du pool : `pat_id → toutes ses venues (ven_numero) → séjours RSS correspondants
→ ensemble de ses codes C → localisation dominante` (vote majoritaire). Chaque document hérite de la
localisation de son patient ; à défaut de tout code C, la localisation est **`Inconnue`**.

### 4.5 Échantillonnage équilibré (« water-filling »)

`balanced_allocation()` répartit les 150 documents le plus **équitablement possible** entre les
localisations présentes : on distribue par parts égales, plafonné par la disponibilité de chaque
groupe, et on redistribue itérativement le reliquat aux groupes encore « ouverts ». Conséquences :

- une localisation rare n'est jamais sur-tirée au-delà de ce qui existe ;
- le groupe `Inconnue` est traité comme un groupe parmi d'autres (donc **plafonné**, il ne domine pas) ;
- on tire d'abord un **sur-échantillon** (`oversample_factor = 3.0`) pour absorber les documents
  illisibles / sans texte, puis on re-équilibre exactement à 150 parmi les valides.

> ⚠️ La couverture dépend des années de RSS parsées (`rss_years`, par défaut 2019–2025). Les CR
> anciens ou ambulatoires sans séjour PMSI codé cancer restent en `Inconnue` — à surveiller dans
> `metadata_cu5a.csv` et à ajuster en élargissant `rss_years` si besoin.

---

## 5. OCR — texte natif d'abord, océrisation en secours

### 5.1 Pourquoi
Les anapath de Foch ont une couche texte native, mais une partie des rapports de **génétique** sont
de **purs scans** (0 caractère extractible). Sans OCR, ces CR de séquençage — pourtant au cœur des
biomarqueurs du CU5a — seraient perdus.

### 5.2 Logique par document (`extract_cu5a.py`)
1. **Extraction native** : `fil_data_fs` (texte natif) si présent, sinon `pdfplumber` sur le PDF.
2. Si le texte obtenu fait **moins de 100 caractères** et que le contenu est un PDF →
   **bascule OCR**.
3. Si l'OCR produit ≥ 100 caractères → on retient ce texte et on marque le document `ocr = True`.

### 5.3 Comment l'OCR fonctionne (`utils/ocr.py`)
- **Rastérisation** des pages avec **PyMuPDF (fitz)** à **300 dpi** → image PNG.
- **Reconnaissance** avec **pytesseract** → moteur **Tesseract v5.5**, langue **`fra`** (repli sur la
  langue par défaut si `fra` indisponible).
- **Localisation du binaire** : variable `TESSERACT_CMD` (`.env`) sinon auto-détection des chemins
  d'installation usuels sous Windows.
- **Dégradation propre** : si pytesseract / Tesseract sont absents, `is_available()` renvoie `False`,
  l'OCR renvoie `None` et le pipeline continue (les scans concernés sont simplement ignorés).

### 5.4 Marquage `_ocr`
Conformément au guide, les fichiers océrisés sont nommés **`{file_id}_ocr.txt`** (et `ocr = True`
dans les métadonnées), afin de tracer la répartition OCR / non-OCR.

---

## 6. CU5b — extraction

Plus simple (pas de PMSI, texte natif) : **tirage aléatoire** (`random_state = 42`) de 500 documents
parmi le pool de consultations d'oncologie, extraction du texte natif (OCR de secours marginal),
sauvegarde. `oversample_factor = 2.0` pour compenser les rares documents illisibles.

---

## 7. Architecture en 2 étapes

1. **`fetch_pool.py`** — une seule requête SQL → `output/pool_metadata.csv`. À relancer uniquement si
   l'on veut rafraîchir le pool. Isole l'accès lourd à la base.
2. **`extract_cu5*.py`** — lit le pool, (CU5a) calcule la localisation via RSS et équilibre, télécharge
   les binaires par lots, extrait le texte (natif/OCR), écrit les sorties. Pas de re-balayage de la base.

```bash
python WP5_CU5a/fetch_pool.py
python WP5_CU5a/extract_cu5a.py
python WP5_CU5b/fetch_pool.py
python WP5_CU5b/extract_cu5b.py
```

---

## 8. Sorties & anonymisation

```
WP5_CU5a/output/                         WP5_CU5b/output/
├── txt/  {file_id}[_ocr].txt            ├── txt/  {file_id}[_ocr].txt
├── metadata_cu5a.csv                    ├── metadata_cu5b.csv
└── ipp_cu5a.csv   (INTERNE)             └── ipp_cu5b.csv   (INTERNE)
```

- **`file_id`** = `SHA-256(doc_id)` tronqué à 12 caractères → nom de fichier anonyme et stable.
- **`metadata_cu5a.csv`** : `file_id, filename, type, localisation, frequence_localisation_pool,
  doc_date, cr_code, ocr, text_chars, export_success`.
- **`metadata_cu5b.csv`** : `file_id, filename, service, doc_date, ocr, text_chars, export_success`.
- **`ipp_cu5*.csv`** : liste des IPP patients — **usage interne uniquement, à NE JAMAIS livrer** au
  Health Data Hub.
- Les dossiers `output/` et les `*.pdf` sont exclus du dépôt (`.gitignore`) : **aucune donnée patient
  n'est versionnée**.

---

## 9. Paramètres clés

| Paramètre | CU5a | CU5b | Fichier |
|---|---|---|---|
| Types de documents | `5, 127` | `7` | `config.py` |
| Période | ≥ 2010 | ≥ 2010 | `config.py` |
| Cible | 150 | 500 | `config.py` |
| Taille du pool SQL | 8 000 | 6 000 | `config.py` |
| Sur-échantillonnage | ×3.0 | ×2.0 | `config.py` |
| Seuil texte valide | 100 car. | 100 car. | `config.py` |
| UF oncologie | — | `324A,324E,324B` | `config.py` |
| Années RSS | 2019–2025 | — | `config.py` |
| OCR (langue / dpi) | `fra` / 300 | `fra` / 300 | `config.py` |
| Graine aléatoire | 42 | 42 | (extraction) |

---

## 10. Limites connues

- **Couverture RSS (CU5a)** : seuls les patients avec un séjour PMSI codé cancer obtiennent une
  localisation ; le reste est `Inconnue`. Élargir `rss_years` améliore la couverture au prix du temps
  de parsing.
- **Blobs corrompus** : quelques `fil_data` illisibles dans `FILES` (`Data-loss while decompressing`) ;
  ils sont ignorés et compensés par le sur-échantillonnage.
- **Dates** : on utilise `doc_realisation_date`, avec repli sur `doc_creation_date` si absente.
- **Qualité OCR** : dépend de la qualité du scan d'origine.

---

## 11. Reproductibilité

Toutes les sélections aléatoires utilisent `random_state = 42`. À pool et paramètres constants, les
extractions sont reproductibles. Pré-requis : accès Easily, lecteur `S:\` (CU5a), et Tesseract +
langue `fra` pour l'OCR (sinon les scans de génétique sont ignorés).
