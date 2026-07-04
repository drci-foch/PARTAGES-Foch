"""
Découpage corps / conclusion d'un CR médical (CU3).

Le guide PARTAGES (v29.01.26, §6.3 + FAQ #10) attend, pour chaque CR, deux
fichiers .txt : le corps du texte SANS la conclusion, et la conclusion seule.
La détection repose sur des « balises ancres » en début de ligne (approche
validée par la FAQ #10 du guide : liste d'expressions types + regexp).

Règles de détection (insensibles à la casse et aux accents) :
  - la balise doit être en DÉBUT de ligne ;
  - formes acceptées :
      « CONCLUSION »                       (titre seul, ± « : » / « . »)
      « Conclusion : texte... »            (contenu sur la même ligne)
      « Au total, texte... »               (prose introduite par la balise)
      « CONCLUSION DE L'EXAMEN : »         (titre étendu se terminant par « : »)
  - si plusieurs balises matchent, on retient la PREMIÈRE occurrence dont le
    découpage passe les garde-fous (le ratio conclusion/document écarte
    naturellement les balises trop précoces) ;
  - un document dont le corps final contient encore une balise titre est
    REJETÉ (`anchor_in_body`) : la vraie conclusion risque d'être restée
    dans le corps (fuite pour la tâche de résumé).

Le split est validé sur les caractères UTILES de la conclusion : les lignes
de pied de page (IPP, « née le », pagination « x / y ») ne comptent pas —
une « conclusion » réduite à un pied de page identifiant est rejetée.

Le module fournit aussi `strip_rgpd_boilerplate()` qui retire la mention
d'information RGPD/EDS Foch (« Vous êtes suivi(e) à l'Hôpital Foch... »)
présente en fin de certains documents.
"""

import re
import unicodedata
from typing import Optional

# Balises ancres par défaut (guide CU3 + FAQ #10). L'ordre importe :
# les plus longues d'abord pour éviter qu'un préfixe court capte le match.
DEFAULT_ANCHORS = [
    "EN CONCLUSION",
    "CONCLUSIONS",
    "CONCLUSION",
    "AU TOTAL",
    "EN SYNTHESE",
    "SYNTHESE",
    "EN RESUME",
]

# Ponctuation acceptée juste après la balise (contenu sur la même ligne)
_PUNCT_AFTER = ":,.-–—"

# Longueur max (chars normalisés) d'un titre étendu type « CONCLUSION DE L'EXAMEN : »
_MAX_EXTENDED_HEADER = 60


def normalize(text: str) -> str:
    """Majuscules sans accents, longueur STRICTEMENT conservée (mapping 1:1)."""
    return "".join(unicodedata.normalize("NFD", ch)[0].upper() for ch in text)


def _nonblank_len(text: str) -> int:
    return len("".join(text.split()))


# Lignes de pied de page (sur texte normalisé) : identifiants patient, pagination.
# Elles ne comptent pas dans les caractères UTILES d'une conclusion.
_FOOTER_RE = re.compile(r"\bIPP ?\d{6,}|\bNEE? LE \d{2}/\d{2}/\d{4}|\b\d+ / \d+\s*$")


def _useful_len(text: str) -> int:
    """Caractères non blancs des lignes qui ne sont PAS des pieds de page."""
    keep = [l for l in text.splitlines() if l.strip() and not _FOOTER_RE.search(normalize(l))]
    return _nonblank_len("".join(keep))


# Mention d'information RGPD/EDS Foch, insérée en fin de document
# (« Vous êtes suivi(e) à l'Hôpital Foch, établissement de santé... »).
_BOILER_MARKER = "VOUS ETES SUIVI"


def strip_rgpd_boilerplate(text: str, max_tail_chars: int = 3000) -> str:
    """Retire la mention RGPD/EDS Foch et tout ce qui la suit (fin de document).

    Garde-fou : si le bloc à retirer dépasse `max_tail_chars` caractères non
    blancs, on ne retire rien (du contenu clinique suivrait la mention — cas
    non observé, mais on reste prudent).
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _BOILER_MARKER in normalize(line):
            tail = "\n".join(lines[i:])
            if _nonblank_len(tail) <= max_tail_chars:
                return "\n".join(lines[:i]).rstrip()
            return text
    return text


def _match_line(line: str, anchors: list) -> Optional[tuple]:
    """Teste si `line` est une ligne d'ancre de conclusion.

    Retourne (anchor, same_line_content) ou None.
    `same_line_content` = texte de conclusion présent sur la ligne de la balise
    (vide si la balise est un simple titre).
    """
    norm = normalize(line)
    lstart = len(line) - len(line.lstrip())

    for anchor in anchors:
        if not norm[lstart:].startswith(anchor):
            continue
        after = lstart + len(anchor)
        rest_norm = norm[after:].strip()
        rest_orig = line[after:]

        # 1. Titre seul : « CONCLUSION » / « CONCLUSION : » / « CONCLUSION. »
        if rest_norm == "" or rest_norm in (":", ".", " :"):
            return anchor, ""

        # 2. Contenu sur la même ligne : « Conclusion : texte » / « Au total, texte »
        if rest_norm[0] in _PUNCT_AFTER:
            content = rest_orig.lstrip().lstrip(_PUNCT_AFTER).lstrip()
            return anchor, content

        # 3. Titre étendu : « CONCLUSION DE L'EXAMEN : » (court, finit par « : »)
        if rest_norm.endswith(":") and len(rest_norm) <= _MAX_EXTENDED_HEADER:
            return anchor, ""

    return None


def split_conclusion(
    text: str,
    anchors: list = None,
    min_conclusion_chars: int = 40,
    min_body_chars: int = 300,
    max_conclusion_ratio: float = 0.6,
) -> dict:
    """Découpe un CR en (corps, conclusion).

    Retourne un dict :
      {"ok": True, "body": ..., "conclusion": ..., "anchor": ...}   si succès
      {"ok": False, "reason": ...}                                  sinon

    Stratégie : on essaie chaque balise dans l'ordre du document et on retient
    la PREMIÈRE dont le découpage passe tous les garde-fous. Les balises trop
    précoces échouent sur le ratio (`conclusion_too_large`), les sections vides
    sur la longueur utile (`conclusion_too_short`).

    Raisons d'échec : no_anchor, conclusion_too_short, body_too_short,
    conclusion_too_large, anchor_in_body (une balise titre subsiste dans le
    corps → la vraie conclusion risque d'y être restée : fuite pour le résumé).
    """
    anchors = anchors or DEFAULT_ANCHORS
    lines = text.splitlines()

    matches = []
    for i, line in enumerate(lines):
        m = _match_line(line, anchors)
        if m:
            matches.append((i, m[0], m[1]))

    if not matches:
        return {"ok": False, "reason": "no_anchor"}

    last_reason = "no_anchor"
    for match_idx, match_anchor, same_line in matches:
        # Le corps ne doit pas se terminer par une balise résiduelle (documents
        # à balises consécutives, ex. « CONCLUSION » puis « AU TOTAL : ... ») :
        # on retire les lignes vides et les lignes titres d'ancre en fin de corps.
        body_lines = lines[:match_idx]
        while body_lines:
            last = body_lines[-1]
            if not last.strip():
                body_lines.pop()
                continue
            m = _match_line(last, anchors)
            if m and m[1] == "":
                body_lines.pop()
                continue
            break

        body = "\n".join(body_lines).strip()
        tail = "\n".join(lines[match_idx + 1:]).strip()
        conclusion = (same_line + "\n" + tail).strip() if same_line else tail

        n_conc = _nonblank_len(conclusion)
        n_body = _nonblank_len(body)

        if _useful_len(conclusion) < min_conclusion_chars:
            last_reason = "conclusion_too_short"
            continue
        if n_body < min_body_chars:
            last_reason = "body_too_short"
            continue
        if n_conc > max_conclusion_ratio * (n_conc + n_body):
            last_reason = "conclusion_too_large"
            continue

        # Fuite : une balise titre encore présente dans le corps signifie
        # qu'une section conclusion antérieure (écartée par les garde-fous)
        # reste dans le corps → document ambigu, rejeté.
        if any((m := _match_line(l, anchors)) and m[1] == "" for l in body_lines):
            last_reason = "anchor_in_body"
            continue

        return {"ok": True, "body": body, "conclusion": conclusion, "anchor": match_anchor}

    return {"ok": False, "reason": last_reason}
