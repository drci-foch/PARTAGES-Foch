"""
Étape 1/2 — Récupération du pool de métadonnées CU5a
Hôpital Foch / Projet PARTAGES

Lance une seule fois pour constituer pool_metadata.csv (candidats anapath + génétique).
extract_cu5a.py lit ce fichier ensuite (stratification par localisation + extraction texte).

Usage :
    python WP5_CU5a/fetch_pool.py
"""

import sys
import getpass
from pathlib import Path

import pyodbc
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU5aConfig, DEFAULT_CONFIG


def cursor_to_df(cursor: pyodbc.Cursor) -> pd.DataFrame:
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)


def build_meta_query(config: CU5aConfig) -> str:
    type_list = ",".join(str(int(t)) for t in config.extraction.doc_type_codes)
    return f"""
    SELECT TOP {config.extraction.sql_pool_size}
        d.doc_id,
        d.doc_stockage_id,
        d.doc_nom,
        d.doc_extension,
        d.doc_type_code,
        COALESCE(d.doc_realisation_date, d.doc_creation_date) AS doc_date,
        d.doc_cr_code                                          AS cr_code,
        d.doc_pat_id,
        p.pat_ipp,
        v.ven_numero
    FROM METADONE.metadone.DOCUMENTS d
    INNER JOIN NOYAU.patient.PATIENT p ON p.pat_id = d.doc_pat_id
    INNER JOIN STOCKAGE.stockage.FILES f ON f.fil_id = d.doc_stockage_id
    LEFT JOIN NOYAU.patient.VENUE v ON d.doc_venue_id = v.ven_id
    WHERE
        d.doc_type_code IN ({type_list})
        AND COALESCE(d.doc_realisation_date, d.doc_creation_date) >= '{config.extraction.date_min}'
        AND COALESCE(d.doc_realisation_date, d.doc_creation_date) <= '{config.extraction.date_max}'
        AND d.doc_supprime != 'true'
        AND p.pat_ipp IS NOT NULL
        AND (f.fil_data IS NOT NULL OR f.fil_data_fs IS NOT NULL)
    ORDER BY NEWID()
    """


def fetch_pool(config: CU5aConfig = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.ensure_dirs()

    print("🔗 Connexion à Easily (SQL Server)...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return

    print("✅ Connecté à METADONE")
    print(f"\n📋 Récupération du pool CU5a (TOP {config.extraction.sql_pool_size}, "
          f"types {config.extraction.doc_type_codes})...")

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
    if not df.empty:
        counts = df["doc_type_code"].value_counts().to_dict()
        for code, lib in config.extraction.type_labels.items():
            print(f"     · {lib} (type {code}) : {counts.get(code, 0):,}")

    df.to_csv(config.paths.pool_path, index=False, encoding="utf-8-sig")
    print(f"✅ Pool sauvegardé : {config.paths.pool_path}")


if __name__ == "__main__":
    config = DEFAULT_CONFIG

    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    fetch_pool(config)
