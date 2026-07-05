# INCEpTION — Mise en place de A à Z pour l'annotation PARTAGES

> Projet PARTAGES (Health Data Hub) — Hôpital Foch
> Guide de référence : *Guide de préparation des données par CU* v29.01.26 (§4.3, §7.3, §8.3, §9.2, FAQ #1, #4, #6).

Ce document décrit l'installation d'INCEpTION et la mise en place des projets d'annotation
pour les cas d'usage qui en ont besoin, jusqu'à l'export au format **JSON UIMA CAS** (seul
format imposé par PARTAGES — FAQ #6).

---

## 1. Quels CU nécessitent INCEpTION ?

| CU | Annotation | Tâche d'annotation | Corpus (déjà extrait) | Annotateurs requis |
|----|------------|--------------------|-----------------------|--------------------|
| **CU1** | ✅ Oui | Entités identifiantes (pseudonymisation) | `WP1_CU1/output/txt/` — 400 CR | Pas d'expertise spécifique (guide §4.3) |
| CU2 | ❌ Non | — (CSV seul, FAQ #2) | — | — |
| CU3 | ❌ Non | — (guide §6.3 : « pas besoin d'annotation ») | — | — |
| **CU5a** | ✅ Oui | Biomarqueurs tumoraux + normalisation (entités + relations) | `WP5_CU5a/output/txt/` — 150 CR | Médecins et/ou ARC spécialisés en oncologie (§7.3) |
| **CU5b** | ✅ Oui | Réponse au traitement — classification **au niveau document** (4 classes + ND/NA) | `WP5_CU5b/output/txt/` — 500 CR | Médecins et/ou ARC spécialisés en oncologie (§8.3) |

**Échéance PARTAGES : annotations à finaliser d'ici fin septembre 2026.**

Les **templates INCEpTION officiels** des 3 CU sont dans ce dossier
(`Template INCEpTION - Tags et Label CU1, CU5a, CU5b.zip` — exports de projets INCEpTION 38.5 :
CU1 = couche `EntiteAnonymisation` 16 catégories ; CU5a = `SpanBiomarker` 209 biomarqueurs
normalisés + relation `RefersTo` ; CU5b = métadonnée document `Nomenclature` 4 classes + ND/NA).
Les guides d'annotation et tutoriels vidéo associés (FAQ #1) sont fournis par le projet —
à défaut, les demander aux CU leads :

- CU1 : partages-wp8@health-data-hub.fr (+ exemple de fichier JSON CU1)
- CU5a / CU5b : flavien.gilles@curie.fr
- Toujours mettre en copie : partages-wp1@health-data-hub.fr

---

## 2. Installation d'INCEpTION

> **Voie recommandée : Docker.** Un kit de déploiement prêt à l'emploi (compose +
> configuration + import automatique des 3 projets PARTAGES) est fourni dans
> [`docker/`](docker/README.md) — testé de bout en bout. La suite de cette section
> décrit l'alternative « JAR standalone » (sans Docker) ; les sections 3 à 7
> s'appliquent dans les deux cas.

### 2.1 Contrainte préalable — données de santé

Les CR contiennent des données patient **non pseudonymisées**. INCEpTION doit tourner
**exclusivement sur le réseau Foch** (poste ou serveur interne). Aucun hébergement cloud,
aucune exposition internet. L'accès multi-annotateurs se fait via le réseau interne.

### 2.2 Prérequis

- **Java 17 ou plus récent** (JRE/JDK — ex. [Temurin/Adoptium](https://adoptium.net/)).
  Vérifier : `java -version`
- 4 Go de RAM disponibles minimum (8 Go recommandés pour plusieurs annotateurs simultanés)
- Un poste/serveur accessible par tous les annotateurs sur le réseau Foch

### 2.3 Téléchargement et premier lancement

1. Télécharger le JAR *standalone* de la dernière version stable :
   <https://inception-project.github.io/downloads/> → `inception-app-webapp-<version>-standalone.jar`
2. Créer un répertoire de données dédié (sauvegardes plus simples), par exemple :

   ```powershell
   mkdir D:\inception-data
   $env:INCEPTION_HOME = "D:\inception-data"
   ```

3. Lancer :

   ```powershell
   java -Xmx4g "-Dinception.home=D:\inception-data" -jar inception-app-webapp-<version>-standalone.jar
   ```

4. Ouvrir <http://localhost:8080>. Au premier démarrage, créer/renseigner le compte
   **administrateur** (si la version propose `admin`/`admin` par défaut : **changer
   immédiatement le mot de passe**).

Pour un accès multi-postes, ouvrir le port 8080 sur le pare-feu du serveur et communiquer
l'URL `http://<nom-du-serveur>:8080` aux annotateurs.

### 2.4 Configuration utile (`settings.properties`)

Fichier à créer dans le répertoire de données (`D:\inception-data\settings.properties`) :

```properties
# Port d'écoute (si 8080 occupé)
server.port=8080

# Interdire l'auto-inscription : les comptes sont créés par l'admin
security.accept-new-users=false
```

Redémarrer INCEpTION après modification.

### 2.5 Lancement automatique et sauvegardes

- **Service Windows** : créer une tâche planifiée « au démarrage » qui exécute la commande
  du §2.3 (ou utiliser NSSM pour un vrai service).
- **Sauvegarde** : arrêter INCEpTION puis copier l'intégralité de `D:\inception-data`
  (contient la base et les documents). À faire **quotidiennement pendant les campagnes
  d'annotation** — l'effort d'annotation est coûteux (médecins/ARC), ne pas le perdre.

---

## 3. Comptes et rôles

Dans **Administration → Users** (connecté en admin) :

1. Créer un compte par annotateur (et par curateur), avec mot de passe individuel.
2. Rôle global `ROLE_USER` suffit pour les annotateurs.

Les droits fins se règlent **par projet** (Settings → Users du projet) :

| Rôle projet | Qui | Droit |
|---|---|---|
| **Manager** | Chef de projet data / DRCI | Paramétrage, import/export, suivi |
| **Annotator** | Annotateurs (médecins, ARC, data scientists selon CU) | Annoter les documents qui leur sont assignés |
| **Curator** | Référent médical / senior | Fusionner et arbitrer les annotations (curation) |

---

## 4. Création des projets — un projet par CU

### 4.1 Import du template PARTAGES (recommandé)

Les templates officiels (fichiers `.zip` de projet INCEpTION) contiennent déjà les **couches
d'annotation** (layers), les **tagsets** et les recommandations du guide d'annotation :

1. Page d'accueil → **Import project** (ou Projects → Import).
2. Sélectionner le `.zip` du template du CU (CU1, CU5a ou CU5b).
3. Renommer le projet clairement : `PARTAGES-CU1-Foch`, `PARTAGES-CU5a-Foch`, `PARTAGES-CU5b-Foch`.

> Si les templates ne sont pas disponibles, créer un projet vierge et reconstruire les couches
> d'après le guide d'annotation du CU — mais **valider le schéma avec le CU lead avant** de
> lancer les annotateurs (le schéma doit être aligné pour l'évaluation).

### 4.2 Import des documents

Pour chaque projet : **Settings → Documents → Import**.

- Format : **Plain text (UTF-8)** — les `.txt` produits par les pipelines d'extraction :

| Projet | Dossier source | Volume |
|---|---|---|
| `PARTAGES-CU1-Foch` | `WP1_CU1/output/txt/*.txt` | 400 |
| `PARTAGES-CU5a-Foch` | `WP5_CU5a/output/txt/*.txt` | 150 |
| `PARTAGES-CU5b-Foch` | `WP5_CU5b/output/txt/*.txt` | 500 |

- L'import accepte la sélection multiple (glisser-déposer l'ensemble des fichiers).
- **Ne pas importer** les fichiers `metadata_*.csv` ni `ipp_*.csv`.
- Les noms de fichiers (`{file_id}.txt`) sont les identifiants anonymes : ils font le lien
  avec `metadata_<cu>.csv` à la livraison — ne pas les renommer.

### 4.3 Spécificités par CU

**CU1 — Pseudonymisation**
- Annotation d'entités identifiantes (noms, prénoms, dates, adresses, téléphones, IPP/NDA…)
  selon le schéma du template CU1.
- **Pré-annotation possible** avec *pseudoFoch* (cf. TODO CU1 du README racine) : générer les
  pré-annotations au format **UIMA CAS XMI** ou **JSON CAS** avec les mêmes noms de couches
  que le template, puis les importer comme documents annotés (Settings → Documents → Import,
  choisir le format CAS correspondant). Les annotateurs corrigent au lieu de partir de zéro.
- ⚠️ Guide §4.4 : si une pré-annotation par modèle est utilisée, **le documenter dans les
  métadonnées livrées** (approche, taux de correction).
- Alternative intégrée : les **Recommenders** d'INCEpTION (Settings → Recommenders) proposent
  des suggestions qui apprennent au fil de l'annotation — à documenter de la même façon.

**CU5a — Biomarqueurs**
- Entités : biomarqueurs, valeurs, unités, statuts (IHC/FISH/NGS), techniques… selon le
  template CU5a.
- **Relations** : l'attribut `refers_to` se crée comme une **relation** entre l'annotation
  (amplification, taux, mutation) et le biomarqueur. **L'orientation de la flèche importe
  peu** (FAQ #4).
- Avant de lancer la campagne : clarifier avec le CU lead les règles en suspens
  (normalisation des valeurs, documents multi-CR, mentions négatives/absentes — cf. TODO CU5a).

**CU5b — Réponse au traitement**
- Classification **au niveau du document** : 4 classes + ND/NA (définies dans le guide
  d'annotation CU5b). Dans INCEpTION, cela correspond à une couche de type **Document
  metadata** (une valeur par CR), fournie par le template.
- Avant de lancer : clarifier la gestion des cas ambigus avec le CU lead (cf. TODO CU5b).

---

## 5. Campagne d'annotation

1. **Calibration** : faire annoter les **mêmes 5–10 documents** par tous les annotateurs,
   comparer (page **Agreement**), discuter les divergences, consigner les décisions dans un
   document de conventions locales. Répéter jusqu'à un accord satisfaisant.
2. **Assignation** : par défaut chaque annotateur voit tous les documents ; pour répartir la
   charge, utiliser **Workload** (Settings → Workload → *matrix workload*) et assigner les
   documents. Prévoir un **double aveugle** (2 annotateurs/document) au moins sur un
   sous-ensemble, pour mesurer l'accord inter-annotateurs.
3. **Suivi** : page **Monitoring** du projet (avancement par document et par annotateur).
4. **Marquage terminé** : l'annotateur clique sur le cadenas (*Finish document*) quand un
   document est fini — condition pour la curation.
5. **Curation** : le curateur ouvre **Curation**, fusionne les annotations des annotateurs
   document par document et produit la version de référence (c'est **la version curée qui
   est livrée**).

---

## 6. Export JSON UIMA CAS et livraison

Le format de livraison imposé est **JSON UIMA CAS** (guide §9.2) : un seul fichier par CR,
contenant à la fois le texte (`sofaString`), les annotations et les métadonnées.

### 6.1 Export

- **Projet complet** : Settings → **Export** → format **UIMA CAS JSON** (ou « JSON CAS ») —
  choisir les documents **curés** (curated) si la curation a été faite, sinon les documents
  annotés.
- Vérifier que chaque `.json` porte bien le nom du document source (`{file_id}.txt.json` ou
  équivalent) pour garder le lien avec `metadata_<cu>.csv`.

### 6.2 Contrôle avant livraison (dkpro-cassis)

Les fichiers doivent être lisibles par [dkpro-cassis](https://github.com/dkpro/dkpro-cassis)
(guide §9.2). Contrôle rapide :

```bash
pip install dkpro-cassis
```

```python
from pathlib import Path
from cassis import load_cas_from_json

for f in Path("export_cu1").glob("*.json"):
    cas = load_cas_from_json(f)          # lève une erreur si le fichier est invalide
    assert cas.sofa_string, f"{f.name}: texte vide"
print("OK : tous les exports sont lisibles par dkpro-cassis")
```

### 6.3 Rappels livraison

- Livrer : les **JSON UIMA CAS** + les métadonnées (`metadata_cu1.csv`, `metadata_cu5a.csv`,
  `metadata_cu5b.csv`).
- **Ne jamais livrer** : `ipp_cu1.csv`, `ipp_cu5a.csv`, `ipp_cu5b.csv`,
  `cu2_correspondance_INTERNE.csv`.
- CU1 : documenter la pré-annotation éventuelle dans les métadonnées (§4.4 du guide).

---

## 7. Dépannage rapide

| Problème | Piste |
|---|---|
| `java` introuvable / version < 17 | Installer un JDK 17+ (Temurin) et vérifier le `PATH` |
| Port 8080 occupé | `server.port=8081` dans `settings.properties` |
| Lenteurs avec plusieurs annotateurs | Augmenter `-Xmx` (ex. `-Xmx8g`) |
| Mot de passe admin perdu | Repartir du répertoire de données sauvegardé (d'où l'importance des sauvegardes §2.5) |
| Import .txt illisible (accents) | Vérifier que le format d'import est bien **Plain text (UTF-8)** — les `.txt` des pipelines sont écrits en UTF-8 |
| L'export ne propose pas « UIMA CAS JSON » | Mettre à jour INCEpTION (format présent dans les versions récentes) |

---

## 8. Ressources

- Site officiel : <https://inception-project.github.io/> (téléchargements, documentation
  utilisateur et administrateur, vidéos)
- dkpro-cassis : <https://github.com/dkpro/dkpro-cassis>
- Guide PARTAGES v29.01.26 (PDF à la racine du repo) — sections annotation par CU + FAQ
- Templates INCEpTION + guides d'annotation + tutoriels vidéo PARTAGES : liens dans le guide
  PDF, sinon demander aux CU leads (§1)
