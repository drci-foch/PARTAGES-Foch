"""
Configuration pour l'extraction CU1 - Pseudonymisation des CR médicaux
Hôpital Foch / Projet PARTAGES
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Charge .env depuis la racine du projet (un niveau au-dessus de WP1_CU1/)
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
    """Paramètres d'extraction selon le guide PARTAGES CU1"""

    # --- Volume cible (guide PARTAGES) ---
    target_count: int = 400     # Idéal
    min_count: int = 100        # Minimum requis
    max_count: int = 1000       # Plafond

    # --- Critères temporels ---
    date_min: str = "2015-01-01"    # CR datant de moins de 10 ans (> 2015)
    date_max: str = "2025-12-31"    # Jusqu'à aujourd'hui

    # --- Types de CR médicaux à inclure (tous types de CR hors admin) ---
    # On exclut les documents non cliniques (arrêts de travail, transport, etc.)
    doc_exclusion_patterns: list = field(default_factory=lambda: [
        "%arret de travail%",
        "%arrêt de travail%",
        "%transport%",
        "%protocole de soin%",
        "%ordonnance%",
        "%prescription%",
        "%consentement%",
        "%facture%",
        "%administratif%",
    ])

    # --- Stratification (par année, sexe, tranche d'âge) ---
    age_bins: list = field(default_factory=lambda: [0, 18, 30, 40, 50, 55, 60, 65, 70, 80, 120])
    age_labels: list = field(default_factory=lambda: [
        "0-17ans", "18-29ans", "30-39ans", "40-49ans",
        "50-54ans", "55-59ans", "60-64ans", "65-69ans", "70-79ans", "80ans+"
    ])

    # --- Batch size pour les requêtes SQL ---
    batch_size: int = 500

    # --- Pré-sélection SQL (TOP N) avant stratification Python ---
    # Évite de charger des millions de documents en mémoire.
    # On tire sql_pool_size docs aléatoires côté SQL, puis on stratifie en Python.
    # Règle : sql_pool_size >> target_count (x20 minimum pour avoir toutes les strates)
    sql_pool_size: int = 20_000

    # --- Sur-échantillonnage pour garantir target_count PDFs valides ---
    # On télécharge target_count * oversample_factor candidats, on filtre (text layer),
    # puis on re-stratifie exactement target_count parmi les valides.
    oversample_factor: float = 3.0

    # --- Parallélisme ---
    max_workers: int = 6

    # --- Noms de colonnes NOYAU.patient.PATIENT ---
    # Convention de nommage Easily : préfixe pat_
    # À vérifier avec : SELECT TOP 1 * FROM NOYAU.patient.PATIENT
    col_sexe: str = "pat_sexe"
    col_date_naissance: str = "pat_date_naissance"


@dataclass
class PathConfig:
    """Chemins de fichiers"""

    # Répertoire de sortie par défaut
    output_dir: str = str(Path(__file__).parent / "output")

    # Outils de conversion PDF → TXT (Java)
    java_path: str = os.environ.get(
        "JAVA_PATH",
        r"C:\Users\benysar\Downloads\sqldeveloper-24.3.0.284.2209-x64\sqldeveloper\jdk\jre\bin\java.exe"
    )
    pdf_jar_path: str = os.environ.get(
        "PDF_JAR_PATH",
        r"C:\Users\benysar\Documents\GitHub\BTB_extraction\src\extraction\pdftotext-jar-with-dependencies.jar"
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
        return Path(self.output_dir) / "metadata_cu1.csv"

    @property
    def ipp_path(self) -> Path:
        return Path(self.output_dir) / "ipp_cu1.csv"

    def ensure_dirs(self):
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class CU1Config:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def set_password(self, password: str):
        self.db.password = password


DEFAULT_CONFIG = CU1Config()
