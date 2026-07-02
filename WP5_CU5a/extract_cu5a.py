"""
Étape 2/2 — Extraction CU5a - Identification automatique des biomarqueurs en oncologie
Hôpital Foch / Projet PARTAGES

Critères (guide PARTAGES v29.01.26, section 7) :
  - CR anapath (doc_type_code=5) + génétique/génomique (doc_type_code=127), datés ≥ 2010
  - Volume : 150 CR (fixe)
  - Échantillon équilibré par type de cancer → localisation déduite des codes CIM-10 'C'
    récupérés dans les RSS PMSI (lecteur S:) via les venues du patient
  - Texte : couche native uniquement (pdfplumber). Les documents sans couche texte
    exploitable (scans à océriser) sont ÉCARTÉS — aucune méthode d'OCR fiable (voir §5 doc).
  - Sorties : output/txt/*.txt, metadata_cu5a.csv, ipp_cu5a.csv (interne)

NOTE : Lancez d'abord python WP5_CU5a/fetch_pool.py pour générer pool_metadata.csv.
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

import pyodbc
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CU5aConfig, DEFAULT_CONFIG
from utils.pdf_converter import PdfConverter, hash_doc_id
from utils.rss_parser import RSSParser


# ---------------------------------------------------------------------------
# 1. CHARGEMENT DU POOL
# ---------------------------------------------------------------------------

def load_pool(config: CU5aConfig) -> pd.DataFrame:
    if not config.paths.pool_path.exists():
        raise FileNotFoundError(
            f"Pool introuvable : {config.paths.pool_path}\n"
            "→ Lancez d'abord : python WP5_CU5a/fetch_pool.py"
        )
    df = pd.read_csv(config.paths.pool_path, encoding="utf-8-sig", dtype={"ven_numero": str})
    df["doc_date"] = pd.to_datetime(df["doc_date"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 2. LOCALISATION TUMORALE (codes CIM-10 'C' via RSS PMSI)
# ---------------------------------------------------------------------------

def _range_bounds(key: str) -> tuple[int, int]:
    """'C15-C26' → (15, 26)."""
    lo, hi = key.split("-")
    return int(lo[1:3]), int(hi[1:3])


def cim_to_localisation(code: str, mapping: dict) -> str | None:
    """Mappe un code CIM-10 'C..' vers un groupe de localisation. None si non cancéreux."""
    code = (code or "").strip().upper()
    if not code.startswith("C"):
        return None
    digits = ""
    for ch in code[1:]:
        if ch.isdigit():
            digits += ch
        else:
            break
    if len(digits) < 2:
        return None
    n = int(digits[:2])
    for key, label in mapping.items():
        lo, hi = _range_bounds(key)
        if lo <= n <= hi:
            return label
    return "Autre cancer (C divers)"


def build_patient_localisation(cursor, pat_ids: list, config: CU5aConfig) -> dict:
    """
    Construit {doc_pat_id: localisation_tumorale_dominante} via :
      patient → toutes ses venues (ven_numero) → RSS (numero_admin) → codes CIM-10 'C'.
    """
    ex = config.extraction
    ids = sorted({int(p) for p in pat_ids if pd.notna(p)})

    # 1. Toutes les venues (ven_numero) des patients du pool
    patient_venues: dict[int, set] = defaultdict(set)
    print(f"   • Récupération des venues de {len(ids):,} patients...")
    for i in range(0, len(ids), ex.batch_size):
        batch = ids[i:i + ex.batch_size]
        ph = ",".join("?" * len(batch))
        try:
            cursor.execute(
                f"SELECT pat_id, ven_numero FROM NOYAU.patient.VENUE "
                f"WHERE pat_id IN ({ph}) AND ven_numero IS NOT NULL",
                batch,
            )
            for pat_id, ven_numero in cursor.fetchall():
                patient_venues[int(pat_id)].add(str(ven_numero).strip())
        except Exception as e:
            print(f"     ⚠️ Erreur batch venues : {e}")

    # 2. Parsing RSS → {numero_admin: [localisations]}
    print(f"   • Parsing RSS PMSI {ex.rss_years} depuis {ex.rss_base_path} ...")
    parser = RSSParser(ex.rss_base_path)
    sejours = parser.parse_years(ex.rss_years)
    admin_to_locs: dict[str, list] = defaultdict(list)
    for s in sejours:
        na = (s.numero_admin_sejour or "").strip()
        if not na:
            continue
        for code in [s.diagnostic_principal, s.diagnostic_relie, *s.diagnostics_associes]:
            if code and code.strip().upper().startswith("C"):
                admin_to_locs[na].append(cim_to_localisation(code, ex.cim_localisation_map))
    print(f"     → {len(admin_to_locs):,} séjours RSS avec un code cancer (C)")

    # 3. Localisation dominante par patient
    patient_loc: dict[int, str] = {}
    for pat_id, venues in patient_venues.items():
        locs = []
        for v in venues:
            locs.extend(admin_to_locs.get(v, []))
        locs = [l for l in locs if l]
        if locs:
            patient_loc[pat_id] = Counter(locs).most_common(1)[0][0]
    print(f"     → {len(patient_loc):,} patients avec une localisation tumorale identifiée")
    return patient_loc


# ---------------------------------------------------------------------------
# 3. ÉCHANTILLONNAGE ÉQUILIBRÉ PAR LOCALISATION
# ---------------------------------------------------------------------------

def balanced_allocation(sizes: dict, target: int) -> dict:
    """Répartit `target` le plus équitablement possible entre groupes (water-filling)."""
    groups = list(sizes.keys())
    alloc = {g: 0 for g in groups}
    remaining = target
    while remaining > 0:
        open_groups = [g for g in groups if alloc[g] < sizes[g]]
        if not open_groups:
            break
        share = max(1, remaining // len(open_groups))
        for g in open_groups:
            add = min(share, sizes[g] - alloc[g], remaining)
            alloc[g] += add
            remaining -= add
            if remaining <= 0:
                break
    return alloc


def balanced_sample(df: pd.DataFrame, target: int, group_col: str,
                    random_state: int = 42) -> pd.DataFrame:
    """Tirage équilibré par groupe (localisation)."""
    if len(df) <= target:
        return df.copy()
    sizes = df[group_col].value_counts().to_dict()
    alloc = balanced_allocation(sizes, target)
    parts = []
    for g, n in alloc.items():
        if n > 0:
            sub = df[df[group_col] == g]
            parts.append(sub.sample(n=min(n, len(sub)), random_state=random_state))
    return pd.concat(parts).sample(frac=1, random_state=random_state).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. TÉLÉCHARGEMENT + EXTRACTION TEXTE (native ou OCR)
# ---------------------------------------------------------------------------

def download_binaries(cursor, stockage_ids: list, batch_size: int) -> dict:
    """Télécharge fil_data + fil_data_fs pour une liste de doc_stockage_id."""
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
    """Worker : extrait la couche texte native d'un document.

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
        "doc_type_code": int(row["doc_type_code"]),
        "type": ex.type_labels.get(int(row["doc_type_code"]), str(row["doc_type_code"])),
        "localisation": row.get("localisation", "Inconnue"),
        "doc_date": row["doc_date"].strftime("%Y-%m-%d") if pd.notna(row["doc_date"]) else "",
        "cr_code": row.get("cr_code", ""),
        "pat_ipp": row.get("pat_ipp", ""),
        "text": text if valid else None,
        "text_chars": len(text) if text else 0,
        "is_valid": valid,
    }


def extract_candidates(df: pd.DataFrame, file_map: dict, converter: PdfConverter,
                       config: CU5aConfig) -> list[dict]:
    args_list = []
    for _, row in df.iterrows():
        fil_data, fil_data_fs = file_map.get(row["doc_stockage_id"], (None, None))
        args_list.append((row, fil_data, fil_data_fs, converter, config))

    records = [None] * len(args_list)
    workers = config.extraction.max_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_one, a): i for i, a in enumerate(args_list)}
        with tqdm(total=len(futures), desc=f"Extraction texte/OCR ({workers} workers)") as pbar:
            for fut in as_completed(futures):
                records[futures[fut]] = fut.result()
                pbar.update(1)
    return records


# ---------------------------------------------------------------------------
# 5. SAUVEGARDE
# ---------------------------------------------------------------------------

def save_outputs(records: list[dict], df_for_freq: pd.DataFrame, config: CU5aConfig):
    txt_dir = config.paths.txt_dir
    txt_dir.mkdir(parents=True, exist_ok=True)

    freq = df_for_freq["localisation"].value_counts(normalize=True).to_dict()

    meta_rows = []
    for r in records:
        filename = f"{r['file_id']}.txt"
        (txt_dir / filename).write_text(r["text"], encoding="utf-8")
        meta_rows.append({
            "file_id": r["file_id"],
            "filename": filename,
            "type": r["type"],
            "localisation": r["localisation"],
            "frequence_localisation_pool": round(freq.get(r["localisation"], 0), 4),
            "doc_date": r["doc_date"],
            "cr_code": r["cr_code"],
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
    print("STATISTIQUES DE L'ÉCHANTILLON FINAL CU5a")
    print(f"{'=' * 60}")
    print(f"Documents retenus : {len(df_meta)}")
    print("\nPar type de document :")
    print(df_meta["type"].value_counts().to_string())
    print("\nPar localisation tumorale :")
    print(df_meta["localisation"].value_counts().to_string())
    print(f"{'=' * 60}\n")


# ---------------------------------------------------------------------------
# 6. PIPELINE PRINCIPAL
# ---------------------------------------------------------------------------

def run_extraction(config: CU5aConfig = None):
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

    print("ℹ️  Sélection sur couche texte native uniquement : les documents à océriser "
          "(scans, ex. génétique) sont écartés (pas de méthode d'OCR fiable).")

    # 2. Connexion DB
    print("\n🔗 Connexion à Easily...")
    try:
        conn = pyodbc.connect(config.db.connection_string, timeout=30)
    except Exception as e:
        print(f"❌ Connexion échouée : {e}")
        return
    cursor = conn.cursor()

    # 3. Localisation tumorale par patient (via RSS)
    print("\n🧬 Détermination de la localisation tumorale (RSS PMSI)...")
    try:
        patient_loc = build_patient_localisation(cursor, df_all["doc_pat_id"].tolist(), config)
    except Exception as e:
        print(f"⚠️  Localisation RSS impossible ({e}) — tirage non stratifié.")
        patient_loc = {}

    df_all["localisation"] = df_all["doc_pat_id"].map(
        lambda p: patient_loc.get(int(p)) if pd.notna(p) else None
    ).fillna("Inconnue")

    print("\n📊 Répartition des localisations dans le pool :")
    print(df_all["localisation"].value_counts().to_string())

    # 4. Sur-échantillonnage équilibré
    df_candidates = balanced_sample(df_all, oversample_target, "localisation")
    print(f"\n   Candidats tirés : {len(df_candidates)} (cible finale : {target})")

    # 5. Téléchargement binaires
    print(f"\n⬇️  Téléchargement de {len(df_candidates)} fichiers...")
    file_map = download_binaries(
        cursor, df_candidates["doc_stockage_id"].tolist(), config.extraction.batch_size
    )
    conn.close()

    # 6. Extraction du texte natif (documents à océriser écartés)
    converter = PdfConverter(config.paths.java_path, config.paths.pdf_jar_path)
    records = extract_candidates(df_candidates, file_map, converter, config)

    valid = [r for r in records if r["is_valid"]]
    n_dropped = len(records) - len(valid)
    print(f"\n   Valides : {len(valid)} / {len(records)}  "
          f"(écartés faute de couche texte native : {n_dropped})")
    if len(valid) < target:
        print(f"⚠️  Seulement {len(valid)} documents exploitables (cible : {target}).")
        print("    → Augmentez sql_pool_size / oversample_factor dans config.py.")

    # 7. Sélection finale équilibrée parmi les valides
    df_valid = pd.DataFrame(valid)
    df_final = balanced_sample(df_valid, target, "localisation")
    final_ids = set(df_final["file_id"])
    final_records = [r for r in valid if r["file_id"] in final_ids]

    # 8. Sauvegarde (fréquence des localisations calculée sur tout le pool = proxy population)
    print(f"\n📁 Sauvegarde de {len(final_records)} fichiers .txt...")
    df_meta = save_outputs(final_records, df_all, config)

    print_stats(df_meta)
    print("✅ Extraction CU5a terminée !")
    print(f"   Fichiers .txt : {config.paths.txt_dir}")
    print(f"   Métadonnées   : {config.paths.metadata_path}")
    print(f"   IPP (interne) : {config.paths.ipp_path}")


if __name__ == "__main__":
    import getpass

    config = DEFAULT_CONFIG
    if not config.db.password:
        config.db.password = getpass.getpass("Mot de passe Easily (SITE_READER_BO) : ")

    run_extraction(config)
