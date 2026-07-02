"""
Étape 2/2 — Extraction CU5b - Analyse de la réponse aux traitements en oncologie
Hôpital Foch / Projet PARTAGES

Critères (guide PARTAGES v29.01.26, section 8) :
  - CR de consultation (type 7) du service d'oncologie (UF 324A/324E/324B), datés ≥ 2010
  - Volume : 500 CR (idéal ; min 100, max 1000)
  - Texte : couche native uniquement (pdfplumber). Les documents sans couche texte
    exploitable (scans à océriser) sont ÉCARTÉS — pas de méthode d'OCR fiable.
  - Sorties : output/txt/*.txt, metadata_cu5b.csv, ipp_cu5b.csv (interne)

NOTE : Lancez d'abord python WP5_CU5b/fetch_pool.py pour générer pool_metadata.csv.
"""

import sys
from pathlib import Path

import pyodbc
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU5bConfig, DEFAULT_CONFIG
from utils.pdf_converter import PdfConverter, hash_doc_id


# ---------------------------------------------------------------------------
# 1. CHARGEMENT DU POOL
# ---------------------------------------------------------------------------

def load_pool(config: CU5bConfig) -> pd.DataFrame:
    if not config.paths.pool_path.exists():
        raise FileNotFoundError(
            f"Pool introuvable : {config.paths.pool_path}\n"
            "→ Lancez d'abord : python WP5_CU5b/fetch_pool.py"
        )
    df = pd.read_csv(config.paths.pool_path, encoding="utf-8-sig")
    df["doc_date"] = pd.to_datetime(df["doc_date"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 2. TÉLÉCHARGEMENT + EXTRACTION TEXTE
# ---------------------------------------------------------------------------

def download_binaries(cursor, stockage_ids: list, batch_size: int) -> dict:
    file_map: dict = {}
    for i in range(0, len(stockage_ids), batch_size):
        batch = stockage_ids[i:i + batch_size]
        ph = ",".join("?" * len(batch))
        try:
            cursor.execute(
                f"SELECT fil_id, fil_data, fil_data_fs FROM STOCKAGE.stockage.FILES "
                f"WHERE fil_id IN ({ph})",
                batch,
            )
            for fil_id, fil_data, fil_data_fs in cursor.fetchall():
                file_map[fil_id] = (fil_data, fil_data_fs)
        except Exception as e:
            print(f"  ⚠️ Erreur batch binaires : {e}")
    return file_map


def _extract_one(args: tuple) -> dict:
    """Extrait la couche texte native d'un document.

    Aucun OCR : faute de méthode d'OCR fiable, un document sans couche texte
    exploitable (scan) est marqué non valide et sera écarté de l'échantillon.
    """
    row, fil_data, fil_data_fs, converter, config = args
    ex = config.extraction
    doc_id = str(row["doc_id"])
    file_id = hash_doc_id(doc_id)

    text = converter.convert(fil_data, fil_data_fs, str(row.get("doc_extension", "pdf")))

    valid = bool(text) and len(text) >= ex.min_text_chars
    return {
        "file_id": file_id,
        "doc_date": row["doc_date"].strftime("%Y-%m-%d") if pd.notna(row["doc_date"]) else "",
        "pat_ipp": row.get("pat_ipp", ""),
        "text": text if valid else None,
        "text_chars": len(text) if text else 0,
        "is_valid": valid,
    }


def extract_candidates(df: pd.DataFrame, file_map: dict, converter: PdfConverter,
                       config: CU5bConfig) -> list[dict]:
    args_list = []
    for _, row in df.iterrows():
        fil_data, fil_data_fs = file_map.get(row["doc_stockage_id"], (None, None))
        args_list.append((row, fil_data, fil_data_fs, converter, config))

    records = [None] * len(args_list)
    workers = config.extraction.max_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_one, a): i for i, a in enumerate(args_list)}
        with tqdm(total=len(futures), desc=f"Extraction texte ({workers} workers)") as pbar:
            for fut in as_completed(futures):
                records[futures[fut]] = fut.result()
                pbar.update(1)
    return records


# ---------------------------------------------------------------------------
# 3. SAUVEGARDE
# ---------------------------------------------------------------------------

def save_outputs(records: list[dict], config: CU5bConfig) -> pd.DataFrame:
    txt_dir = config.paths.txt_dir
    txt_dir.mkdir(parents=True, exist_ok=True)

    meta_rows = []
    for r in records:
        filename = f"{r['file_id']}.txt"
        (txt_dir / filename).write_text(r["text"], encoding="utf-8")
        meta_rows.append({
            "file_id": r["file_id"],
            "filename": filename,
            "service": "oncologie",
            "doc_date": r["doc_date"],
            "text_chars": r["text_chars"],
            "export_success": True,
        })

    df_meta = pd.DataFrame(meta_rows)
    df_meta.to_csv(config.paths.metadata_path, index=False, encoding="utf-8-sig")

    df_ipp = pd.DataFrame([{"pat_ipp": r["pat_ipp"]} for r in records])
    df_ipp.drop_duplicates().dropna().to_csv(config.paths.ipp_path, index=False, encoding="utf-8-sig")
    return df_meta


def print_stats(df_meta: pd.DataFrame):
    print(f"\n{'=' * 60}")
    print("STATISTIQUES DE L'ÉCHANTILLON FINAL CU5b")
    print(f"{'=' * 60}")
    print(f"Documents retenus : {len(df_meta)}")
    print("\nRépartition par année :")
    years = pd.to_datetime(df_meta["doc_date"], errors="coerce").dt.year
    print(years.value_counts().sort_index().to_string())
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# 4. PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def run_extraction(config: CU5bConfig = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.ensure_dirs()
    target = config.extraction.target_count
    oversample_target = int(target * config.extraction.oversample_factor)

    # 1. Pool
    print(f"📂 Chargement du pool : {config.paths.pool_path}")
    try:
        df_all = load_pool(config)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return
    print(f"   → {len(df_all):,} documents dans le pool")
    if df_all.empty:
        print("❌ Pool vide.")
        return
    if len(df_all) < config.extraction.min_count:
        print(f"⚠️  Pool ({len(df_all)}) sous le minimum requis ({config.extraction.min_count}).")

    # 2. Tirage aléatoire des candidats (sur-échantillonné)
    n_cand = min(len(df_all), oversample_target)
    df_candidates = df_all.sample(n=n_cand, random_state=42).reset_index(drop=True)
    print(f"   Candidats tirés : {len(df_candidates)} (cible finale : {target})")

    # 3. Connexion + téléchargement
    print("\n🔗 Connexion à Easily...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return
    cursor = conn.cursor()

    print("ℹ️  Sélection sur couche texte native uniquement : les documents à océriser "
          "(scans) sont écartés (pas de méthode d'OCR fiable).")

    print(f"\n⬇️  Téléchargement de {len(df_candidates)} fichiers...")
    file_map = download_binaries(
        cursor, df_candidates["doc_stockage_id"].tolist(), config.extraction.batch_size
    )
    conn.close()

    # 4. Extraction texte
    converter = PdfConverter(config.paths.java_path, config.paths.pdf_jar_path)
    records = extract_candidates(df_candidates, file_map, converter, config)

    valid = [r for r in records if r["is_valid"]]
    print(f"\n   Valides : {len(valid)} / {len(records)}")
    if len(valid) < target:
        print(f"⚠️  Seulement {len(valid)} documents exploitables (cible : {target}).")
        print("    → Augmentez sql_pool_size / oversample_factor dans config.py.")

    final_records = valid[:target]

    # 5. Sauvegarde
    print(f"\n📁 Sauvegarde de {len(final_records)} fichiers .txt...")
    df_meta = save_outputs(final_records, config)

    print_stats(df_meta)
    print("✅ Extraction CU5b terminée !")
    print(f"   Fichiers .txt : {config.paths.txt_dir}")
    print(f"   Métadonnées   : {config.paths.metadata_path}")
    print(f"   IPP (interne) : {config.paths.ipp_path}")


if __name__ == "__main__":
    import getpass

    config = DEFAULT_CONFIG
    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    run_extraction(config)
