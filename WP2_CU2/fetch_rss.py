"""
Étape 1/2 — Récupération du pool RSS pour CU2
Hôpital Foch / Projet PARTAGES

Parse les fichiers RSS 2023-2025, filtre les séjours ambulatoires (durée = 0)
et optionnellement par liste GHM, puis sauvegarde pool_rss.csv.

Usage :
    python WP2_CU2/fetch_rss.py
"""

import sys
import getpass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.rss_parser import RSSParser, duree_sejour
from config import CU2Config, DEFAULT_CONFIG


def fetch_rss(config: CU2Config = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.ensure_dirs()

    print("📂 Lecture des fichiers RSS...")
    print(f"   Base : {config.extraction.rss_base_path}")
    print(f"   Années : {config.extraction.years}")

    parser = RSSParser(base_path=config.extraction.rss_base_path)
    sejours = parser.parse_years(config.extraction.years)

    if not sejours:
        print("❌ Aucun séjour RSS trouvé. Vérifiez le chemin et les années.")
        return

    print(f"\n   → {len(sejours):,} séjours RSS bruts")

    # Conversion DataFrame
    df = parser.to_dataframe(sejours)

    # Filtre ambulatoire (durée = 0)
    if config.extraction.only_ambulatoire:
        df = df[df["duree_sejour"] == 0].copy()
        print(f"   → {len(df):,} séjours ambulatoires (durée = 0)")

    # Filtre GHM (référentiel PARTAGES chirurgie ambulatoire)
    if config.extraction.ghm_whitelist:
        whitelist = set(config.extraction.ghm_whitelist)
        df = df[df["ghm"].fillna("").astype(str).str.strip().isin(whitelist)].copy()
        print(f"   → {len(df):,} après filtre GHM ({len(whitelist)} GHM)")

    if df.empty:
        print("⚠️  Aucun séjour après filtrage.")
        return

    # Dédoublonnage sur numero_admin (un séjour = une ligne)
    before = len(df)
    df = df.drop_duplicates(subset="numero_admin").reset_index(drop=True)
    if len(df) < before:
        print(f"   → {len(df):,} après dédoublonnage sur numero_admin (- {before - len(df)})")

    # Statistiques rapides
    print(f"\n{'=' * 50}")
    print(f"Pool RSS : {len(df):,} séjours uniques")
    print(f"{'=' * 50}")
    print("\nRépartition par année (date_entree_iso) :")
    print(pd.to_datetime(df["date_entree_iso"], errors="coerce").dt.year.value_counts().sort_index().to_string())
    print("\nTop 10 GHM :")
    print(df["ghm"].value_counts().head(10).to_string())

    df.to_csv(config.paths.pool_rss_path, sep=";", index=False, encoding="utf-8-sig")
    print(f"\n✅ Pool sauvegardé : {config.paths.pool_rss_path}")


if __name__ == "__main__":
    config = DEFAULT_CONFIG
    fetch_rss(config)
