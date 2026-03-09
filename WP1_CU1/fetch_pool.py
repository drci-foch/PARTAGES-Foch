"""
Étape 1/2 — Récupération du pool de métadonnées CU1
Hôpital Foch / Projet PARTAGES

Lance une seule fois pour constituer pool_metadata.csv.
extract_cu1.py lit ce fichier sans retoucher la base.

Usage :
    python WP1_CU1/fetch_pool.py
"""

import sys
import getpass
from pathlib import Path

import pyodbc
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU1Config, DEFAULT_CONFIG


def cursor_to_df(cursor: pyodbc.Cursor) -> pd.DataFrame:
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)


def build_meta_query(config: CU1Config) -> str:
    exclusion_clauses = " OR ".join(
        f"LOWER(TRIM(d.doc_nom)) LIKE '{p}'"
        for p in config.extraction.doc_exclusion_patterns
    )
    return f"""
    SELECT TOP {config.extraction.sql_pool_size}
        d.doc_id,
        d.doc_stockage_id,
        d.doc_nom,
        d.doc_extension,
        CASE
            WHEN d.doc_realisation_date IS NOT NULL
                 AND d.doc_realisation_date >= '2003-01-01'
            THEN d.doc_realisation_date
            ELSE d.doc_creation_date
        END AS doc_date,
        d.doc_cr_code                             AS departement_code,
        p.pat_ipp,
        p.{config.extraction.col_sexe}            AS pat_sexe,
        p.{config.extraction.col_date_naissance}  AS pat_date_naissance
    FROM METADONE.metadone.DOCUMENTS d
    INNER JOIN NOYAU.patient.PATIENT p ON p.pat_id = d.doc_pat_id
    INNER JOIN STOCKAGE.stockage.FILES f ON f.fil_id = d.doc_stockage_id
    WHERE
        CASE
            WHEN d.doc_realisation_date IS NOT NULL AND d.doc_realisation_date >= '2003-01-01'
            THEN d.doc_realisation_date
            ELSE d.doc_creation_date
        END >= '{config.extraction.date_min}'
        AND CASE
            WHEN d.doc_realisation_date IS NOT NULL AND d.doc_realisation_date >= '2003-01-01'
            THEN d.doc_realisation_date
            ELSE d.doc_creation_date
        END <= '{config.extraction.date_max}'
        AND d.doc_supprime != 'true'
        AND p.pat_ipp IS NOT NULL
        AND TRY_CAST(d.doc_app_id AS INT) > 0
        AND NOT ({exclusion_clauses})
        AND f.fil_data IS NOT NULL
    ORDER BY NEWID()
    """


def fetch_pool(config: CU1Config = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.raw_pdf_dir.parent.mkdir(parents=True, exist_ok=True)

    print("🔗 Connexion à Easily (SQL Server)...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return

    print("✅ Connecté à METADONE")
    print(f"\n📋 Récupération du pool (TOP {config.extraction.sql_pool_size})...")

    try:
        cursor = conn.cursor()
        cursor.execute(build_meta_query(config))
        df = cursor_to_df(cursor)
    except Exception as e:
        print(f"❌ Erreur requête : {e}")
        conn.close()
        return

    conn.close()

    print(f"   → {len(df):,} documents trouvés")

    df.to_csv(config.paths.pool_path, index=False, encoding="utf-8-sig")
    print(f"✅ Pool sauvegardé : {config.paths.pool_path}")


if __name__ == "__main__":
    config = DEFAULT_CONFIG

    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    fetch_pool(config)
