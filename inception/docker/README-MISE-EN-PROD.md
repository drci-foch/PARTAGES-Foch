# Mise en production d'INCEpTION — Projet PARTAGES (Hôpital Foch)

> Guide pas à pas pour l'administrateur qui déploie INCEpTION sur le serveur de
> production. Aucune connaissance d'INCEpTION n'est requise : suivre les étapes dans
> l'ordre. Durée estimée : ~30 minutes (hors création des comptes annotateurs).

**Contexte.** INCEpTION est l'outil d'annotation utilisé pour le projet PARTAGES
(Health Data Hub). Trois équipes vont y annoter des comptes rendus médicaux :
pseudonymisation (CU1), biomarqueurs en oncologie (CU5a), réponse au traitement (CU5b).
Ce dossier contient **tout le nécessaire** : la configuration Docker, les projets
pré-paramétrés et les documents à annoter.

> **Serveur cible : Linux.** Ce guide utilise les commandes `bash` / `docker compose`
> et les scripts `.sh`. Les scripts `.ps1` du dossier `docker/` ne servent qu'aux tests
> sous Windows et peuvent être ignorés en production.

⚠️ **Les dossiers `CU1/`, `CU5a/`, `CU5b/` contiennent des données patient non
pseudonymisées.** Ce dossier ne doit exister que sur le réseau interne Foch, et le
serveur ne doit jamais être exposé sur internet.

---

## Contenu du dossier

| Élément | Rôle |
|---|---|
| `README.md` | Ce guide |
| `docker/` | Configuration Docker (compose, settings) + scripts d'installation |
| `Template INCEpTION - Tags et Label CU1, CU5a, CU5b.zip` | Projets INCEpTION officiels PARTAGES (utilisé par le script d'installation) |
| `CU1/` | **400 fichiers .txt** à annoter — pseudonymisation |
| `CU5a/` | **150 fichiers .txt** à annoter — biomarqueurs |
| `CU5b/` | **500 fichiers .txt** à annoter — réponse au traitement |

## Prérequis serveur

- Serveur **sur le réseau Foch** (Linux recommandé ; Windows possible, voir encadrés)
- **Docker + Docker Compose** installés (`docker compose version` doit répondre)
- 8 Go de RAM recommandés, ~20 Go de disque
- Un port ouvert pour les annotateurs (8080 par défaut)
- `python3` avec le module `bcrypt` (uniquement pour l'étape 2 ; sinon utiliser
  l'alternative indiquée)

---

## Étape 1 — Copier ce dossier sur le serveur

Copier l'intégralité du dossier (par ex. dans `/opt/inception-partages/`) :

```bash
# depuis le poste : scp -r INCEPTION-DEPLOIEMENT-FOCH/ user@serveur:/opt/inception-partages/
cd /opt/inception-partages
chmod +x docker/*.sh          # rendre les scripts exécutables
```

## Étape 2 — Définir le mot de passe administrateur (AVANT le premier démarrage)

Le compte `admin` est créé automatiquement au premier démarrage, avec le mot de passe
défini (sous forme chiffrée bcrypt) dans `docker/settings.properties`.

1. Choisir un mot de passe fort et générer son hash :

   ```bash
   python3 -c "import bcrypt; print(bcrypt.hashpw(b'VOTRE_MOT_DE_PASSE', bcrypt.gensalt(rounds=10, prefix=b'2a')).decode())"
   ```

   *(Sans python3/bcrypt : `docker run --rm httpd:2.4-alpine htpasswd -bnBC 10 "" 'VOTRE_MOT_DE_PASSE' | tr -d ':\n'`)*

2. Dans `docker/settings.properties`, remplacer le hash existant de la ligne
   `security.default-admin-password=` en **conservant le préfixe `{bcrypt}`** :

   ```properties
   security.default-admin-password={bcrypt}$2a$10$........................
   ```

   ⚠️ Le hash livré dans ce dossier correspond au mot de passe du test local — il **doit**
   être remplacé.

## Étape 3 — Démarrer INCEpTION

```bash
cd docker
docker compose up -d
docker compose logs -f     # attendre « Started INCEpTION in ... seconds » (Ctrl-C pour quitter)
```

Vérifier : ouvrir `http://<serveur>:8080` → page de connexion INCEpTION.
Se connecter avec `admin` + le mot de passe choisi à l'étape 2.

## Étape 4 — Installer les 3 projets PARTAGES

Toujours depuis `docker/` :

```bash
cd docker
./provision.sh http://localhost:8080 admin 'VOTRE_MOT_DE_PASSE'
```

Le script importe les 3 projets pré-paramétrés. Résultat attendu : `✔ importé` pour CU1,
CU5a et CU5b, puis la liste des 3 projets (`EX_PARTAGES_CU1_…`, `EX_PARTAGES_CU5a_…`,
`EX_PARTAGES_CU5b_…`), visibles aussi sur la page d'accueil de l'interface web.
Le script est **relançable sans risque** : un projet déjà présent est ignoré (pas de
doublon).

## Étape 5 — Importer les documents à annoter

Les corpus sont dans les dossiers `CU1/`, `CU5a/`, `CU5b/` à la racine de ce dossier
(il faut récupérer les `.txt` du dossier nommé `CU1` pour le projet CU1, etc. —
le script fait cette correspondance automatiquement) :

```bash
./import-documents.sh http://localhost:8080 admin 'VOTRE_MOT_DE_PASSE'
```

Résultat attendu :

```
→ CU1  (projet 0) : 400 importés, 0 déjà présents, 0 erreurs, sur 400 fichiers
→ CU5a (projet 1) : 150 importés, 0 déjà présents, 0 erreurs, sur 150 fichiers
→ CU5b (projet 2) : 500 importés, 0 déjà présents, 0 erreurs, sur 500 fichiers
```

Le script est **relançable sans risque** (les documents déjà importés sont ignorés).

*Alternative manuelle (si l'API pose problème)* : dans l'interface, ouvrir le projet →
**Settings → Documents** → Format **Plain text (UTF-8)** → glisser-déposer les `.txt`
du dossier CU correspondant.

## Étape 6 — Créer les comptes des annotateurs

1. **Administration → Users** (menu haut droite, connecté en admin) : créer un compte
   par annotateur et par curateur (rôle global `ROLE_USER`).
2. Dans **chaque projet** : **Settings → Users** → ajouter les personnes avec le bon
   rôle :
   - *Annotator* : ceux qui annotent (CU5a/CU5b : médecins et/ou ARC oncologie) ;
   - *Curator* : le référent qui fusionnera/arbitrera les annotations ;
   - *Manager* : le responsable du paramétrage et du suivi.

## Étape 7 — Vérification finale

- Se connecter avec un compte annotateur → ouvrir un projet → l'onglet **Annotation**
  liste les documents → en ouvrir un → les couches PARTAGES sont proposées
  (ex. `EntiteAnonymisation` dans CU1).
- Page **Monitoring** (en manager) : les volumes correspondent (400 / 150 / 500).

## Étape 8 — Sécurisation post-installation

1. **Désactiver l'API distante** (qui n'a servi qu'à l'installation) : dans
   `docker/settings.properties`, passer `remote-api.enabled=false`, puis :

   ```bash
   docker compose restart
   ```

2. **Sauvegardes** : tout l'état (projets, comptes, **annotations**) est dans
   `docker/data/`. Pendant les campagnes d'annotation, sauvegarder **quotidiennement** :

   ```bash
   docker compose stop && cp -a data /sauvegardes/inception-$(date +%F) && docker compose start
   ```

3. Une fois l'import vérifié, restreindre l'accès aux dossiers `CU1/`, `CU5a/`, `CU5b/`
   de ce dossier réseau (les documents sont désormais dans INCEpTION).

---

## Dépannage

| Symptôme | Cause probable / correctif |
|---|---|
| `provision.sh` répond 401 | Mot de passe erroné, ou hash mal collé à l'étape 2 (le `{bcrypt}` doit être conservé). Le compte admin n'est créé qu'au **premier** démarrage : si l'étape 2 a été faite après coup, supprimer `docker/data/` (uniquement si l'instance est vierge !) et reprendre à l'étape 3 |
| `bash: ./provision.sh: Permission denied` | `chmod +x docker/*.sh` (étape 1) |
| Projets en double après une relance | Ne devrait pas arriver (scripts idempotents). Si des doublons existent, les supprimer via l'interface (Settings → Delete project) en gardant la 1re occurrence |
| `provision.sh` répond 302 | `remote-api.enabled=false` ou compte sans accès API → vérifier `settings.properties`, `docker compose restart` |
| Import projet : erreur de version | L'image doit être ≥ 38.5 (les templates viennent d'INCEpTION 38.5) — ne pas baisser le tag dans `docker-compose.yml` |
| Port 8080 déjà pris | Changer le mapping dans `docker-compose.yml` (ex. `"9090:8080"`) |
| Interface lente à plusieurs | Passer `JAVA_OPTS` à `-Xmx8g` dans `docker-compose.yml`, `docker compose up -d` |
| Accents illisibles dans un document | Vérifier que l'import a bien été fait en **Plain text (UTF-8)** |

## Contacts

- Questions données/corpus : DRCI Hôpital Foch (équipe data — expéditrice de ce dossier)
- Questions annotation PARTAGES : CU leads (cf. guide PARTAGES) avec
  partages-wp1@health-data-hub.fr en copie
- Documentation INCEpTION : https://inception-project.github.io/documentation/
