# Kit de déploiement INCEpTION — Docker

Déploiement « clé en main » d'INCEpTION avec les 3 projets PARTAGES (CU1, CU5a, CU5b)
pré-importés. Testé de bout en bout le 05/07/2026 sur ce poste (Docker 28, image
officielle INCEpTION 38.5).

> **Pourquoi pas une image personnalisée « tout dedans » ?** Tout l'état d'INCEpTION
> (projets, comptes, annotations) vit dans le répertoire de données `./data` (volume),
> pas dans l'image. Une image figée perdrait les annotations à la suppression du
> conteneur, et embarquer des CR patient dans une image est un risque de gouvernance
> (une image se push/se copie). Ce kit utilise donc l'**image officielle** + un volume
> + un **script de provisionnement** qui importe les templates PARTAGES — même résultat,
> sans les pièges.

## Contenu

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | Image officielle `ghcr.io/inception-project/inception:38.5`, port 8080, volume `./data` |
| `settings.properties` | Config : pas d'auto-inscription, API distante activée, **admin auto-créé au 1er démarrage** |
| `provision.sh` / `provision.ps1` | Import automatique des 3 projets PARTAGES via l'API AERO |
| `import-documents.sh` / `.ps1` | Import automatique des corpus `.txt` (dossiers `../CU1`, `../CU5a`, `../CU5b`) — relançable (409 = déjà présent) |
| `README-MISE-EN-PROD.md` | Guide pas à pas pour l'admin prod (copié en `README.md` à la racine du paquet de livraison) |

**Paquet de livraison** : `..\make_livraison.ps1` assemble le dossier complet à copier sur
le réseau Foch (kit + templates + corpus CU1/CU5a/CU5b + guide) — par défaut dans
`C:\Users\benysar\Documents\INCEPTION-DEPLOIEMENT-FOCH`.

⚠️ La version de l'image doit rester **≥ 38.5** : les templates PARTAGES ont été exportés
avec INCEpTION 38.5 et ne s'importent pas dans une version antérieure.

## Déploiement sur un serveur (Linux, Docker + compose installés)

```bash
# 1. Copier le dossier inception/ du repo sur le serveur (docker/ + le zip des templates)

# 2. AVANT le premier démarrage : remplacer le hash du mot de passe admin
#    dans settings.properties (clé security.default-admin-password) :
python3 -c "import bcrypt; print(bcrypt.hashpw(b'VOTRE_MOT_DE_PASSE', bcrypt.gensalt(rounds=10, prefix=b'2a')).decode())"
#    → coller le résultat après {bcrypt} (conserver le préfixe {bcrypt})

# 3. Démarrer
cd inception/docker
docker compose up -d

# 4. Importer les 3 projets PARTAGES (une seule fois)
./provision.sh http://localhost:8080 admin 'VOTRE_MOT_DE_PASSE'

# 5. Vérifier : http://<serveur>:8080 → connexion admin → les 3 projets sont là
```

Ensuite, dans l'interface web (voir `../README.md` §3 à §6) :
1. créer les comptes annotateurs/curateurs (Administration → Users) ;
2. dans chaque projet : Settings → Users (rôles) et Settings → Documents (import des `.txt`) ;
3. une fois le provisionnement terminé, passer `remote-api.enabled=false` dans
   `settings.properties` puis `docker compose restart` (l'API n'est plus nécessaire).

## Points d'attention

- **`./data` = toutes les données** (base, documents patient, annotations) :
  - jamais dans git (déjà exclu par `.gitignore`) ;
  - **sauvegarde quotidienne** pendant les campagnes : `docker compose stop`,
    copie de `./data`, `docker compose start` (ou snapshot à chaud si outillage) ;
  - serveur sur le **réseau Foch uniquement**, jamais exposé sur internet.
- La base embarquée (HSQLDB) convient pour une équipe d'annotation de taille
  raisonnable ; INCEpTION affiche un avertissement « not recommended for production » —
  pour un usage intensif multi-projets, brancher MariaDB (voir doc admin INCEpTION,
  section Database).
- Mémoire : `JAVA_OPTS=-Xmx4g` dans le compose ; passer à `-Xmx8g` si beaucoup
  d'annotateurs simultanés.
- Windows/PowerShell : utiliser `provision.ps1` (les `.ps1` du kit sont volontairement
  sans accents — PowerShell 5.1 lit mal l'UTF-8 sans BOM).

## Test local réalisé (05/07/2026)

- `docker compose up -d` → interface accessible en ~10 s sur http://localhost:8080
- Admin auto-créé via `security.default-admin-*` (vérifié : API 200)
- `provision.ps1` → les 3 projets importés :
  `EX_PARTAGES_CU1_Pseudonymisation`, `EX_PARTAGES_CU5a_Identification_De_Biomarqueurs`,
  `EX_PARTAGES_CU5b_Reponse_Au_Traitement_Oncologie`
