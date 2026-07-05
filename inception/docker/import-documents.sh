#!/usr/bin/env bash
# Import des documents .txt dans les 3 projets PARTAGES via l'API AERO.
#
# Attend, à côté du dossier docker/, les dossiers de corpus :
#   ../CU1/*.txt   -> projet titre contenant "CU1"
#   ../CU5a/*.txt  -> projet titre contenant "CU5a"
#   ../CU5b/*.txt  -> projet titre contenant "CU5b"
#
# Usage : ./import-documents.sh [URL] [UTILISATEUR] [MOT_DE_PASSE]
#         ./import-documents.sh http://localhost:8080 admin 'motdepasse'
#
# Relançable : les documents déjà présents dans le projet sont ignorés (on lit
# la liste des documents du projet avant d'importer — l'API renvoie une erreur,
# pas un code dédié, quand un document du même nom existe déjà).
set -euo pipefail

URL="${1:-http://localhost:8080}"
USER="${2:-admin}"
PASS="${3:?Mot de passe requis : ./import-documents.sh URL UTILISATEUR MOT_DE_PASSE}"

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_JSON=$(curl -sf -u "$USER:$PASS" "$URL/api/aero/v1/projects")

get_project_id() {  # $1 = motif du titre (CU1, CU5a, CU5b)
    echo "$PROJECTS_JSON" | tr '}' '\n' | grep "\"title\":\"[^\"]*$1" \
        | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2
}

for CU in CU1 CU5a CU5b; do
    DIR="$HERE/../$CU"
    # Titres des projets : EX_PARTAGES_CU1_..., EX_PARTAGES_CU5a_..., EX_PARTAGES_CU5b_...
    # On cible "_CU1", "_CU5a", "_CU5b" pour éviter que "CU1" matche aussi "CU1x".
    PID="$(get_project_id "_${CU}" || true)"
    if [ -z "${PID:-}" ]; then
        echo "✘ $CU : projet introuvable sur $URL — lancez d'abord provision.sh"
        continue
    fi
    if [ ! -d "$DIR" ]; then
        echo "✘ $CU : dossier de corpus absent : $DIR"
        continue
    fi

    # Documents déjà présents dans le projet (pour l'idempotence)
    EXISTING_DOCS=$(curl -sf -u "$USER:$PASS" \
        "$URL/api/aero/v1/projects/$PID/documents" | tr ',' '\n' \
        | grep -o '"name":"[^"]*"' | cut -d'"' -f4 || true)

    TOTAL=0; OK=0; SKIP=0; ERR=0
    for F in "$DIR"/*.txt; do
        [ -e "$F" ] || continue
        TOTAL=$((TOTAL + 1))
        NAME="$(basename "$F")"
        if echo "$EXISTING_DOCS" | grep -qxF "$NAME"; then
            SKIP=$((SKIP + 1))
            continue
        fi
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" -u "$USER:$PASS" \
            -F "content=@$F" -F "name=$NAME" -F "format=text" \
            "$URL/api/aero/v1/projects/$PID/documents")
        case "$HTTP" in
            200|201) OK=$((OK + 1)) ;;
            *)       ERR=$((ERR + 1)); echo "   ✘ $NAME : HTTP $HTTP" ;;
        esac
    done
    echo "→ $CU (projet $PID) : $OK importés, $SKIP déjà présents, $ERR erreurs, sur $TOTAL fichiers"
done

echo "Terminé. Vérifiez les volumes dans l'interface (Settings → Documents de chaque projet)."
