"""
Étape 2/2 — Extraction CU2 - Codage CIM-10 depuis CRH
Hôpital Foch / Projet PARTAGES

Critères (guide PARTAGES v29.01.26) :
  - Séjours ambulatoires 2023-2025
  - 1 000 séjours (tirage aléatoire)
  - Source : RSS + CRH/CRO depuis Easily
  - Format sortie : CSV (5 colonnes : ID, Spécialité, Texte, Codes CCAM, CIM-10 DP)
  - Fichier stats : cu2_stats.csv

NOTE : Lancez d'abord python WP2_CU2/fetch_rss.py pour générer pool_rss.csv.
"""

import os
import subprocess
import sys
import hashlib
import tempfile
from pathlib import Path

import pyodbc
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU2Config, DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# 1. CHARGEMENT DU POOL RSS
# ---------------------------------------------------------------------------


def load_pool(config: CU2Config) -> pd.DataFrame:
    if not config.paths.pool_rss_path.exists():
        raise FileNotFoundError(
            f"Pool introuvable : {config.paths.pool_rss_path}\n"
            "→ Lancez d'abord : python WP2_CU2/fetch_rss.py"
        )
    # sep=None + engine="python" : pandas détecte automatiquement "," ou ";"
    df = pd.read_csv(
        config.paths.pool_rss_path, sep=None, engine="python",
        encoding="utf-8-sig", dtype=str,
    )
    # Vérification : la colonne clé doit exister
    if "numero_admin" not in df.columns:
        raise ValueError(
            f"Colonne 'numero_admin' absente de {config.paths.pool_rss_path}.\n"
            "→ Régénérez le pool : python WP2_CU2/fetch_rss.py"
        )
    # Filtre GHM (liste blanche) : appliqué aussi ici pour couvrir un pool
    # généré avant réception du référentiel GHM.
    whitelist = set(config.extraction.ghm_whitelist)
    if whitelist and "ghm" in df.columns:
        before = len(df)
        df = df[df["ghm"].fillna("").str.strip().isin(whitelist)].copy()
        if len(df) < before:
            print(
                f"   → Filtre GHM ({len(whitelist)} GHM) : "
                f"{len(df):,} séjours retenus sur {before:,}"
            )
    return df


# ---------------------------------------------------------------------------
# 2. ANONYMISATION
# ---------------------------------------------------------------------------


def hash_sejour_id(numero_admin: str) -> str:
    """Identifiant anonymisé du séjour (SHA-256, 16 hex chars)."""
    return hashlib.sha256(numero_admin.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 3. SPÉCIALITÉ DEPUIS GHM
# ---------------------------------------------------------------------------


def get_specialite(ghm: str, exact_mapping: dict, prefix_mapping: dict) -> str:
    """Retourne la spécialité médicale d'un GHM.

    Priorité au mapping exact du référentiel PARTAGES (GHM → spécialité),
    repli sur le préfixe CMD (2 premiers caractères) sinon.
    """
    ghm = (ghm or "").strip()
    if len(ghm) < 2:
        return "Inconnu"
    if ghm in exact_mapping:
        return exact_mapping[ghm]
    return prefix_mapping.get(ghm[:2], f"GHM_{ghm[:2]}")


# ---------------------------------------------------------------------------
# 4. EXTRACTION TEXTE PDF (via Java jar)
# ---------------------------------------------------------------------------

_MIN_TEXT_CHARS = 100


def extract_text_from_pdf(pdf_bytes: bytes, java_path: str, jar_path: str) -> str:
    """
    Extrait le texte d'un PDF binaire via le jar pdftotext.
    Le jar reçoit le chemin du PDF et écrit un .txt dans le répertoire courant.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf.write(pdf_bytes)
        tmp_pdf_path = tmp_pdf.name

    txt_path = Path(tmp_pdf_path).with_suffix(".txt")
    try:
        subprocess.run(
            [java_path, "-jar", jar_path, tmp_pdf_path],
            capture_output=True,
            timeout=60,
        )
        # Le jar peut écrire le .txt soit à côté du PDF, soit dans le CWD
        cwd_txt = Path(os.path.splitext(os.path.basename(tmp_pdf_path))[0] + ".txt")
        found_txt = (
            txt_path if txt_path.exists() else (cwd_txt if cwd_txt.exists() else None)
        )
        if found_txt is None:
            return ""
        # Le jar produit du cp1252 sur Windows — on essaie dans l'ordre
        for enc in ("cp1252", "latin-1", "utf-8"):
            try:
                text = found_txt.read_text(encoding=enc).strip()
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = found_txt.read_text(encoding="utf-8", errors="replace").strip()
        if found_txt == cwd_txt:
            cwd_txt.unlink(missing_ok=True)
        return text
    except (subprocess.TimeoutExpired, Exception):
        return ""
    finally:
        Path(tmp_pdf_path).unlink(missing_ok=True)
        txt_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 5. REQUÊTE SQL — DOCUMENTS PAR VEN_NUMERO (stratégie 1)
# ---------------------------------------------------------------------------


def _cursor_to_df(cursor) -> pd.DataFrame:
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)


def _build_doc_query_by_venue(patterns: list) -> str:
    pattern_clauses = " OR ".join(f"d.doc_nom LIKE '{p}'" for p in patterns)
    return f"""
    SELECT
        p.pat_ipp,
        d.doc_id,
        d.doc_nom,
        d.doc_stockage_id,
        d.doc_realisation_date
    FROM METADONE.metadone.DOCUMENTS d
    INNER JOIN NOYAU.patient.PATIENT p ON d.doc_pat_id = p.pat_id
    INNER JOIN NOYAU.patient.VENUE v ON d.doc_venue_id = v.ven_id
    WHERE v.ven_numero = ?
      AND ({pattern_clauses})
      AND d.doc_supprime != 'true'
    ORDER BY d.doc_realisation_date DESC
    """


def _build_doc_query_by_ipp_dates(patterns: list, tolerance: int) -> str:
    pattern_clauses = " OR ".join(f"d.doc_nom LIKE '{p}'" for p in patterns)
    return f"""
    SELECT
        p.pat_ipp,
        d.doc_id,
        d.doc_nom,
        d.doc_stockage_id,
        d.doc_realisation_date
    FROM METADONE.metadone.DOCUMENTS d
    INNER JOIN NOYAU.patient.PATIENT p ON d.doc_pat_id = p.pat_id
    WHERE p.pat_ipp = ?
      AND ({pattern_clauses})
      AND d.doc_realisation_date >= DATEADD(day, -{tolerance}, ?)
      AND d.doc_realisation_date <= DATEADD(day, {tolerance}, ?)
      AND d.doc_supprime != 'true'
    ORDER BY d.doc_realisation_date DESC
    """


_IPP_VENUE_QUERY = """
SELECT DISTINCT p.pat_ipp
FROM NOYAU.patient.VENUE v
INNER JOIN NOYAU.patient.PATIENT p ON v.pat_id = p.pat_id
WHERE v.ven_numero = ?
"""


# ---------------------------------------------------------------------------
# 6. LIAISON SÉJOUR → DOCUMENTS
# ---------------------------------------------------------------------------


def find_docs_for_sejour(
    cursor,
    numero_admin: str,
    date_entree: str,
    date_sortie: str,
    all_patterns: list,
    tolerance: int,
) -> tuple[pd.DataFrame, str]:
    """
    Cherche les documents CRH/CRO pour un séjour.
    Stratégie 1 : via ven_numero.
    Stratégie 2 : via IPP + dates.
    Retourne (DataFrame, méthode).
    """
    # Stratégie 1 : ven_numero
    try:
        q = _build_doc_query_by_venue(all_patterns)
        cursor.execute(q, (numero_admin,))
        df = _cursor_to_df(cursor)
        if not df.empty:
            return df, "venue"
    except Exception:
        pass

    # Récupérer IPP depuis VENUE
    ipp = None
    try:
        cursor.execute(_IPP_VENUE_QUERY, (numero_admin,))
        row = cursor.fetchone()
        ipp = row[0] if row else None
    except Exception:
        pass

    # Stratégie 2 : IPP + dates
    if ipp and date_entree and date_sortie:
        try:
            q = _build_doc_query_by_ipp_dates(all_patterns, tolerance)
            cursor.execute(q, (ipp, date_entree, date_sortie))
            df = _cursor_to_df(cursor)
            if not df.empty:
                return df, "ipp_dates"
        except Exception:
            pass

    return pd.DataFrame(), "not_found"


# ---------------------------------------------------------------------------
# 7. TÉLÉCHARGEMENT BINAIRE
# ---------------------------------------------------------------------------


def fetch_file_bytes(cursor, doc_stockage_id: str) -> bytes | None:
    try:
        cursor.execute(
            "SELECT fil_data FROM STOCKAGE.stockage.FILES WHERE fil_id = ?",
            (doc_stockage_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            b = bytes(row[0]) if not isinstance(row[0], bytes) else row[0]
            return b if b[:4] == b"%PDF" else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 8. PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

_OUTPUT_COLUMNS = ["ID", "Spécialité", "Texte", "Codes CCAM", "CIM-10 DP"]


def _load_already_done(output_path: Path) -> set[str]:
    """Retourne l'ensemble des ID déjà présents dans le CSV de sortie."""
    if not output_path.exists():
        return set()
    try:
        df = pd.read_csv(
            output_path, sep=";", encoding="utf-8-sig", usecols=["ID"], dtype=str
        )
        return set(df["ID"].dropna().tolist())
    except Exception:
        return set()


def _append_row(output_path: Path, row: dict):
    """Ajoute une ligne au CSV de sortie (crée le fichier avec header si besoin)."""
    write_header = not output_path.exists()
    pd.DataFrame([row], columns=_OUTPUT_COLUMNS).to_csv(
        output_path,
        sep=";",
        mode="a",
        index=False,
        header=write_header,
        encoding="utf-8-sig",
    )


_CORR_COLUMNS = ["ID", "numero_admin"]


def _append_correspondence(corr_path: Path, sejour_id: str, numero_admin: str):
    """Ajoute une ligne à la table de correspondance interne (usage interne uniquement)."""
    write_header = not corr_path.exists()
    pd.DataFrame(
        [{"ID": sejour_id, "numero_admin": numero_admin}],
        columns=_CORR_COLUMNS,
    ).to_csv(
        corr_path,
        sep=";",
        mode="a",
        index=False,
        header=write_header,
        encoding="utf-8-sig",
    )


def run_extraction(config: CU2Config = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.ensure_dirs()

    # 1. Chargement pool RSS
    print(f"📂 Chargement du pool RSS : {config.paths.pool_rss_path}")
    try:
        df_pool = load_pool(config)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    print(f"   → {len(df_pool):,} séjours dans le pool")

    # 2. Tirage aléatoire (reproductible via random_state=42)
    target = config.extraction.target_count
    if len(df_pool) > target:
        df_sample = df_pool.sample(n=target, random_state=42).reset_index(drop=True)
        print(f"   → Tirage aléatoire : {target} séjours")
    else:
        df_sample = df_pool.copy().reset_index(drop=True)
        print(f"   ⚠️ Pool < cible : on prend les {len(df_sample)} séjours disponibles")

    # 3. Reprise : ignorer les séjours déjà traités
    already_done = _load_already_done(config.paths.output_csv_path)
    if already_done:
        # Garde-fou : des séjours extraits avant réception du référentiel GHM
        # peuvent être hors du pool filtré ; ils resteraient dans le CSV final.
        try:
            corr = pd.read_csv(
                config.paths.correspondence_path,
                sep=";", encoding="utf-8-sig", dtype=str,
            )
            pool_numeros = set(df_pool["numero_admin"].fillna("").str.strip())
            stale = corr[
                ~corr["numero_admin"].fillna("").str.strip().isin(pool_numeros)
            ]
            if not stale.empty:
                print(
                    f"   ⚠️ {len(stale)} séjours déjà extraits sont hors du pool "
                    "filtré par GHM (extraction antérieure au référentiel ?).\n"
                    "      → Pour un dataset conforme, archivez/supprimez "
                    "cu2_dataset.csv et cu2_correspondance_INTERNE.csv puis relancez."
                )
        except Exception:
            pass
        # Pré-calculer les IDs du sample pour filtrer
        df_sample["_id"] = df_sample["numero_admin"].apply(
            lambda x: hash_sejour_id(str(x).strip())
        )
        df_sample = df_sample[~df_sample["_id"].isin(already_done)].drop(columns="_id")
        df_sample = df_sample.reset_index(drop=True)
        print(
            f"   → Reprise : {len(already_done)} déjà traités, {len(df_sample)} restants"
        )
    else:
        print(f"   → Nouveau départ : {len(df_sample)} séjours à traiter")

    if df_sample.empty:
        print("✅ Tous les séjours ont déjà été traités.")
        return

    all_patterns = (
        config.extraction.crh_doc_patterns + config.extraction.cro_doc_patterns
    )

    # 4. Vérification Java + jar
    java_path = config.paths.java_path
    jar_path = config.paths.pdf_jar_path
    if not Path(java_path).exists():
        print(f"❌ Java introuvable : {java_path}")
        print("   → Vérifiez JAVA_PATH dans .env ou WP2_CU2/config.py")
        return
    if not Path(jar_path).exists():
        print(f"❌ Jar introuvable : {jar_path}")
        print("   → Vérifiez PDF_JAR_PATH dans .env ou WP2_CU2/config.py")
        return
    print(f"✅ Java  : {java_path}")
    print(f"✅ Jar   : {jar_path}")

    # 5. Connexion DB
    print("\n🔗 Connexion à Easily...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return
    cursor = conn.cursor()
    print("✅ Connecté\n")

    # 6. Extraction itérative — écriture immédiate après chaque séjour
    link_stats = {"venue": 0, "ipp_dates": 0, "not_found": 0}
    n_with_text = 0

    for _, row in tqdm(
        df_sample.iterrows(), total=len(df_sample), desc="Extraction CU2"
    ):
        numero_admin = str(row.get("numero_admin", "")).strip()
        date_entree = str(row.get("date_entree_iso", "")).strip()
        date_sortie = str(row.get("date_sortie_iso", "")).strip()
        ghm = str(row.get("ghm", "")).strip()
        dp = str(row.get("dp", "")).strip()
        codes_ccam = str(row.get("codes_ccam", "")).strip()

        sejour_id = hash_sejour_id(numero_admin)
        specialite = get_specialite(
            ghm,
            config.extraction.ghm_specialites,
            config.extraction.ghm_to_specialite,
        )

        docs_df, method = find_docs_for_sejour(
            cursor,
            numero_admin,
            date_entree,
            date_sortie,
            all_patterns,
            config.extraction.tolerance_days,
        )
        link_stats[method] = link_stats.get(method, 0) + 1

        texte = ""
        if not docs_df.empty:
            texts = []
            for _, doc in docs_df.iterrows():
                doc_stockage_id = str(doc.get("doc_stockage_id", "")).strip()
                if not doc_stockage_id:
                    continue
                pdf_bytes = fetch_file_bytes(cursor, doc_stockage_id)
                if pdf_bytes:
                    t = extract_text_from_pdf(pdf_bytes, java_path, jar_path)
                    if len(t) >= _MIN_TEXT_CHARS:
                        texts.append(t)
            texte = "\n\n---\n\n".join(texts)

        out_row = {
            "ID": sejour_id,
            "Spécialité": specialite,
            "Texte": texte,
            "Codes CCAM": codes_ccam,
            "CIM-10 DP": dp,
        }

        # ── Sauvegarde immédiate ──
        _append_row(config.paths.output_csv_path, out_row)
        _append_correspondence(config.paths.correspondence_path, sejour_id, numero_admin)

        if len(texte) >= _MIN_TEXT_CHARS:
            n_with_text += 1

    conn.close()

    # 7. Statistiques finales (calculées depuis le CSV complet)
    df_out = pd.read_csv(
        config.paths.output_csv_path, sep=";", encoding="utf-8-sig", dtype=str
    )
    df_with_text = df_out[
        df_out["Texte"].fillna("").str.len() >= _MIN_TEXT_CHARS
    ].copy()
    _print_and_save_stats(df_out, df_with_text, link_stats, config)

    print(f"\n✅ Extraction CU2 terminée !")
    print(f"   Total dans le CSV  : {len(df_out)}")
    print(f"   Avec texte extrait : {len(df_with_text)}")
    print(f"   CSV (PARTAGES)     : {config.paths.output_csv_path}")
    print(f"   Correspondance     : {config.paths.correspondence_path}  ← usage interne")
    print(f"   Stats              : {config.paths.stats_path}")


# ---------------------------------------------------------------------------
# 9. STATISTIQUES
# ---------------------------------------------------------------------------


def _enrich_with_demographics(df_all: pd.DataFrame, config: CU2Config) -> pd.DataFrame:
    """Ajoute le sexe et l'âge (issus du RSS) à chaque séjour livré.

    Jonction : df_out.ID → cu2_correspondance_INTERNE (ID ↔ numero_admin) → pool_rss
    (sexe, date_naissance, date_entree_iso). Colonnes ajoutées : `sexe`, `age`.
    """
    df = df_all.copy()
    try:
        corr = pd.read_csv(
            config.paths.correspondence_path, sep=";", encoding="utf-8-sig", dtype=str
        ).drop_duplicates("ID")
        pool = pd.read_csv(
            config.paths.pool_rss_path, sep=None, engine="python",
            encoding="utf-8-sig", dtype=str,
        )
    except Exception:
        df["sexe"] = ""
        df["age"] = pd.NA
        return df

    pool_cols = pool[["numero_admin", "sexe", "date_naissance", "date_entree_iso"]].drop_duplicates(
        "numero_admin"
    )
    df = df.merge(corr, on="ID", how="left").merge(pool_cols, on="numero_admin", how="left")

    def _age(row):
        naiss = str(row.get("date_naissance", "") or "").strip()    # JJMMAAAA
        entree = str(row.get("date_entree_iso", "") or "").strip()  # AAAA-MM-JJ
        try:
            if len(naiss) == 8 and naiss.isdigit() and len(entree) >= 4:
                return float(int(entree[:4]) - int(naiss[4:8]))
        except Exception:
            return None
        return None

    df["age"] = df.apply(_age, axis=1)
    return df


def _print_and_save_stats(
    df_all: pd.DataFrame,
    df_text: pd.DataFrame,
    link_stats: dict,
    config: CU2Config,
):
    # Enrichissement démographique pour les métadonnées obligatoires du guide (§5.4)
    df_demo = _enrich_with_demographics(df_all, config)
    df_demo["__age"] = pd.to_numeric(df_demo["age"], errors="coerce")

    n_total = len(df_demo)
    n_h = int((df_demo["sexe"] == "M").sum())
    n_f = int((df_demo["sexe"] == "F").sum())
    age_moyen = df_demo["__age"].dropna().mean()

    print(f"\n{'=' * 60}")
    print("STATISTIQUES CU2")
    print(f"{'=' * 60}")
    print(f"Séjours traités      : {n_total}")
    print(f"Avec texte extrait   : {len(df_text)}")
    print(f"Sexe ratio           : {n_h} H / {n_f} F"
          + (f"  (H/F = {n_h / n_f:.2f})" if n_f else ""))
    print("Âge moyen            : "
          + (f"{age_moyen:.1f} ans" if pd.notna(age_moyen) else "n/a"))
    print("\nMéthode de liaison RSS→CRH :")
    for m, k in sorted(link_stats.items(), key=lambda x: -x[1]):
        print(f"   · {m}: {k}")
    print("\nRépartition par spécialité :")
    print(df_all["Spécialité"].value_counts().to_string())
    print("\nTop 10 CIM-10 DP :")
    print(df_text["CIM-10 DP"].value_counts().head(10).to_string())
    print(f"{'=' * 60}\n")

    # --- cu2_stats.csv : par spécialité (nb, sexe, âge moyen, CIM-10 DP dominant) ---
    stats_rows = []
    for specialite, count in df_all["Spécialité"].value_counts().items():
        sub = df_demo[df_demo["Spécialité"] == specialite]
        sub_text = df_text[df_text["Spécialité"] == specialite]
        age_sp = sub["__age"].dropna().mean()
        top_dp = (
            sub_text["CIM-10 DP"].value_counts().index[0]
            if len(sub_text) > 0 and sub_text["CIM-10 DP"].value_counts().size > 0
            else ""
        )
        stats_rows.append({
            "specialite": specialite,
            "nb_sejours": int(count),
            "nb_avec_texte": len(sub_text),
            "nb_hommes": int((sub["sexe"] == "M").sum()),
            "nb_femmes": int((sub["sexe"] == "F").sum()),
            "age_moyen": round(age_sp, 1) if pd.notna(age_sp) else "",
            "top_cim10_dp": top_dp,
        })
    pd.DataFrame(stats_rows).to_csv(
        config.paths.stats_path, sep=";", index=False, encoding="utf-8-sig"
    )

    # --- cu2_cim10_frequency.csv : distribution complète des CIM-10 DP ---
    cim_counts = (
        df_all["CIM-10 DP"].fillna("").replace("", pd.NA).dropna().value_counts()
    )
    cim_rows = [
        {
            "cim10_dp": code,
            "nb_sejours": int(cnt),
            "frequence": round(cnt / n_total, 4) if n_total else 0,
        }
        for code, cnt in cim_counts.items()
    ]
    pd.DataFrame(cim_rows).to_csv(
        config.paths.cim10_freq_path, sep=";", index=False, encoding="utf-8-sig"
    )


# ---------------------------------------------------------------------------
# 10. POINT D'ENTRÉE
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import getpass

    config = DEFAULT_CONFIG

    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    run_extraction(config)
