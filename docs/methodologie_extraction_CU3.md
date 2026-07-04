# Méthodologie d'extraction — CU3

> Projet PARTAGES (Health Data Hub) — Hôpital Foch
> Guide de référence : *Guide de préparation des données par CU* v29.01.26 (section 6 + FAQ #3, #5, #10).

Ce document explique **comment** le jeu de données CU3 a été constitué : la source, les choix de
sélection, la **détection et le découpage de la conclusion**, la stratification, et l'anonymisation.

---

## 1. Objectif

**CU3 — Résumé automatique des CR médicaux.** Constituer un échantillon de comptes rendus
médicaux dont la **conclusion est bien définie et identifiée**, pour évaluer un modèle de
**génération automatique de conclusions** (masquage de la conclusion puis génération, métriques
de similarité textuelle et de rappel/précision des éléments clés).

| Paramètre | Valeur |
|---|---|
| Volume cible | **400** (min 100, max 1000) |
| Profondeur | CR datés **≥ 2020** (voir §3.3 — interprétation de la fenêtre temporelle) |
| Types de CR | **Tous** les CR médicaux, hors documents non cliniques (ordonnances exclues, guide §6.2) |
| Contenu | Texte pur, **conclusion détectable** par balise ancre (sinon le CR est écarté) |
| Représentativité | Échantillon **stratifié proportionnel** (année × sexe × tranche d'âge) |
| Livrable | **2 fichiers `.txt` par CR** : corps sans conclusion + conclusion seule (`_conclusion`) |
| Annotation | **Aucune** (guide §6.3 : « Pas besoin d'annotation sur ce cas d'usage ») |

Métadonnées **obligatoires** (guide §6.4) : la **strate** de chaque document, mentionnée **dans le
titre du fichier**, et si possible la fréquence de chaque strate dans la population globale.

---

## 2. Source de données — EDS Easily (SQL Server)

Identique aux CU1/CU5 : connexion `pyodbc` au serveur `srvapp600`, utilisateur `SITE_READER_BO`
(lecture seule).

| Table | Usage |
|---|---|
| `METADONE.metadone.DOCUMENTS` | Métadonnées des documents (`doc_nom`, dates, `doc_pat_id`…) |
| `NOYAU.patient.PATIENT` | Patients (`pat_ipp`, `pat_sexe`, `pat_date_naissance`) |
| `STOCKAGE.stockage.FILES` | Contenu (`fil_data` = PDF binaire, `fil_data_fs` = texte natif) |

---

## 3. Sélection des documents

### 3.1 Périmètre : *tous* les CR médicaux, par **exclusion** + filtre conclusion

Comme le CU1, le CU3 vise la **représentativité de l'activité de l'établissement** : tous les CR
cliniques sont éligibles, la sélection procède par **exclusion** des documents non cliniques via
des motifs sur `doc_nom` (`doc_exclusion_patterns` dans `WP3_CU3/config.py`) :

> arrêt de travail · transport · protocole de soin · **ordonnance** · **prescription** ·
> consentement · facture · administratif · **contexte de vie**

(Le guide CU3 §6.2 exclut explicitement les ordonnances. Les fiches « Contexte de vie » —
formulaires sociaux sans contenu clinique à résumer — ont été ajoutées après revue qualité :
leur balise « SYNTHESE » de template produisait des faux positifs. Ce filtre est ré-appliqué
sur `doc_nom` au chargement du pool par `extract_cu3.py`, au cas où le pool aurait été généré
avant l'ajout d'un motif.)

S'y ajoute le filtre **spécifique au CU3** : seuls les CR dont une **conclusion est détectée**
(voir §4) sont retenus. Les CR sans conclusion identifiable sont écartés — c'est une exigence du
guide (« une conclusion bien définie et identifiée »).

### 3.2 Filtres de la requête (`fetch_pool.py`)

```
date(CR) ∈ [2020-01-01 ; 2026-12-31]          -- doc_realisation_date sinon doc_creation_date
ET doc_supprime ≠ 'true'
ET pat_ipp non nul
ET TRY_CAST(doc_app_id AS INT) > 0            -- applications source valides
ET NOT ( doc_nom LIKE l'un des motifs d'exclusion )
ET (fil_data non nul OU fil_data_fs non nul)  -- un contenu doit exister
ORDER BY NEWID()                               -- tirage aléatoire côté SQL
```

Pool aléatoire de `sql_pool_size = 20 000` documents tiré côté SQL, stratifié ensuite côté Python.

### 3.3 Interprétation de la fenêtre temporelle

Le guide §6.2 indique : *« les CR sélectionnés doivent être relativement récents et dater au plus
tard entre 2020-2022 »*. Cette formulation est ambiguë. **Lecture retenue : CR datés de 2020 ou
après** (« relativement récents », borne basse 2020), fenêtre `2020-01-01 → 2026-12-31`.
La fenêtre est paramétrable dans `config.py` (`date_min`/`date_max`) si le CU3 lead
(perceval.wajsburt@aphp.fr) confirme une lecture stricte 2020–2022.

---

## 4. Détection et découpage de la conclusion

C'est l'étape **spécifique au CU3**, implémentée dans `utils/conclusion_splitter.py` et validée
par la **FAQ #10** du guide (approche « liste d'expressions types + regexp » explicitement admise,
protocole à documenter dans les métadonnées — c'est l'objet de cette section).

### 4.1 Balises ancres

Détection **insensible à la casse et aux accents**, balise en **début de ligne** :

> `EN CONCLUSION` · `CONCLUSIONS` · `CONCLUSION` · `AU TOTAL` · `EN SYNTHESE` · `SYNTHESE` · `EN RESUME`

Formes de ligne acceptées :

| Forme | Exemple | Conclusion retenue |
|---|---|---|
| Titre seul | `CONCLUSION` / `Conclusion :` | tout ce qui suit la ligne |
| Contenu sur la même ligne | `Conclusion : évolution favorable…` | reste de la ligne + suite |
| Prose introduite | `Au total, évolution favorable…` | reste de la ligne + suite |
| Titre étendu (≤ 60 car., finit par `:`) | `CONCLUSION DE L'EXAMEN :` | tout ce qui suit la ligne |

Si plusieurs balises matchent, on retient la **première occurrence dont le découpage passe les
garde-fous** du §4.2 : les balises trop précoces (documents multi-parties) échouent naturellement
sur le ratio conclusion/document, les sections de template vides sur la longueur utile. Ce choix
évite qu'une conclusion réelle reste dans le corps quand un court résumé la suit (fuite pour la
tâche de résumé) — défaut observé avec la stratégie initiale « dernière occurrence ».

### 4.2 Garde-fous (anti faux positifs)

Un split n'est **valide** que si :

| Contrôle | Seuil (config) | Raison de rejet |
|---|---|---|
| Longueur **utile** de la conclusion (car. non blancs, **hors lignes de pied de page** : IPP, « née le », pagination « x / y ») | ≥ 40 (`min_conclusion_chars`) | `conclusion_too_short` |
| Longueur du corps (car. non blancs) | ≥ 300 (`min_body_chars`) | `body_too_short` |
| Part de la conclusion dans le document | ≤ 60 % (`max_conclusion_ratio`) | `conclusion_too_large` |
| Taille totale du document (car. non blancs) | ≤ 150 000 (`max_doc_chars`) | `doc_too_large` |
| Balise titre subsistant dans le corps final (conclusion antérieure restée dans le corps → fuite) | — | `anchor_in_body` |
| Aucune balise trouvée | — | `no_anchor` |

Le décompte « utile » écarte les faux positifs où la « conclusion » n'est qu'un pied de page
identifiant (observés sur les fiches de type formulaire). Le rejet `anchor_in_body` écarte les
documents ambigus (multi-CR, doubles sections) dont le corps contiendrait encore une conclusion.

Le contrôle `doc_too_large` écarte les documents aberrants (exports cumulatifs type dossier
complet, > 50 pages) qui ne sont pas des CR à résumer — observés lors du premier run
(5 documents de 1,3 à 3,3 M de caractères).

Le corps livré est le texte **avant** la ligne de la balise ; la conclusion est le texte **après**
(y compris le contenu porté par la ligne de la balise elle-même, hors intitulé). Les lignes
vides et les éventuelles balises résiduelles en fin de corps (documents à balises consécutives,
ex. « CONCLUSION » puis « AU TOTAL : … ») sont retirées du corps.

### 4.3 Nettoyage du boilerplate RGPD/EDS

La mention d'information RGPD/EDS Foch (« *Vous êtes suivi(e) à l'Hôpital Foch…* »), présente en
fin de nombreux documents (13 % des conclusions au 2e run), est **retirée du texte avant le
découpage** (`strip_rgpd_boilerplate()` dans `utils/conclusion_splitter.py`) : détection de la
ligne marqueur (insensible casse/accents) et troncature jusqu'à la fin du document, avec un
garde-fou (pas de retrait si le bloc dépasse 3 000 caractères non blancs).

### 4.4 Limite connue

Le texte situé **après** la conclusion (formules de politesse, signature du praticien, champs
administratifs de lettre de liaison) reste dans le fichier `_conclusion` — il n'existe pas de
délimiteur fiable de fin de conclusion. Les entités identifiantes éventuelles seront traitées
par la pseudonymisation en aval.

---

## 5. Stratification (représentativité de l'activité)

Identique au CU1 : strate **`{année}_{sexe}_{tranche_âge}`** (ex. `2021_Homme_50-54ans`),
échantillonnage **proportionnel** aux fréquences observées dans le pool
(`stratified_sample()`), fréquence de strate enregistrée comme proxy de la fréquence dans la
population globale (`frequence_strate_population`).

Tranches d'âge : `0-17 · 18-29 · 30-39 · 40-49 · 50-54 · 55-59 · 60-64 · 65-69 · 70-79 · 80+`

---

## 6. Couche texte native — pas d'OCR

Politique identique aux CU5a/CU5b : seuls les documents à **couche texte native** sont retenus
(`fil_data_fs` texte, ou PDF via `pdfplumber`) ; les scans à océriser sont **écartés** faute
d'OCR fiable.

Conséquence pour les métadonnées CU3 (guide §6.3 + FAQ #5) : la répartition OCR/non-OCR du jeu
livré est **100 % non-OCR** — aucun fichier ne porte le suffixe `_ocr`, et la colonne `ocr` de
`metadata_cu3.csv` vaut `False` partout. À signaler au CU3 lead lors de la livraison.

Pour absorber les rejets (pas de couche texte **ou** pas de conclusion détectée), on tire un
sur-échantillon stratifié de `oversample_factor = 5.0` × la cible, puis on retient les
`target_count` premiers valides.

---

## 7. Architecture en 2 étapes

1. **`fetch_pool.py`** — une requête SQL → `output/pool_metadata.csv` (pool aléatoire de 20 000 docs).
2. **`extract_cu3.py`** — lit le pool, calcule les strates, sur-échantillonne (×5), télécharge les
   binaires par lots, extrait le texte natif, **détecte et découpe la conclusion**, et sauvegarde
   la sélection finale.

```bash
python WP3_CU3/fetch_pool.py
python WP3_CU3/extract_cu3.py
```

---

## 8. Sorties & anonymisation

```
WP3_CU3/output/
├── txt/                                        # LIVRABLE : 2 fichiers par CR
│   ├── {file_id}_{strate}.txt                  #   corps du CR SANS la conclusion
│   └── {file_id}_{strate}_conclusion.txt       #   conclusion seule
├── raw_pdf/  {file_id}.pdf                     # PDF sources conservés (traçabilité)
├── metadata_cu3.csv                            # métadonnées (voir ci-dessous)
└── ipp_cu3.csv                                 # IPP patients — usage INTERNE, NE PAS livrer
```

- **`file_id`** = `SHA-256(doc_id)` tronqué à 12 caractères → identifiant anonyme et stable.
- La **strate figure dans le nom des fichiers** (métadonnée obligatoire, guide §6.4) —
  ex. `a3f2b1c4d5e6_2021_Homme_50-54ans.txt` + `a3f2b1c4d5e6_2021_Homme_50-54ans_conclusion.txt`.
- **`ipp_cu3.csv`** : à **ne jamais livrer** au Health Data Hub.
- `output/` est exclu du dépôt (`.gitignore`) : aucune donnée patient versionnée.

**Colonnes de `metadata_cu3.csv`** : `file_id`, `filename_texte`, `filename_conclusion`, `strate`,
`frequence_strate_population`, `doc_date`, `departement_code`, `balise_conclusion` (ancre ayant
matché), `body_chars`, `conclusion_chars`, `ocr` (False — pas d'OCR), `export_success`.

---

## 9. Paramètres clés (`WP3_CU3/config.py`)

| Paramètre | Valeur | Rôle |
|---|---|---|
| `target_count` / `min` / `max` | 400 / 100 / 1000 | Volume de l'échantillon |
| `date_min` / `date_max` | 2020-01-01 / 2026-12-31 | Fenêtre temporelle (voir §3.3) |
| `doc_exclusion_patterns` | (voir §3.1) | Documents non cliniques exclus |
| `conclusion_anchors` | (voir §4.1) | Balises ancres de détection |
| `min_conclusion_chars` / `min_body_chars` | 40 / 300 | Seuils de validité du split |
| `max_conclusion_ratio` | 0.6 | Anti faux positif (balise trop tôt) |
| `max_doc_chars` | 150 000 | Rejet des documents aberrants (exports cumulatifs) |
| `age_bins` / `age_labels` | 10 tranches | Découpage d'âge des strates |
| `sql_pool_size` | 20 000 | Taille du pool aléatoire SQL |
| `oversample_factor` | 5.0 | Marge pour absorber les rejets (texte + conclusion) |
| `max_workers` | 6 | Parallélisme de validation |

---

## 10. Conformité au guide PARTAGES (section 6)

| Exigence du guide (§6) | Statut |
|---|---|
| Profondeur : CR relativement récents | ✅ `date_min = 2020` (interprétation documentée §3.3, paramétrable) |
| Représentativité par année, sexe, tranche d'âge | ✅ Stratification proportionnelle `année × sexe × âge` |
| Contenu purement textuel (.txt), ordonnances exclues | ✅ Couche texte native + motifs d'exclusion |
| Conclusion bien définie et identifiée | ✅ Détection par balises ancres (FAQ #10), rejets sinon |
| 2 fichiers .txt par CR, suffixe `_conclusion` | ✅ `{file_id}_{strate}.txt` + `..._conclusion.txt` |
| Strate dans le titre du fichier (obligatoire §6.4) | ✅ Strate incluse dans le nom des 2 fichiers |
| Fréquence des strates (si possible) | ✅ `frequence_strate_population` dans `metadata_cu3.csv` |
| Préciser le traitement d'extraction / OCR au CU3 lead | 🟡 À faire à la livraison : 100 % non-OCR, protocole §4 |
| Suffixe `_ocr` pour les CR océrisés | ✅ N/A — aucun document océrisé (aucun suffixe) |
| Annotation | N/A (« Pas besoin d'annotation sur ce cas d'usage ») |

---

## 11. Limites connues

- **Rejet des scans** : pas d'OCR — l'échantillon est 100 % couche texte native (biais possible
  vers les documents produits nativement par le DPI).
- **Détection de conclusion par balises** : les CR utilisant une formulation non listée sont
  écartés (`no_anchor`) ; la liste est paramétrable et le taux de rejet est affiché à l'exécution.
- **Fin de conclusion** : signature/formules de politesse/champs administratifs inclus dans le
  fichier `_conclusion` (§4.4) ; la mention RGPD/EDS est en revanche retirée (§4.3).
- **Fenêtre temporelle** : interprétation « ≥ 2020 » à confirmer avec le CU3 lead (§3.3).

---

## 12. Reproductibilité

Les tirages aléatoires utilisent `random_state = 42` ; à pool et paramètres constants, l'extraction
est reproductible. Pré-requis : accès Easily depuis le réseau Foch.
