"""
Configuration pour l'extraction CU5b - Analyse de la réponse aux traitements en oncologie
Hôpital Foch / Projet PARTAGES

Périmètre (guide PARTAGES v29.01.26, section 8) :
  - CR de consultation (doc_type_code = 7) du service d'oncologie uniquement
  - CR datant de 2010 ou après
  - Volume : min 100 / idéal 500 / max 1000
  - Format sortie : .txt (1 fichier / CR)
  - Métadonnées obligatoires : N/A ; facultatif : localisation, dates de traitements, date du CR

Sélection sur couche texte native uniquement : les documents sans texte extractible
(scans à océriser) sont ÉCARTÉS car il n'existe pas de méthode d'OCR fiable.

Liaison oncologie : doc → VENUE (doc_venue_id) → SEJOUR (ven_id) → sej_uf_medicale_code ∈ UF onco
(doc_cr_code = Centre de Responsabilité, ≠ UF → ne PAS l'utiliser)
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
    """Paramètres d'extraction CU5b"""

    # --- Type de document : 7 = "Compte-rendu consultation" ---
    doc_type_code: int = 7

    # --- UF du service d'oncologie (NOYAU.coeur.UF) ---
    # 324A/324E = ONCOLOGIE, 324B = ONCOLOGIE HDJ (oncologie clinique).
    # Élargir si besoin : 325B (prévention), 328A/B/E (soins de support), 547A (soins palliatifs onco).
    oncology_uf_codes: list = field(default_factory=lambda: ["324A", "324E", "324B"])

    # --- Critères temporels ---
    date_min: str = "2010-01-01"
    date_max: str = "2026-12-31"

    # --- Volume cible (guide : min 100, idéal 500, max 1000) ---
    target_count: int = 500
    min_count: int = 100
    max_count: int = 1000

    # --- Pré-sélection SQL (pool aléatoire) ---
    sql_pool_size: int = 6_000

    # --- Sur-échantillonnage (consultations = texte natif, validité élevée) ---
    oversample_factor: float = 2.0

    # --- Parallélisme ---
    max_workers: int = 6
    batch_size: int = 200

    # --- Seuil de validité texte (caractères NON BLANCS) ---
    # Un document dont la couche texte native contient moins de min_text_chars
    # caractères non blancs est ÉCARTÉ : soit c'est un scan à océriser (pas d'OCR
    # fiable), soit un PDF « vide » (about:blank imprimé, enveloppe de messagerie
    # sécurisée…) dont le texte n'est que des espaces + quelques libellés.
    min_text_chars: int = 200


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
        return Path(self.output_dir) / "metadata_cu5b.csv"

    @property
    def ipp_path(self) -> Path:
        """IPP patients — usage interne, NON livré à PARTAGES."""
        return Path(self.output_dir) / "ipp_cu5b.csv"

    def ensure_dirs(self):
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.txt_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class CU5bConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def set_password(self, password: str):
        self.db.password = password


DEFAULT_CONFIG = CU5bConfig()
