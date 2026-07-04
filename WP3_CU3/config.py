"""
Configuration pour l'extraction CU3 - Résumé automatique des CR médicaux
Hôpital Foch / Projet PARTAGES

Périmètre (guide PARTAGES v29.01.26, section 6) :
  - CR récents (fenêtre retenue : 2020 → aujourd'hui, voir docs/methodologie_extraction_CU3.md)
  - Tous CR médicaux par exclusion (ordonnances et documents non cliniques exclus)
    + OBLIGATOIRE : une conclusion bien définie et identifiée (balises ancres, FAQ #10)
  - Volume : min 100 / idéal 400 / max 1000
  - Format sortie : 2 fichiers .txt par CR — corps sans conclusion + conclusion seule
    (suffixe « _conclusion ») ; strate incluse dans le NOM des fichiers (§6.4)
  - Pas d'annotation pour ce CU

Sélection sur couche texte native uniquement : les documents sans texte extractible
(scans à océriser) sont ÉCARTÉS (pas d'OCR fiable) → aucun suffixe « _ocr ».
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Charge .env depuis la racine du projet (un niveau au-dessus de WP3_CU3/)
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
    """Paramètres d'extraction selon le guide PARTAGES CU3"""

    # --- Volume cible (guide PARTAGES §3) ---
    target_count: int = 400     # Idéal
    min_count: int = 100        # Minimum requis
    max_count: int = 1000       # Plafond

    # --- Critères temporels ---
    # Guide §6.2 : « CR relativement récents, datant au plus tard entre 2020-2022 »
    # → lecture retenue : CR datés de 2020 ou après (voir méthodologie CU3).
    date_min: str = "2020-01-01"
    date_max: str = "2026-12-31"

    # --- Documents non cliniques exclus (mêmes motifs que CU1) ---
    # Le guide CU3 exclut explicitement les ordonnances (« ordonnance », « prescription »).
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
        # Formulaires sociaux sans contenu clinique à résumer (balise « SYNTHESE »
        # de template → faux positifs observés au 2e run)
        "%contexte de vie%",
    ])

    # --- Détection de la conclusion (balises ancres, FAQ #10 du guide) ---
    # Matching insensible à la casse et aux accents, en début de ligne,
    # dernière occurrence retenue. Voir utils/conclusion_splitter.py.
    conclusion_anchors: list = field(default_factory=lambda: [
        "EN CONCLUSION",
        "CONCLUSIONS",
        "CONCLUSION",
        "AU TOTAL",
        "EN SYNTHESE",
        "SYNTHESE",
        "EN RESUME",
    ])
    min_conclusion_chars: int = 40      # chars non blancs min de la conclusion
    min_body_chars: int = 300           # chars non blancs min du corps (matière à résumer)
    max_conclusion_ratio: float = 0.6   # la conclusion ne doit pas dominer le document
    # Rejet des documents aberrants (exports cumulatifs type dossier complet,
    # > 150k chars non blancs ≈ 50+ pages) : ce ne sont pas des CR à résumer.
    max_doc_chars: int = 150_000

    # --- Stratification (année × sexe × tranche d'âge, comme CU1) ---
    age_bins: list = field(default_factory=lambda: [0, 18, 30, 40, 50, 55, 60, 65, 70, 80, 120])
    age_labels: list = field(default_factory=lambda: [
        "0-17ans", "18-29ans", "30-39ans", "40-49ans",
        "50-54ans", "55-59ans", "60-64ans", "65-69ans", "70-79ans", "80ans+"
    ])

    # --- Batch size pour les requêtes SQL ---
    batch_size: int = 500

    # --- Pré-sélection SQL (TOP N aléatoire) avant stratification Python ---
    sql_pool_size: int = 20_000

    # --- Sur-échantillonnage ---
    # Plus élevé que CU1 (3.0) : en plus des rejets « pas de couche texte »,
    # le CU3 rejette les CR sans conclusion détectable.
    oversample_factor: float = 5.0

    # --- Parallélisme ---
    max_workers: int = 6

    # --- Noms de colonnes NOYAU.patient.PATIENT ---
    col_sexe: str = "pat_sexe"
    col_date_naissance: str = "pat_date_naissance"


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
        return Path(self.output_dir) / "metadata_cu3.csv"

    @property
    def ipp_path(self) -> Path:
        """IPP patients — usage interne, NON livré à PARTAGES."""
        return Path(self.output_dir) / "ipp_cu3.csv"

    def ensure_dirs(self):
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.txt_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class CU3Config:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def set_password(self, password: str):
        self.db.password = password


DEFAULT_CONFIG = CU3Config()
