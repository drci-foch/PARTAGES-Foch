# Méthodologie d'extraction — CU2

> Projet PARTAGES (Health Data Hub) — Hôpital Foch
> Guide de référence : *Guide de préparation des données par CU* v29.01.26 (section 5 + FAQ).

Ce document explique **comment** le jeu de données CU2 a été constitué : les sources, la sélection
des séjours, l'appariement PMSI ↔ comptes rendus, la construction du fichier livré, et la
**conformité au guide PARTAGES** (§9).

---

## 1. Objectif

**CU2 — Codage automatique d'informations médicales (DIM).** Constituer un jeu de données de séjours
de **chirurgie ambulatoire** associant le **texte des comptes rendus** (CRH/CRO) et les **codes CCAM**
du séjour, avec pour cible le **code CIM-10 du diagnostic principal (DP)**. Objectif : évaluer un
modèle qui prédit le DP à partir du compte rendu et des actes.

| Paramètre | Valeur |
|---|---|
| Volume cible | **1 000 séjours** (tirage aléatoire) |
| Période | **2023–2025** |
| Périmètre | Séjours de **chirurgie ambulatoire** (durée = 0 jour) |
| Spécialités visées | Chirurgie orthopédique/traumato, chirurgie viscérale, urologie — **71 GHM** de l'annexe PARTAGES (13/12/2025) |
| Entrée | Texte CRH et/ou CRO + codes CCAM du séjour |
| Cible | CIM-10 du diagnostic principal (PMSI) |
| Annotation | **Aucune** (simple fichier CSV) |

---

## 2. Sources de données

| Source | Contenu |
|---|---|
| **RSS PMSI** (`S:\Envoi-EDS-PMSI`) | Séjours : GHM, durée, **diagnostics CIM-10** (DP/DR/DA), **actes CCAM**, sexe, date de naissance, `numero_admin` |
| **EDS Easily** (SQL Server) | Texte des comptes rendus : `METADONE.metadone.DOCUMENTS` + `STOCKAGE.stockage.FILES`, reliés au séjour via `NOYAU.patient.VENUE`/`PATIENT` |

Le RSS apporte la **cible** (CIM-10 DP) et les **actes CCAM** ; Easily apporte le **texte** (CRH/CRO).
La jonction entre les deux constitue le cœur du pipeline (§4).

---

## 3. Sélection des séjours (`fetch_rss.py`)

Le format **RSS groupé 120** (ATIH 2020) est parsé par `utils/rss_parser.py`. Filtres appliqués :

```
Années ∈ {2023, 2024, 2025}
ET durée de séjour = 0 jour            -- chirurgie ambulatoire (inclut les HDJ)
ET ghm ∈ ghm_whitelist                 -- 71 GHM de l'annexe PARTAGES
PUIS dédoublonnage sur numero_admin    -- un séjour = une ligne
```

- **Durée = 0** : sélectionne l'ambulatoire (et les hôpitaux de jour), conformément au guide.
- **Filtre GHM** : la `ghm_whitelist` est chargée automatiquement depuis le **référentiel versionné**
  `WP2_CU2/referentiel/liste_ghm_chirurgie_ambulatoire.csv` (annexe PARTAGES du 13/12/2025,
  convertie de l'Excel en CSV UTF-8). Il contient **71 GHM** : 32 chirurgie orthopédique/traumato,
  21 chirurgie viscérale, 18 urologie.
- **Sécurité** : le filtre GHM est **aussi appliqué au chargement du pool** dans `extract_cu2.py`
  (`load_pool`), afin qu'un `pool_rss.csv` généré avant réception du référentiel soit filtré à la
  volée sans devoir relancer `fetch_rss.py`. Sur le pool Foch 2023–2025 : 151 121 séjours
  ambulatoires → **6 695 séjours** dans le périmètre GHM.

Le pool éligible est sauvegardé dans `output/pool_rss.csv`.

---

## 4. Appariement séjour ↔ comptes rendus (`extract_cu2.py`)

Pour chaque séjour tiré, on recherche ses CRH/CRO dans Easily selon deux stratégies successives
(`find_docs_for_sejour`) :

1. **Par numéro de séjour** : `VENUE.ven_numero = numero_admin` (du RSS).
2. **Repli par patient + dates** : si rien trouvé, via `pat_ipp` et la fenêtre
   `[date_entrée − tolérance ; date_sortie + tolérance]` (`tolerance_days = 3`).

Les documents recherchés sont identifiés par des **motifs de nom** :

- **CRH** : `Fiche Hospitalisation`, `Compte-Rendu d'Hospitalisation`, `CRH`, `Lettre de Liaison`…
- **CRO** : `Compte-Rendu Opératoire`, `CRO`…

(`crh_doc_patterns` / `cro_doc_patterns` dans `WP2_CU2/config.py`.)

### Extraction du texte
Le binaire PDF (`fil_data`) est converti en texte via le **jar Java `pdftotext`** (décodage
cp1252 → latin-1 → utf-8). Un document est retenu si le texte fait **≥ 100 caractères**. Les textes
CRH et CRO d'un même séjour sont **concaténés dans une seule colonne** (séparés par `---`).

---

## 5. Construction du fichier livré (5 colonnes)

`output/cu2_dataset.csv` (séparateur `;`, encodage `utf-8-sig`) :

| Colonne | Contenu | Source |
|---|---|---|
| `ID` | Identifiant anonymisé du séjour = `SHA-256(numero_admin)` tronqué à 16 hex | calculé |
| `Spécialité` | Spécialité médicale du GHM (référentiel annexe) | mapping GHM (§5.1) |
| `Texte` | CRH et/ou CRO concaténés (une seule colonne) | Easily |
| `Codes CCAM` | Codes CCAM du séjour, **séparés par un espace** | RSS |
| `CIM-10 DP` | Diagnostic principal du séjour (**cible**) | RSS |

> Les **libellés** des actes CCAM ne sont **pas** ajoutés ici : le guide précise qu'ils sont
> concaténés **automatiquement sur la plateforme PARTAGES** au cours du traitement. On ne fournit
> donc que les **codes** CCAM.

### 5.1 De GHM à spécialité
`get_specialite()` utilise en priorité le **mapping exact GHM → spécialité du référentiel de
l'annexe** (`ghm_specialites`, chargé depuis
`WP2_CU2/referentiel/liste_ghm_chirurgie_ambulatoire.csv`) : `CH.ORTHO.ET TRAUMATO`,
`CHIRURGIE VISCERALE`, `UROLOGIE`. En repli (GHM hors référentiel, cas normalement impossible après
filtrage), la spécialité est déduite du **préfixe à 2 caractères du GHM** (catégorie majeure de
diagnostic, `ghm_to_specialite`).

---

## 6. Architecture en 2 étapes

1. **`fetch_rss.py`** — parse les RSS, filtre (ambulatoire, GHM), dédoublonne → `output/pool_rss.csv`.
2. **`extract_cu2.py`** — re-filtre le pool par GHM (sécurité), tire aléatoirement `target_count`
   séjours (`random_state = 42`), apparie les CR, extrait le texte, écrit le dataset.
   **Reprise automatique** : les séjours déjà présents dans le CSV de sortie sont ignorés (écriture
   ligne à ligne, robuste aux interruptions). **Garde-fou** : si des séjours déjà extraits sont hors
   du pool filtré (extraction antérieure au référentiel GHM), une alerte demande d'archiver les
   sorties et de relancer.

```bash
python WP2_CU2/fetch_rss.py
python WP2_CU2/extract_cu2.py
```

---

## 7. Sorties & anonymisation

```
WP2_CU2/output/
├── pool_rss.csv                    # Pool de séjours éligibles (étape 1)
├── cu2_dataset.csv                 # Dataset livré à PARTAGES (5 colonnes)
├── cu2_stats.csv                   # Par spécialité : nb séjours, sexe (H/F), âge moyen, CIM-10 DP dominant
├── cu2_cim10_frequency.csv         # Distribution complète des CIM-10 DP (code, nb, fréquence)
└── cu2_correspondance_INTERNE.csv  # ID anonymisé ↔ numero_admin réel (INTERNE)
```

- **`ID`** = `SHA-256(numero_admin)` tronqué à 16 caractères → identifiant anonyme et stable.
- **`cu2_correspondance_INTERNE.csv`** : table de ré-identification — **usage INTERNE uniquement,
  à NE JAMAIS livrer** au Health Data Hub.
- `output/` et `*.pdf` sont exclus du dépôt (`.gitignore`) : aucune donnée patient versionnée.
- **Pas d'annotation** : le livrable est le CSV (conforme au guide).

### 7.1 Métadonnées descriptives (guide §5.4)

Le guide impose un document décrivant les cas cliniques sélectionnés. Ces métadonnées **obligatoires**
sont produites automatiquement (`_print_and_save_stats` + `_enrich_with_demographics`) en reliant le
dataset au RSS (sexe, date de naissance, date d'entrée) via la table de correspondance :

- **Nombre de séjours par spécialité** — `cu2_stats.csv` (`nb_sejours`).
- **Sexe ratio** — `cu2_stats.csv` (`nb_hommes` / `nb_femmes`) + ratio global affiché en console.
- **Âge moyen** — `cu2_stats.csv` (`age_moyen`, calculé `année d'entrée − année de naissance`) +
  moyenne globale en console.
- **Fréquence des diagnostics CIM-10** — `cu2_cim10_frequency.csv` (distribution complète des DP).

---

## 8. Paramètres clés (`WP2_CU2/config.py`)

| Paramètre | Valeur | Rôle |
|---|---|---|
| `years` | 2023, 2024, 2025 | Période |
| `target_count` | 1000 | Nombre de séjours tirés |
| `only_ambulatoire` | True | Filtre durée = 0 |
| `ghm_whitelist` | 71 GHM (chargés du référentiel) | GHM de l'annexe (ortho/viscéral/uro) |
| `ghm_specialites` | dict (chargé du référentiel) | Mapping exact GHM → spécialité |
| `crh_doc_patterns` / `cro_doc_patterns` | motifs | Identification CRH / CRO |
| `ghm_to_specialite` | dict | Repli : GHM (préfixe 2c) → spécialité |
| `tolerance_days` | 3 | Fenêtre d'appariement par dates |
| `rss_base_path` | `S:\Envoi-EDS-PMSI` | Source RSS |

---

## 9. Conformité au guide PARTAGES (section 5 + FAQ)

| Exigence du guide | Statut |
|---|---|
| Période 2023–2025 | ✅ Conforme |
| Séjours de chirurgie ambulatoire (durée = 0) | ✅ Conforme |
| Inclure les HDJ (FAQ #8) | ✅ Conforme (0 jour) |
| CRH **et/ou** CRO, concaténés dans **une seule** colonne (FAQ #8) | ✅ Conforme |
| Codes CCAM **séparés par un espace** (FAQ #9) | ✅ Conforme |
| Libellés CCAM ajoutés **par la plateforme**, pas par l'ES | ✅ Conforme (codes seuls fournis) |
| Appariement PMSI ↔ CR (n° séjour, puis IPP + dates) | ✅ Conforme |
| CIM-10 du DP comme cible | ✅ Conforme |
| Pas d'annotation (FAQ #2) | ✅ Conforme |
| ID anonymisé | ✅ Conforme (hash SHA-256) |
| 5 colonnes : ID, Spécialité, Texte, Codes CCAM, CIM-10 DP | ✅ Conforme |
| Séjours filtrés sur les **GHM de l'annexe** (ortho/viscéral/uro) | ✅ Conforme (71 GHM, référentiel du 13/12/2025) |
| Spécialité = **GHM regroupés** (liste annexe) | ✅ Conforme (mapping exact du référentiel) |
| Métadonnées 5.4 : nb séjours/spécialité, **sexe ratio**, **âge moyen**, **fréquence CIM-10** | ✅ Conforme (`cu2_stats.csv` + `cu2_cim10_frequency.csv`) |
| Représentativité de chaque GHM (5.2) | 🟡 Tirage aléatoire (proportions naturelles) |

---

## 10. Points en attente / limites

- **Liste GHM de l'annexe** : ✅ **résolu** — référentiel reçu le 13/12/2025 et versionné dans
  `WP2_CU2/referentiel/liste_ghm_chirurgie_ambulatoire.csv` (71 GHM). Le filtre et le mapping
  spécialité sont chargés automatiquement ; une extraction lancée **avant** réception du référentiel
  est détectée au démarrage (garde-fou : séjours déjà extraits hors du pool filtré) avec consigne
  d'archiver les sorties et de relancer.
- **Codage professionnalisé** (5.2) : recommandé par le guide, non vérifiable automatiquement.

---

## 11. Reproductibilité

Le tirage des séjours utilise `random_state = 42` ; à pool constant, l'extraction est reproductible.
L'écriture ligne à ligne permet de **reprendre** une extraction interrompue sans doublon. Pré-requis :
accès Easily, lecteur `S:\` (RSS), et Java + le jar `pdftotext` pour la conversion PDF → texte.
