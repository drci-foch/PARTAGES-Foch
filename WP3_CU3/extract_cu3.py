"""
Étape 2/2 — Extraction CU3 - Résumé automatique des CR médicaux
Hôpital Foch / Projet PARTAGES

Critères (guide PARTAGES v29.01.26, section 6) :
  - CR récents (≥ 2020), tous types de CR médicaux hors documents non cliniques
  - OBLIGATOIRE : conclusion bien définie, détectée par balises ancres (FAQ #10)
  - Volume : 400 CR (idéal ; min 100, max 1000)
  - Stratification : année × sexe × tranche d'âge (représentativité, §6.2)
  - Sortie : 2 fichiers .txt par CR (guide §6.3 / §9.1) :
      {file_id}_{strate}.txt              → corps du texte SANS la conclusion
      {file_id}_{strate}_conclusion.txt   → conclusion seule
    La strate figure dans le NOM des fichiers (métadonnée obligatoire, §6.4).
  - Texte : couche native uniquement ; les scans à océriser sont ÉCARTÉS
    (pas d'OCR fiable) → aucun suffixe « _ocr » (répartition 100 % non-OCR).

NOTE : Lancez d'abord python WP3_CU3/fetch_pool.py pour générer pool_metadata.csv.
"""

import sys
from pathlib import Path

import pyodbc
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU3Config, DEFAULT_CONFIG
from utils.pdf_converter import PdfConverter, hash_doc_id
from utils.conclusion_splitter import split_conclusion, strip_rgpd_boilerplate


# ---------------------------------------------------------------------------
# 1. CHARGEMENT DU POOL
# ---------------------------------------------------------------------------

def load_pool(config: CU3Config) -> pd.DataFrame:
    if not config.paths.pool_path.exists():
        raise FileNotFoundError(
            f"Pool introuvable : {config.paths.pool_path}\n"
            "→ Lancez d'abord : python WP3_CU3/fetch_pool.py"
        )
    df = pd.read_csv(config.paths.pool_path, encoding="utf-8-sig")
    df["doc_date"] = pd.to_datetime(df["doc_date"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 2. STRATIFICATION (identique CU1)
# ---------------------------------------------------------------------------

def compute_strate(row: pd.Series, age_bins: list, age_labels: list) -> str:
    """Calcule la strate : {année}_{sexe}_{tranche_age} — ex. 2021_Homme_50-54ans"""
    year = row["doc_date"].year if pd.notna(row["doc_date"]) else "XXXX"

    sexe_raw = str(row.get("pat_sexe", "")).strip().upper()
    if sexe_raw in ("M", "MASCULIN", "H", "HOMME", "1"):
        sexe = "Homme"
    elif sexe_raw in ("F", "FEMININ", "FÉMININ", "FEMME", "2"):
        sexe = "Femme"
    else:
        sexe = "Inconnu"

    try:
        naissance = pd.to_datetime(row["pat_date_naissance"])
        doc_date = pd.to_datetime(row["doc_date"])
        age = (doc_date - naissance).days // 365
        age_label = pd.cut([age], bins=age_bins, labels=age_labels, right=False)[0]
        age_str = str(age_label) if pd.notna(age_label) else "Age_inconnu"
    except Exception:
        age_str = "Age_inconnu"

    return f"{year}_{sexe}_{age_str}"


def stratified_sample(df: pd.DataFrame, target: int, random_state: int = 42) -> pd.DataFrame:
    """Échantillonnage proportionnel par strate pour atteindre `target` documents."""
    if len(df) <= target:
        return df

    strate_freq = df["strate"].value_counts(normalize=True)
    allocation = (strate_freq * target).round().astype(int)

    diff = target - allocation.sum()
    if diff != 0:
        allocation[allocation.idxmax()] += diff

    sampled_parts = []
    for strate, n in allocation.items():
        subset = df[df["strate"] == strate]
        n = min(n, len(subset))
        if n > 0:
            sampled_parts.append(subset.sample(n=n, random_state=random_state))

    return pd.concat(sampled_parts).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. TÉLÉCHARGEMENT + VALIDATION (texte natif + conclusion)
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


def _check_one(args: tuple) -> dict:
    """Worker : extrait la couche texte native puis tente le split corps/conclusion.

    Un document est valide si ET SEULEMENT SI :
      1. une couche texte native exploitable existe (pas d'OCR — scans écartés) ;
      2. une conclusion est détectée par balise ancre et passe les seuils
         (longueurs minimales, ratio conclusion/document).
    """
    row, fil_data, fil_data_fs, converter, config = args
    ex = config.extraction
    doc_id = str(row["doc_id"])
    file_id = hash_doc_id(doc_id)

    text = converter.convert(fil_data, fil_data_fs, str(row.get("doc_extension", "pdf")))
    if text:
        # Mention d'information RGPD/EDS Foch en fin de document : retirée
        # AVANT le split pour qu'elle ne pollue ni le corps ni la conclusion.
        text = strip_rgpd_boilerplate(text)
    result = {
        "file_id": file_id,
        "strate": row["strate"],
        "doc_date": row["doc_date"].strftime("%Y-%m-%d") if pd.notna(row["doc_date"]) else "",
        "departement_code": row.get("departement_code", ""),
        "pat_ipp": row.get("pat_ipp", ""),
        "is_valid": False,
        "reject_reason": "",
        "body": None,
        "conclusion": None,
        "anchor": "",
        "pdf_bytes": None,
    }

    n_chars = len("".join(text.split())) if text else 0
    if n_chars < ex.min_body_chars:
        result["reject_reason"] = "no_text_layer"
        return result
    if n_chars > ex.max_doc_chars:
        result["reject_reason"] = "doc_too_large"
        return result

    split = split_conclusion(
        text,
        anchors=ex.conclusion_anchors,
        min_conclusion_chars=ex.min_conclusion_chars,
        min_body_chars=ex.min_body_chars,
        max_conclusion_ratio=ex.max_conclusion_ratio,
    )
    if not split["ok"]:
        result["reject_reason"] = split["reason"]
        return result

    # PDF source conservé pour traçabilité (si le binaire est bien un PDF)
    try:
        b = bytes(fil_data) if fil_data is not None and not isinstance(fil_data, bytes) else fil_data
        if b and b[:4] == b"%PDF":
            result["pdf_bytes"] = b
    except Exception:
        pass

    result.update(is_valid=True, body=split["body"], conclusion=split["conclusion"],
                  anchor=split["anchor"])
    return result


def validate_candidates(df: pd.DataFrame, file_map: dict, converter: PdfConverter,
                        config: CU3Config) -> list[dict]:
    args_list = []
    for _, row in df.iterrows():
        fil_data, fil_data_fs = file_map.get(row["doc_stockage_id"], (None, None))
        args_list.append((row, fil_data, fil_data_fs, converter, config))

    records = [None] * len(args_list)
    workers = config.extraction.max_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check_one, a): i for i, a in enumerate(args_list)}
        with tqdm(total=len(futures), desc=f"Validation texte+conclusion ({workers} workers)") as pbar:
            for fut in as_completed(futures):
                records[futures[fut]] = fut.result()
                pbar.update(1)
    return records


# ---------------------------------------------------------------------------
# 4. SAUVEGARDE
# ---------------------------------------------------------------------------

def save_outputs(records: list[dict], strate_pop_freq: dict, config: CU3Config) -> pd.DataFrame:
    """Écrit les 2 .txt par CR (corps + conclusion), le PDF source, les métadonnées.

    Nommage (guide §6.3/§6.4) : la strate figure dans le titre des fichiers ;
    le fichier conclusion porte le suffixe « _conclusion ». Pas de suffixe
    « _ocr » : tous les documents sont issus de la couche texte native.
    """
    txt_dir = config.paths.txt_dir
    txt_dir.mkdir(parents=True, exist_ok=True)
    config.paths.raw_pdf_dir.mkdir(parents=True, exist_ok=True)

    meta_rows = []
    for r in records:
        base = f"{r['file_id']}_{r['strate']}"
        fn_body = f"{base}.txt"
        fn_conc = f"{base}_conclusion.txt"
        (txt_dir / fn_body).write_text(r["body"], encoding="utf-8")
        (txt_dir / fn_conc).write_text(r["conclusion"], encoding="utf-8")
        if r["pdf_bytes"]:
            (config.paths.raw_pdf_dir / f"{r['file_id']}.pdf").write_bytes(r["pdf_bytes"])

        meta_rows.append({
            "file_id": r["file_id"],
            "filename_texte": fn_body,
            "filename_conclusion": fn_conc,
            "strate": r["strate"],
            "frequence_strate_population": round(strate_pop_freq.get(r["strate"], 0), 4),
            "doc_date": r["doc_date"],
            "departement_code": r["departement_code"],
            "balise_conclusion": r["anchor"],
            "body_chars": len("".join(r["body"].split())),
            "conclusion_chars": len("".join(r["conclusion"].split())),
            "ocr": False,
            "export_success": True,
        })

    df_meta = pd.DataFrame(meta_rows)
    df_meta.to_csv(config.paths.metadata_path, index=False, encoding="utf-8-sig")

    df_ipp = pd.DataFrame([{"pat_ipp": r["pat_ipp"]} for r in records])
    df_ipp.drop_duplicates().dropna().to_csv(config.paths.ipp_path, index=False, encoding="utf-8-sig")
    return df_meta


def print_stats(df_meta: pd.DataFrame):
    print(f"\n{'=' * 60}")
    print("STATISTIQUES DE L'ÉCHANTILLON FINAL CU3")
    print(f"{'=' * 60}")
    print(f"Documents retenus : {len(df_meta)}  (× 2 fichiers .txt)")
    print("\nRépartition par année :")
    years = pd.to_datetime(df_meta["doc_date"], errors="coerce").dt.year
    print(years.value_counts().sort_index().to_string())
    print("\nRépartition par balise de conclusion :")
    print(df_meta["balise_conclusion"].value_counts().to_string())
    print("\nRépartition par strate (top 10) :")
    print(df_meta["strate"].value_counts().head(10).to_string())
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# 5. PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def run_extraction(config: CU3Config = None):
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

    # Filtre de sécurité sur doc_nom : le pool a pu être généré avant l'ajout
    # d'un motif d'exclusion (ex. « contexte de vie ») — on ré-applique ici.
    pats = [p.strip("%").lower() for p in config.extraction.doc_exclusion_patterns]
    excl = df_all["doc_nom"].fillna("").str.lower().apply(lambda n: any(p in n for p in pats))
    if excl.any():
        print(f"   → {excl.sum()} documents exclus par motif doc_nom (post-pool)")
        df_all = df_all[~excl].reset_index(drop=True)

    if len(df_all) < target:
        print(f"⚠️  Pool insuffisant ({len(df_all)} < {target}). Relancez fetch_pool.py.")
        return

    # 2. Stratification
    print("\n📊 Calcul des strates...")
    df_all["strate"] = df_all.apply(
        compute_strate, axis=1,
        age_bins=config.extraction.age_bins,
        age_labels=config.extraction.age_labels,
    )
    strate_pop_freq = df_all["strate"].value_counts(normalize=True).to_dict()

    # 3. Sur-échantillonnage stratifié des candidats
    df_candidates = stratified_sample(df_all, target=oversample_target)
    print(f"   Candidats : {len(df_candidates)}  (cible finale : {target})")

    # 4. Téléchargement des binaires
    print("\n🔗 Connexion à Easily...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return
    cursor = conn.cursor()

    print("ℹ️  Couche texte native uniquement : les scans à océriser sont écartés "
          "(pas d'OCR fiable) — aucun suffixe « _ocr ».")

    print(f"\n⬇️  Téléchargement de {len(df_candidates)} fichiers...")
    file_map = download_binaries(
        cursor, df_candidates["doc_stockage_id"].tolist(), config.extraction.batch_size
    )
    conn.close()

    # 5. Validation : texte natif + conclusion détectée
    converter = PdfConverter(config.paths.java_path, config.paths.pdf_jar_path)
    print(f"\n🔍 Validation (couche texte + détection de conclusion)...")
    all_results = validate_candidates(df_candidates, file_map, converter, config)

    valid_records = [r for r in all_results if r["is_valid"]]
    reject_summary: dict = {}
    for r in all_results:
        if not r["is_valid"]:
            reject_summary[r["reject_reason"]] = reject_summary.get(r["reject_reason"], 0) + 1

    print(f"   Valides : {len(valid_records)} / {len(all_results)}")
    for reason, count in sorted(reject_summary.items(), key=lambda x: -x[1]):
        print(f"   · {reason}: {count}")

    if len(valid_records) < target:
        print(f"\n⚠️  Seulement {len(valid_records)} CR valides (cible : {target})")
        print("   → Augmentez oversample_factor ou sql_pool_size dans config.py.")

    # Les candidats ont été tirés de façon stratifiée → les valides le sont aussi.
    final_records = valid_records[:target]

    # 6. Sauvegarde : 2 .txt par CR + PDF (traçabilité) + métadonnées + IPP
    print(f"\n📁 Sauvegarde de {len(final_records)} CR (2 .txt chacun)...")
    df_meta = save_outputs(final_records, strate_pop_freq, config)

    print_stats(df_meta)
    print("✅ Extraction CU3 terminée !")
    print(f"   CR retenus     : {len(final_records)}  → {2 * len(final_records)} fichiers .txt")
    print(f"   Dossier TXT    : {config.paths.txt_dir}")
    print(f"   Dossier PDF    : {config.paths.raw_pdf_dir}")
    print(f"   Métadonnées    : {config.paths.metadata_path}")
    print(f"   IPP (interne)  : {config.paths.ipp_path}")


if __name__ == "__main__":
    import getpass

    config = DEFAULT_CONFIG
    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    run_extraction(config)
