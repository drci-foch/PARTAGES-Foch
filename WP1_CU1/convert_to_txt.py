"""
Conversion PDF → TXT pour le CU1
Hôpital Foch / Projet PARTAGES

Génère les fichiers .txt (livrable pour l'annotation, guide PARTAGES §9.1) à partir
des PDF déjà extraits dans output/raw_pdf/. Ne touche PAS à la base de données.

À lancer après extract_cu1.py (qui produit désormais les .txt directement), ou pour
(re)générer les .txt à partir de PDF déjà présents.

Usage :
    python WP1_CU1/convert_to_txt.py
"""

import sys
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.pdf_converter import PdfConverter
from config import CU1Config, DEFAULT_CONFIG


def convert_all(config: CU1Config = None):
    if config is None:
        config = DEFAULT_CONFIG

    raw_dir = config.paths.raw_pdf_dir
    txt_dir = config.paths.txt_dir

    if not raw_dir.exists():
        print(f"❌ Dossier PDF introuvable : {raw_dir}")
        print("   → Lancez d'abord l'extraction : python WP1_CU1/extract_cu1.py")
        return

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        print(f"⚠️  Aucun PDF dans {raw_dir}")
        return

    txt_dir.mkdir(parents=True, exist_ok=True)
    converter = PdfConverter(config.paths.java_path, config.paths.pdf_jar_path)

    print(f"📄 Conversion de {len(pdfs)} PDF → TXT vers {txt_dir}")
    n_ok, n_empty = 0, 0
    for pdf in tqdm(pdfs, desc="PDF → TXT"):
        try:
            text = converter.from_bytes(pdf.read_bytes()) or ""
        except Exception as e:
            text = ""
            print(f"  ⚠️ {pdf.name} : {e}")
        (txt_dir / f"{pdf.stem}.txt").write_text(text, encoding="utf-8")
        if text.strip():
            n_ok += 1
        else:
            n_empty += 1

    print(f"\n✅ {n_ok} fichiers .txt générés dans {txt_dir}")
    if n_empty:
        print(f"⚠️  {n_empty} PDF sans texte extractible (.txt vide) — à vérifier")


if __name__ == "__main__":
    convert_all()
