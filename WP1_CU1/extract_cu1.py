"""
Extraction CU1 - Pseudonymisation des CR médicaux
Hôpital Foch / Projet PARTAGES

Critères (guide PARTAGES v29.01.26) :
  - CR datant de 2015 ou après
  - Tous types de CR médicaux (hors documents admin)
  - Volume cible : 400 CR (min 100, max 1000)
  - Stratification : année × sexe × tranche d'âge
  - Format sortie : .txt (1 fichier / CR)
  - Métadonnées : metadata_cu1.csv
"""

import io
import sys
from pathlib import Path

import pyodbc
import pandas as pd
import pdfplumber
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.pdf_converter import PdfConverter, hash_doc_id
from config import CU1Config, DEFAULT_CONFIG

# ---------------------------------------------------------------------------
# NOTE : Ce script suppose que fetch_pool.py a déjà été exécuté.
#        Il lit pool_metadata.csv, télécharge les PDFs des candidats,
#        valide la couche texte et sauvegarde exactement target_count PDFs.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. CHARGEMENT DU POOL
# ---------------------------------------------------------------------------

def load_pool(config: CU1Config) -> pd.DataFrame:
    """Charge le pool de métadonnées généré par fetch_pool.py."""
    if not config.paths.pool_path.exists():
        raise FileNotFoundError(
            f"Pool introuvable : {config.paths.pool_path}\n"
            "→ Lancez d'abord : python WP1_CU1/fetch_pool.py"
        )
    df = pd.read_csv(config.paths.pool_path, encoding="utf-8-sig")
    df["doc_date"] = pd.to_datetime(df["doc_date"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 2. STRATIFICATION
# ---------------------------------------------------------------------------

def compute_strate(row: pd.Series, age_bins: list, age_labels: list) -> str:
    """Calcule la strate : {{année}}_{{sexe}}_{{tranche_age}} — ex. 2019_Homme_50-54ans"""
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
# 3. EXPORT
# ---------------------------------------------------------------------------

_MIN_PDF_BYTES = 2048   # Taille minimale pour un PDF exploitable
_MIN_TEXT_CHARS = 100   # Caractères minimum pour considérer qu'il y a une couche texte


def _has_text_layer(pdf_bytes: bytes) -> bool:
    """Retourne True si le PDF contient une couche texte extractible (pas un scan)."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            chars = 0
            for page in pdf.pages:
                chars += len(page.extract_text() or "")
                if chars >= _MIN_TEXT_CHARS:
                    return True
        return False
    except Exception:
        return False


def _check_one(args: tuple) -> dict:
    """Worker : vérifie la validité du PDF (text layer). Garde les bytes en mémoire si valide."""
    row = args
    doc_id = str(row["doc_id"])
    strate = row["strate"]
    file_id = hash_doc_id(doc_id)

    fil_data = row.get("fil_data")
    is_valid = False
    pdf_bytes = None
    pdf_size_kb = None
    reject_reason = None

    if fil_data is None:
        reject_reason = "no_data"
    else:
        try:
            b = bytes(fil_data) if not isinstance(fil_data, bytes) else fil_data
            if b[:4] != b"%PDF":
                reject_reason = "invalid_magic"
            elif len(b) < _MIN_PDF_BYTES:
                reject_reason = "too_small"
            elif not _has_text_layer(b):
                reject_reason = "no_text_layer"
            else:
                pdf_bytes = b
                pdf_size_kb = round(len(b) / 1024, 1)
                is_valid = True
        except Exception as e:
            reject_reason = f"error:{e}"

    return {
        "file_id": file_id,
        "strate": strate,
        "is_valid": is_valid,
        "pdf_bytes": pdf_bytes,       # None si invalide
        "pdf_size_kb": pdf_size_kb,
        "reject_reason": reject_reason or "",
        "doc_date": row["doc_date"].strftime("%Y-%m-%d") if pd.notna(row["doc_date"]) else "",
        "departement_code": row.get("departement_code", ""),
        "pat_ipp": row.get("pat_ipp", ""),
    }


def validate_candidates(df: pd.DataFrame, config: CU1Config) -> list[dict]:
    """Valide les PDFs en parallèle (sans sauvegarder). Retourne la liste de résultats."""
    rows = [row for _, row in df.iterrows()]

    records = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=config.extraction.max_workers) as pool:
        futures = {pool.submit(_check_one, row): i for i, row in enumerate(rows)}
        with tqdm(total=len(futures), desc=f"Validation PDF ({config.extraction.max_workers} workers)") as pbar:
            for future in as_completed(futures):
                records[futures[future]] = future.result()
                pbar.update(1)

    return records


def save_final(records: list[dict], raw_pdf_dir: Path, txt_dir: Path,
               converter: PdfConverter) -> None:
    """Sauvegarde la sélection finale : le `.txt` (livrable annotation) ET le PDF (traçabilité).

    Le format attendu pour l'annotation est `.txt`, 1 fichier par CR (guide PARTAGES §9.1).
    Le PDF source est conservé en parallèle.
    """
    raw_pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        (raw_pdf_dir / f"{rec['file_id']}.pdf").write_bytes(rec["pdf_bytes"])
        text = converter.from_bytes(rec["pdf_bytes"]) or ""
        (txt_dir / f"{rec['file_id']}.txt").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. STATISTIQUES
# ---------------------------------------------------------------------------

def print_stats(df_final: pd.DataFrame):
    print(f"\n{'=' * 60}")
    print("STATISTIQUES DE L'ÉCHANTILLON FINAL CU1")
    print(f"{'=' * 60}")
    print(f"Documents retenus : {len(df_final)}")
    print("\nRépartition par année :")
    years = pd.to_datetime(df_final["doc_date"], errors="coerce").dt.year
    print(years.value_counts().sort_index().to_string())
    print("\nRépartition par strate (top 10) :")
    print(df_final["strate"].value_counts().head(10).to_string())
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# 5. PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def run_extraction(config: CU1Config = None):
    if config is None:
        config = DEFAULT_CONFIG

    config.paths.ensure_dirs()
    target = config.extraction.target_count
    oversample_target = int(target * config.extraction.oversample_factor)

    # 1. Chargement du pool (généré par fetch_pool.py)
    print(f"📂 Chargement du pool : {config.paths.pool_path}")
    try:
        df_all = load_pool(config)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    print(f"   → {len(df_all):,} documents dans le pool")

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
    print(f"\n⬇️  Téléchargement de {len(df_candidates)} PDFs...")
    conn = pyodbc.connect(config.db.connection_string, timeout=30)
    cursor = conn.cursor()
    file_data_map = {}

    for i in range(0, len(df_candidates), config.extraction.batch_size):
        batch = df_candidates["doc_stockage_id"].iloc[i:i + config.extraction.batch_size].tolist()
        placeholders = ",".join("?" * len(batch))
        try:
            cursor.execute(
                f"SELECT fil_id, fil_data FROM STOCKAGE.stockage.FILES WHERE fil_id IN ({placeholders})",
                batch,
            )
            for row in cursor.fetchall():
                file_data_map[row[0]] = row[1]
        except Exception as e:
            print(f"  ⚠️  Erreur batch {i // config.extraction.batch_size + 1} : {e}")

    conn.close()

    df_candidates = df_candidates.copy()
    df_candidates["fil_data"] = df_candidates["doc_stockage_id"].map(
        lambda x: file_data_map.get(x)
    )

    # 5. Validation en parallèle (text layer, sans sauvegarder)
    print(f"\n🔍 Validation des PDFs (couche texte)...")
    all_results = validate_candidates(df_candidates, config)

    valid_records = [r for r in all_results if r["is_valid"]]
    invalid_records = [r for r in all_results if not r["is_valid"]]

    reject_summary: dict = {}
    for r in invalid_records:
        reject_summary[r["reject_reason"]] = reject_summary.get(r["reject_reason"], 0) + 1

    print(f"   Valides : {len(valid_records)} / {len(all_results)}")
    for reason, count in sorted(reject_summary.items(), key=lambda x: -x[1]):
        print(f"   · {reason}: {count}")

    if len(valid_records) < target:
        print(f"\n⚠️  Seulement {len(valid_records)} PDFs valides (cible : {target})")
        print("   → Augmentez oversample_factor ou sql_pool_size dans config.py.")

    # Les candidats ont été tirés de façon stratifiée → les valides le sont aussi.
    # On prend simplement les `target` premiers valides.
    final_records = valid_records[:target]

    # 7. Sauvegarde sur disque : .txt (livrable) + PDF (traçabilité)
    print(f"\n📁 Sauvegarde de {len(final_records)} CR (.txt + PDF)...")
    converter = PdfConverter(config.paths.java_path, config.paths.pdf_jar_path)
    save_final(final_records, config.paths.raw_pdf_dir, config.paths.txt_dir, converter)

    # 8. Métadonnées + IPP
    df_meta = pd.DataFrame([
        {
            "file_id": r["file_id"],
            "filename": f"{r['file_id']}.txt",
            "strate": r["strate"],
            "frequence_strate_population": round(strate_pop_freq.get(r["strate"], 0), 4),
            "doc_date": r["doc_date"],
            "departement_code": r["departement_code"],
            "pdf_size_kb": r["pdf_size_kb"],
        }
        for r in final_records
    ])
    df_meta.to_csv(config.paths.metadata_path, index=False, encoding="utf-8-sig")

    df_ipp = pd.DataFrame([{"pat_ipp": r["pat_ipp"]} for r in final_records])
    df_ipp.drop_duplicates().dropna().to_csv(config.paths.ipp_path, index=False, encoding="utf-8-sig")

    print_stats(df_meta)
    print(f"✅ Extraction terminée !")
    print(f"   CR sauvegardés    : {len(final_records)}  (.txt + PDF)")
    print(f"   Dossier TXT       : {config.paths.txt_dir}")
    print(f"   Dossier PDF       : {config.paths.raw_pdf_dir}")
    print(f"   Métadonnées       : {config.paths.metadata_path}")
    print(f"   IPP               : {config.paths.ipp_path}  ({df_ipp['pat_ipp'].nunique()} patients distincts)")


# ---------------------------------------------------------------------------
# 6. POINT D'ENTRÉE
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = DEFAULT_CONFIG

    # Le mot de passe est nécessaire uniquement pour télécharger les binaires.
    if not config.db.password:
        import getpass
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    run_extraction(config)
