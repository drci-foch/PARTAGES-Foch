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
| Spécialités visées | Urologie, chirurgie digestive, orthopédie (GHM de l'annexe PARTAGES) |
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
ET ghm ∈ ghm_whitelist                 -- liste de l'annexe PARTAGES (si renseignée)
PUIS dédoublonnage sur numero_admin    -- un séjour = une ligne
```

- **Durée = 0** : sélectionne l'ambulatoire (et les hôpitaux de jour), conformément au guide.
- **Filtre GHM** : la `ghm_whitelist` (`WP2_CU2/config.py`) restreint aux GHM de l'annexe (urologie,
  chirurgie digestive, orthopédie). Voir §10 (point en attente).

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
| `Spécialité` | Spécialité médicale déduite du GHM | mapping GHM (§5.1) |
| `Texte` | CRH et/ou CRO concaténés (une seule colonne) | Easily |
| `Codes CCAM` | Codes CCAM du séjour, **séparés par un espace** | RSS |
| `CIM-10 DP` | Diagnostic principal du séjour (**cible**) | RSS |

> Les **libellés** des actes CCAM ne sont **pas** ajoutés ici : le guide précise qu'ils sont
> concaténés **automatiquement sur la plateforme PARTAGES** au cours du traitement. On ne fournit
> donc que les **codes** CCAM.

### 5.1 De GHM à spécialité
`get_specialite()` déduit la spécialité du **préfixe à 2 caractères du GHM** (catégorie majeure de
diagnostic, ex. `06 → Appareil digestif`, `08 → Appareil musculo-squelettique`, `11/12 → uro-génital`).
Mapping dans `ghm_to_specialite` (`WP2_CU2/config.py`). Voir §10 pour l'alignement sur le regroupement
exact de l'annexe.

---

## 6. Architecture en 2 étapes

1. **`fetch_rss.py`** — parse les RSS, filtre (ambulatoire, GHM), dédoublonne → `output/pool_rss.csv`.
2. **`extract_cu2.py`** — tire aléatoirement `target_count` séjours (`random_state = 42`), apparie les
   CR, extrait le texte, écrit le dataset. **Reprise automatique** : les séjours déjà présents dans le
   CSV de sortie sont ignorés (écriture ligne à ligne, robuste aux interruptions).

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
| `ghm_whitelist` | (vide → à renseigner) | GHM de l'annexe (urologie/digestif/ortho) |
| `crh_doc_patterns` / `cro_doc_patterns` | motifs | Identification CRH / CRO |
| `ghm_to_specialite` | dict | GHM (préfixe 2c) → spécialité |
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
| Séjours filtrés sur les **GHM de l'annexe** (uro/digestif/ortho) | ⚠️ En attente de la liste GHM (§10) |
| Spécialité = **GHM regroupés** (liste annexe) | ⚠️ Proxy par CMD ATIH en attendant (§10) |
| Métadonnées 5.4 : nb séjours/spécialité, **sexe ratio**, **âge moyen**, **fréquence CIM-10** | ✅ Conforme (`cu2_stats.csv` + `cu2_cim10_frequency.csv`) |
| Représentativité de chaque GHM (5.2) | 🟡 Tirage aléatoire (proportions naturelles) |

---

## 10. Points en attente / limites

- **Liste GHM de l'annexe (bloquant pour le périmètre exact)** : `ghm_whitelist` est **vide** ⇒
  aucun filtre GHM n'est appliqué, donc la sélection couvre **tous** les séjours ambulatoires et pas
  seulement urologie / chirurgie digestive / orthopédie. À renseigner dès réception de l'annexe
  auprès du porteur de projet.
- **Spécialité** : déduite de la **catégorie majeure de diagnostic** (préfixe GHM 2 car.), proxy en
  attendant le **regroupement exact** GHM→spécialité de l'annexe.
- **Codage professionnalisé** (5.2) : recommandé par le guide, non vérifiable automatiquement.

---

## 11. Reproductibilité

Le tirage des séjours utilise `random_state = 42` ; à pool constant, l'extraction est reproductible.
L'écriture ligne à ligne permet de **reprendre** une extraction interrompue sans doublon. Pré-requis :
accès Easily, lecteur `S:\` (RSS), et Java + le jar `pdftotext` pour la conversion PDF → texte.
