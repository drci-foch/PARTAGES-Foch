"""
Étape 1/2 — Récupération du pool de métadonnées CU5b
Hôpital Foch / Projet PARTAGES

Constitue pool_metadata.csv : CR de consultation (type 7) du service d'oncologie.
Filtre oncologie : EXISTS doc→VENUE→SEJOUR avec sej_uf_medicale_code ∈ UF onco.

Usage :
    python WP5_CU5b/fetch_pool.py
"""

import sys
import getpass
from pathlib import Path

import pyodbc
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU5bConfig, DEFAULT_CONFIG


def cursor_to_df(cursor: pyodbc.Cursor) -> pd.DataFrame:
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame.from_records(rows, columns=columns)


def build_meta_query(config: CU5bConfig) -> str:
    ex = config.extraction
    uf_list = ",".join(f"'{u}'" for u in ex.oncology_uf_codes)
    return f"""
    SELECT TOP {ex.sql_pool_size}
        d.doc_id,
        d.doc_stockage_id,
        d.doc_nom,
        d.doc_extension,
        COALESCE(d.doc_realisation_date, d.doc_creation_date) AS doc_date,
        d.doc_pat_id,
        p.pat_ipp
    FROM METADONE.metadone.DOCUMENTS d
    INNER JOIN NOYAU.patient.PATIENT p ON p.pat_id = d.doc_pat_id
    INNER JOIN STOCKAGE.stockage.FILES f ON f.fil_id = d.doc_stockage_id
    WHERE
        d.doc_type_code = {int(ex.doc_type_code)}
        AND COALESCE(d.doc_realisation_date, d.doc_creation_date) >= '{ex.date_min}'
        AND COALESCE(d.doc_realisation_date, d.doc_creation_date) <= '{ex.date_max}'
        AND d.doc_supprime != 'true'
        AND p.pat_ipp IS NOT NULL
        AND (f.fil_data IS NOT NULL OR f.fil_data_fs IS NOT NULL)
        AND EXISTS (
            SELECT 1
            FROM NOYAU.patient.VENUE v
            INNER JOIN NOYAU.patient.SEJOUR s ON s.ven_id = v.ven_id
            WHERE v.ven_id = d.doc_venue_id
              AND s.sej_uf_medicale_code IN ({uf_list})
        )
    ORDER BY NEWID()
    """


def fetch_pool(config: CU5bConfig = None):
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
    print(f"\n📋 Récupération du pool CU5b (consultations onco, UF {config.extraction.oncology_uf_codes})...")
    print("   (la requête EXISTS sur VENUE/SEJOUR peut prendre 1-2 min)")

    try:
        cursor = conn.cursor()
        conn.timeout = 300
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
