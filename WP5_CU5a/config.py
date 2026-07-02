"""
Configuration pour l'extraction CU5a - Identification automatique des biomarqueurs en oncologie
Hôpital Foch / Projet PARTAGES

Périmètre (guide PARTAGES v29.01.26, section 7) :
  - CR d'anatomopathologie + génomique tumorale (résultats IHC, FISH, NGS)
  - CR datant de 2010 ou après
  - Volume : exactement 150 (min = idéal = max)
  - Échantillon équilibré par type de cancer (localisation déduite des codes CIM-10 C via RSS PMSI)
  - Format sortie : .txt (1 fichier / CR)
  - Métadonnées obligatoires : N/A ; facultatif : localisation du cancer

Sélection sur couche texte native uniquement : les documents sans texte extractible
(scans à océriser, ex. génétique) sont ÉCARTÉS car il n'existe pas de méthode d'OCR fiable.

Liaison Easily : DOCUMENTS.doc_type_code  (5 = CR anapath, 127 = Génétique)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass
class DatabaseConfig:
    """Connexion à Easily (SQL Server via ODBC)"""

    server: str = os.environ.get("EASILY_DB_SERVER", "srvapp600")
    database: str = os.environ.get("EASILY_DB_DATABASE", "master")
    username: str = os.environ.get("EASILY_DB_USERNAME", "SITE_READER_BO")
    password: str = os.environ.get("EASILY_DB_PASSWORD", "")
    port: int = 1433

    @property
    def connection_string(self) -> str:
        return (
            f"DRIVER={{SQL Server}};"
            f"SERVER={self.server},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"PWD={self.password};"
            f"TrustServerCertificate=yes"
        )


@dataclass
class ExtractionConfig:
    """Paramètres d'extraction CU5a"""

    # --- Types de documents (référentiel TYPE_DOCUMENT) ---
    # 5 = "Compte-rendu anapath" (texte natif, Foch)
    # 127 = "Génétique" (souvent des scans Institut Curie → écartés faute de couche texte)
    doc_type_codes: list = field(default_factory=lambda: [5, 127])
    type_labels: dict = field(default_factory=lambda: {5: "anapath", 127: "genetique"})

    # --- Critères temporels ---
    date_min: str = "2010-01-01"
    date_max: str = "2026-12-31"

    # --- Volume cible (fixe à 150 selon le guide) ---
    target_count: int = 150
    min_count: int = 150
    max_count: int = 150

    # --- Pré-sélection SQL (pool aléatoire) avant stratification ---
    sql_pool_size: int = 8_000

    # --- Sur-échantillonnage pour garantir target_count fichiers exploitables ---
    oversample_factor: float = 3.0

    # --- Parallélisme extraction texte ---
    max_workers: int = 6
    batch_size: int = 200

    # --- Localisation tumorale via RSS PMSI (codes CIM-10 commençant par 'C') ---
    rss_base_path: str = r"S:\Envoi-EDS-PMSI"
    # Années de RSS à parser pour reconstituer le profil cancéreux des patients.
    # Plus large = meilleure couverture, mais limité par les fichiers réellement présents sur S:\.
    rss_years: list = field(default_factory=lambda: [2019, 2020, 2021, 2022, 2023, 2024, 2025])

    # Mapping préfixe code CIM-10 (cancers C00-C97) → localisation tumorale (groupe)
    # Utilisé pour équilibrer l'échantillon par type de cancer.
    cim_localisation_map: dict = field(default_factory=lambda: {
        "C00-C14": "Lèvre, cavité buccale, pharynx",
        "C15-C26": "Appareil digestif",
        "C30-C39": "Appareil respiratoire et thorax",
        "C40-C41": "Os et cartilage articulaire",
        "C43-C44": "Peau (mélanome et autres)",
        "C45-C49": "Tissus mésothéliaux et mous",
        "C50-C50": "Sein",
        "C51-C58": "Organes génitaux féminins",
        "C60-C63": "Organes génitaux masculins",
        "C64-C68": "Voies urinaires",
        "C69-C72": "Œil, encéphale, SNC",
        "C73-C75": "Thyroïde et glandes endocrines",
        "C76-C80": "Sièges mal définis / secondaires",
        "C81-C96": "Tissus lymphoïde et hématopoïétique",
    })

    # --- Seuils de validité texte ---
    # Un document dont la couche texte native fait moins de min_text_chars caractères
    # est considéré comme un scan à océriser → ÉCARTÉ (pas d'OCR fiable).
    min_text_chars: int = 100


@dataclass
class PathConfig:
    """Chemins de fichiers"""

    output_dir: str = str(Path(__file__).parent / "output")

    java_path: str = os.environ.get(
        "JAVA_PATH",
        r"C:\Users\benysar\Downloads\sqldeveloper-24.3.0.284.2209-x64\sqldeveloper\jdk\jre\bin\java.exe",
    )
    pdf_jar_path: str = os.environ.get(
        "PDF_JAR_PATH",
        r"C:\Users\benysar\Documents\GitHub\BTB_extraction\src\extraction\pdftotext-jar-with-dependencies.jar",
    )

    @property
    def raw_pdf_dir(self) -> Path:
        return Path(self.output_dir) / "raw_pdf"

    @property
    def txt_dir(self) -> Path:
        return Path(self.output_dir) / "txt"

    @property
    def pool_path(self) -> Path:
        return Path(self.output_dir) / "pool_metadata.csv"

    @property
    def metadata_path(self) -> Path:
        return Path(self.output_dir) / "metadata_cu5a.csv"

    @property
    def ipp_path(self) -> Path:
        """IPP patients — usage interne, NON livré à PARTAGES."""
        return Path(self.output_dir) / "ipp_cu5a.csv"

    def ensure_dirs(self):
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.txt_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class CU5aConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def set_password(self, password: str):
        self.db.password = password


DEFAULT_CONFIG = CU5aConfig()
