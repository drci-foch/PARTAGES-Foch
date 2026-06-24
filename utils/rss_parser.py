"""
Parser pour fichiers RSS (Résumé de Sortie Standardisé) PMSI
Adapté de cim10-mapper pour le projet PARTAGES — Hôpital Foch
Format RSS groupé 120 - Conforme aux spécifications ATIH 2020
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from collections import Counter

import pandas as pd


# ============================================================================
# STRUCTURES DE DONNÉES
# ============================================================================


@dataclass
class ActeCCAM:
    """Représente un acte CCAM selon le format 120 (29 caractères par acte)"""

    date_realisation: str
    code_ccam: str
    extension_pmsi: str
    phase: str
    activite: str
    extension_documentaire: str
    modificateurs: str
    remboursement_exceptionnel: str
    association_non_prevue: str
    nombre_realisations: int


@dataclass
class SejourRSS:
    """Représente un RUM/RSS selon le format groupé 120 (2020)"""

    # Identifiants
    finess: str
    numero_rss: str
    numero_admin_sejour: str
    numero_rum: str

    # Patient
    date_naissance: str
    sexe: str

    # Séjour
    numero_um: str
    date_entree_um: str
    date_sortie_um: str
    mode_entree: str
    mode_sortie: str

    # Groupage
    ghm: str

    # Diagnostics
    diagnostic_principal: str
    diagnostic_relie: str
    diagnostics_associes: List[str] = field(default_factory=list)

    # Actes
    actes: List[ActeCCAM] = field(default_factory=list)


# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================


def safe_int(value: str, default: int = 0) -> int:
    try:
        v = value.strip()
        if v == "" or v == " " * len(v):
            return default
        return int(v)
    except (ValueError, AttributeError):
        return default


def format_date_iso(date_str: str) -> str:
    """Formate une date JJMMAAAA en AAAA-MM-JJ (format ISO)"""
    date_str = date_str.strip()
    if len(date_str) == 8 and date_str.replace(" ", "0").isdigit():
        if date_str.strip() and date_str not in ("00000000", "        "):
            return f"{date_str[4:8]}-{date_str[2:4]}-{date_str[0:2]}"
    return date_str


def format_sexe(code: str) -> str:
    mapping = {"1": "M", "2": "F", "M": "M", "F": "F"}
    return mapping.get(code.strip(), code.strip())


def duree_sejour(sejour: SejourRSS) -> int:
    """Calcule la durée du séjour en jours (0 = ambulatoire)."""
    try:
        from datetime import date
        d_entree = date(
            int(sejour.date_entree_um[4:8]),
            int(sejour.date_entree_um[2:4]),
            int(sejour.date_entree_um[0:2]),
        )
        d_sortie = date(
            int(sejour.date_sortie_um[4:8]),
            int(sejour.date_sortie_um[2:4]),
            int(sejour.date_sortie_um[0:2]),
        )
        return (d_sortie - d_entree).days
    except Exception:
        return -1


# ============================================================================
# PARSING
# ============================================================================


def _parse_acte_ccam(zone_acte: str) -> Optional[ActeCCAM]:
    """Parse une zone acte de 29 caractères selon le format 120."""
    if len(zone_acte) < 29:
        return None
    code = zone_acte[8:15].strip()
    if not code:
        return None
    try:
        return ActeCCAM(
            date_realisation=zone_acte[0:8].strip(),
            code_ccam=code,
            extension_pmsi=zone_acte[15:18].strip(),
            phase=zone_acte[18:19].strip(),
            activite=zone_acte[19:20].strip(),
            extension_documentaire=zone_acte[20:21].strip(),
            modificateurs=zone_acte[21:25].strip(),
            remboursement_exceptionnel=zone_acte[25:26].strip(),
            association_non_prevue=zone_acte[26:27].strip(),
            nombre_realisations=safe_int(zone_acte[27:29], 1),
        )
    except Exception:
        return None


def parse_ligne_rss(ligne: str) -> Optional[SejourRSS]:
    """
    Parse une ligne RSS selon le format groupé 120 (2020).
    Partie fixe : 192 caractères + partie variable.
    """
    if len(ligne) < 192:
        return None
    try:
        finess = ligne[15:24].strip()
        numero_rss = ligne[27:47].strip()
        numero_admin_sejour = ligne[47:67].strip()
        numero_rum = ligne[67:77].strip()

        date_naissance = ligne[77:85].strip()
        sexe = ligne[85:86].strip()

        numero_um = ligne[86:90].strip()
        date_entree_um = ligne[92:100].strip()
        mode_entree = ligne[100:101].strip()
        date_sortie_um = ligne[102:110].strip()
        mode_sortie = ligne[110:111].strip()

        ghm = ligne[2:8].strip()

        nb_da = safe_int(ligne[133:135])
        nb_dad = safe_int(ligne[135:137])
        nb_actes = safe_int(ligne[137:140])

        diagnostic_principal = ligne[140:148].strip()
        diagnostic_relie = ligne[148:156].strip()

        pos = 192

        diagnostics_associes = []
        for _ in range(nb_da):
            if pos + 8 <= len(ligne):
                da = ligne[pos: pos + 8].strip()
                if da:
                    diagnostics_associes.append(da)
                pos += 8

        pos += nb_dad * 8

        actes = []
        for _ in range(nb_actes):
            if pos + 29 <= len(ligne):
                acte = _parse_acte_ccam(ligne[pos: pos + 29])
                if acte:
                    actes.append(acte)
                pos += 29

        return SejourRSS(
            finess=finess,
            numero_rss=numero_rss,
            numero_admin_sejour=numero_admin_sejour,
            numero_rum=numero_rum,
            date_naissance=date_naissance,
            sexe=sexe,
            numero_um=numero_um,
            date_entree_um=date_entree_um,
            date_sortie_um=date_sortie_um,
            mode_entree=mode_entree,
            mode_sortie=mode_sortie,
            ghm=ghm,
            diagnostic_principal=diagnostic_principal,
            diagnostic_relie=diagnostic_relie,
            diagnostics_associes=diagnostics_associes,
            actes=actes,
        )
    except Exception:
        return None


# ============================================================================
# CLASSE PRINCIPALE
# ============================================================================


class RSSParser:
    """
    Parser pour fichiers RSS PMSI.
    Usage minimal :
        parser = RSSParser()
        sejours = parser.parse_years([2023, 2024, 2025])
        df = parser.to_dataframe(sejours)
    """

    MONTH_NAMES = {
        1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
        5: "Mai", 6: "Juin", 7: "Juillet", 8: "Aout",
        9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
    }

    def __init__(self, base_path: str = r"S:\Envoi-EDS-PMSI"):
        self.base_path = Path(base_path)
        self.sejours: List[SejourRSS] = []

    # ------------------------------------------------------------------
    # Découverte des fichiers
    # ------------------------------------------------------------------

    def find_rss_files(self, year: int, month: Optional[int] = None) -> List[Path]:
        """Trouve les fichiers RSS pour une année (et optionnellement un mois)."""
        rss_files = []
        year_path = self.base_path / str(year)

        if not year_path.exists():
            print(f"⚠️ Dossier année non trouvé : {year_path}")
            return rss_files

        months_to_search = [month] if month else range(1, 13)

        for m in months_to_search:
            month_name = self.MONTH_NAMES.get(m, "")
            month_path = year_path / f"{m:02d} {month_name} {year}"
            if month_path.exists():
                for pat in ("RSS*.txt", "RSS*.TXT"):
                    rss_files.extend(month_path.glob(pat))
                pmsi_pilot = month_path / "PMSIPilot"
                if pmsi_pilot.exists():
                    for pat in ("RSS*.txt", "RSS*.TXT"):
                        rss_files.extend(pmsi_pilot.glob(pat))

        # Déduplication : sur un système de fichiers insensible à la casse (Windows),
        # les motifs *.txt et *.TXT renvoient les mêmes fichiers → on évite de parser 2×.
        seen = set()
        unique_files = []
        for f in rss_files:
            key = str(f.resolve()).lower()
            if key not in seen:
                seen.add(key)
                unique_files.append(f)

        unique_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return unique_files

    def parse_years(self, years: List[int]) -> List[SejourRSS]:
        """Parse tous les fichiers RSS pour une liste d'années."""
        all_sejours: List[SejourRSS] = []
        for year in years:
            files = self.find_rss_files(year)
            if not files:
                print(f"⚠️ Aucun fichier RSS pour {year}")
                continue
            print(f"📅 {year} — {len(files)} fichier(s) RSS")
            for f in files:
                sejours = self.parse_file(f)
                all_sejours.extend(sejours)
                print(f"   {f.name} → {len(sejours)} séjours")
        self.sejours = all_sejours
        return all_sejours

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_file(self, filepath: Path) -> List[SejourRSS]:
        """Parse un fichier RSS et retourne la liste des séjours."""
        sejours = []
        lignes_ignorees = 0
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(filepath, "r", encoding=encoding, errors="ignore") as fh:
                    for ligne in fh:
                        ligne = ligne.rstrip("\n\r")
                        if len(ligne) >= 192:
                            s = parse_ligne_rss(ligne)
                            if s:
                                sejours.append(s)
                            else:
                                lignes_ignorees += 1
                        elif len(ligne) > 0:
                            lignes_ignorees += 1
                break
            except UnicodeDecodeError:
                continue
        if lignes_ignorees:
            print(f"   ⚠️ {lignes_ignorees} ligne(s) ignorée(s) dans {filepath.name}")
        return sejours

    # ------------------------------------------------------------------
    # Conversion DataFrame
    # ------------------------------------------------------------------

    def to_dataframe(self, sejours: Optional[List[SejourRSS]] = None) -> pd.DataFrame:
        """Convertit les séjours en DataFrame."""
        if sejours is None:
            sejours = self.sejours
        rows = []
        for s in sejours:
            rows.append({
                "finess": s.finess,
                "numero_rss": s.numero_rss,
                "numero_admin": s.numero_admin_sejour,
                "numero_rum": s.numero_rum,
                "date_naissance": s.date_naissance,
                "sexe": format_sexe(s.sexe),
                "numero_um": s.numero_um,
                "date_entree_iso": format_date_iso(s.date_entree_um),
                "date_sortie_iso": format_date_iso(s.date_sortie_um),
                "mode_entree": s.mode_entree,
                "mode_sortie": s.mode_sortie,
                "ghm": s.ghm,
                "dp": s.diagnostic_principal,
                "dr": s.diagnostic_relie,
                "nb_da": len(s.diagnostics_associes),
                "nb_actes": len(s.actes),
                "codes_ccam": " ".join(a.code_ccam for a in s.actes),
                "duree_sejour": duree_sejour(s),
            })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Statistiques
    # ------------------------------------------------------------------

    def get_statistics(self, sejours: Optional[List[SejourRSS]] = None) -> Dict:
        if sejours is None:
            sejours = self.sejours
        if not sejours:
            return {}
        dp_counter = Counter(s.diagnostic_principal for s in sejours if s.diagnostic_principal)
        ghm_counter = Counter(s.ghm for s in sejours)
        return {
            "total_sejours": len(sejours),
            "unique_sejours": len({s.numero_admin_sejour for s in sejours}),
            "unique_dp": len(dp_counter),
            "unique_ghm": len(ghm_counter),
            "top_10_dp": dp_counter.most_common(10),
            "top_10_ghm": ghm_counter.most_common(10),
        }
