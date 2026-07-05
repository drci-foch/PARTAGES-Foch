#!/usr/bin/env bash
# Provisionnement INCEpTION — importe les 3 projets PARTAGES (CU1, CU5a, CU5b)
# via l'API distante AERO. À lancer une fois INCEpTION démarré.
#
# Usage : ./provision.sh [URL] [UTILISATEUR] [MOT_DE_PASSE]
#         ./provision.sh http://localhost:8080 admin 'motdepasse'
set -euo pipefail

URL="${1:-http://localhost:8080}"
USER="${2:-admin}"
PASS="${3:?Mot de passe requis : ./provision.sh URL UTILISATEUR MOT_DE_PASSE}"

HERE="$(cd "$(dirname "$0")" && pwd)"
MASTER_ZIP="$HERE/../Template INCEpTION - Tags et Label CU1, CU5a, CU5b.zip"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# INCEpTION renvoie HTTP 200 + une page « starting up » pendant tout son démarrage :
# on attend que l'API AERO réponde réellement du JSON avant d'importer, sinon les
# imports sont silencieusement perdus.
echo "→ Attente du démarrage complet d'INCEpTION..."
for i in $(seq 1 60); do
    BODY="$(curl -s -u "$USER:$PASS" "$URL/api/aero/v1/projects" || true)"
    case "$BODY" in
        '{'*) echo "   ✔ API prête"; break ;;
        *)    sleep 5 ;;
    esac
    if [ "$i" = "60" ]; then
        echo "   ✘ API toujours indisponible après 5 min — INCEpTION démarré ? identifiants corrects ?"
        exit 1
    fi
done

# Titre du projet PARTAGES par CU (pour détecter un import déjà réalisé)
title_for() {
    case "$1" in
        CU1)  echo "EX_PARTAGES_CU1" ;;
        CU5a) echo "EX_PARTAGES_CU5a" ;;
        CU5b) echo "EX_PARTAGES_CU5b" ;;
    esac
}

echo "→ Extraction des templates depuis : $MASTER_ZIP"
unzip -q "$MASTER_ZIP" -d "$TMP"

# Liste des projets déjà présents (idempotence : ne pas réimporter → pas de doublon)
EXISTING="$(curl -sf -u "$USER:$PASS" "$URL/api/aero/v1/projects" || echo '')"

for CU in CU1 CU5a CU5b; do
    if echo "$EXISTING" | grep -q "\"title\":\"$(title_for "$CU")"; then
        echo "→ $CU déjà présent — ignoré (relance sans doublon)"
        continue
    fi
    echo "→ Import du projet $CU ..."
    HTTP=$(curl -s -o "$TMP/resp_$CU.json" -w "%{http_code}" \
        -u "$USER:$PASS" \
        -F "file=@$TMP/$CU.zip" \
        "$URL/api/aero/v1/projects/import")
    if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then
        echo "   ✔ $CU importé"
    else
        echo "   ✘ $CU : HTTP $HTTP — $(cat "$TMP/resp_$CU.json")"
        echo "     (droits ROLE_REMOTE manquants ? remote-api.enabled=false ?)"
    fi
done

echo "→ Projets présents sur $URL :"
curl -s -u "$USER:$PASS" "$URL/api/aero/v1/projects"
echo
echo "Terminé. Pensez à désactiver remote-api.enabled si l'API n'est plus utile."
