"""
Configuration pour l'extraction CU2 - Codage CIM-10 depuis CRH
Hôpital Foch / Projet PARTAGES
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
    """Paramètres d'extraction pour CU2"""

    # --- Années à couvrir ---
    years: list = field(default_factory=lambda: [2023, 2024, 2025])

    # --- Volume cible ---
    target_count: int = 1000

    # --- Filtre ambulatoire (durée séjour = 0 jours) ---
    only_ambulatoire: bool = True

    # --- Filtre GHM (liste blanche) ---
    # Laisser vide pour ne pas filtrer par GHM.
    # Renseigner avec les GHM de l'annexe fournie par le porteur du projet.
    # Exemple : ["28Z07Z", "28Z14Z", ...]
    ghm_whitelist: list = field(default_factory=list)

    # --- Patterns de noms de documents CRH (Compte-Rendu Hospitalisation) ---
    crh_doc_patterns: list = field(default_factory=lambda: [
        "%Fiche Hospitalisation%",
        "%Compte-Rendu%Hospitalisation%",
        "%Compte Rendu%Hospitalisation%",
        "%CRH%",
        "%CR Hospitalisation%",
        "%Lettre de Liaison%",
    ])

    # --- Patterns de noms de documents CRO (Compte-Rendu Opératoire) ---
    cro_doc_patterns: list = field(default_factory=lambda: [
        "%Compte-Rendu%Opératoire%",
        "%Compte Rendu%Operatoire%",
        "%Compte-Rendu%Operatoire%",
        "%CRO%",
        "%CR Opératoire%",
        "%Compte Rendu Opératoire%",
    ])

    # --- Mapping GHM → Spécialité médicale ---
    # Préfixe du GHM (2 premiers caractères) → libellé spécialité
    # Complétez selon le référentiel ATIH ou l'annexe PARTAGES.
    ghm_to_specialite: dict = field(default_factory=lambda: {
        "01": "Système nerveux",
        "02": "Œil",
        "03": "ORL - Stomatologie",
        "04": "Appareil respiratoire",
        "05": "Appareil circulatoire",
        "06": "Appareil digestif",
        "07": "Foie - Pancréas - Voies biliaires",
        "08": "Appareil musculo-squelettique",
        "09": "Peau - Tissu sous-cutané - Sein",
        "10": "Endocrinologie - Nutrition",
        "11": "Reins - Voies urinaires",
        "12": "Appareil génital masculin",
        "13": "Appareil génital féminin",
        "14": "Grossesse - Accouchement - Puerpéralité",
        "15": "Nouveau-nés - Nourrissons",
        "16": "Sang - Organes hématopoïétiques",
        "17": "Affections myéloprolifératives - Tumeurs malignes",
        "18": "Maladies infectieuses - Parasitaires",
        "19": "Santé mentale",
        "20": "Consommation alcool - Drogues",
        "21": "Traumatismes - Empoisonnements",
        "22": "Brûlures",
        "23": "Facteurs influant sur l'état de santé",
        "24": "Séjours de moins de 2 jours",
        "25": "VIH",
        "26": "Traumatismes crâniens - Lésions cérébrales",
        "27": "Transplantations d'organes",
        "28": "Séances",
        "90": "Erreurs et autres séjours",
    })

    # --- Tolérance jours pour liaison par dates ---
    tolerance_days: int = 3

    # --- Taille batch pour requêtes SQL ---
    batch_size: int = 200

    # --- Chemin RSS ---
    rss_base_path: str = r"S:\Envoi-EDS-PMSI"


@dataclass
class PathConfig:
    """Chemins de fichiers"""

    output_dir: str = str(Path(__file__).parent / "output")

    # Java + jar pour conversion PDF → TXT
    java_path: str = os.environ.get(
        "JAVA_PATH",
        r"C:\Users\benysar\Downloads\sqldeveloper-24.3.0.284.2209-x64\sqldeveloper\jdk\jre\bin\java.exe",
    )
    pdf_jar_path: str = os.environ.get(
        "PDF_JAR_PATH",
        r"C:\Users\benysar\Documents\GitHub\BTB_extraction\src\extraction\pdftotext-jar-with-dependencies.jar",
    )

    @property
    def pool_rss_path(self) -> Path:
        return Path(self.output_dir) / "pool_rss.csv"

    @property
    def output_csv_path(self) -> Path:
        return Path(self.output_dir) / "cu2_dataset.csv"

    @property
    def stats_path(self) -> Path:
        return Path(self.output_dir) / "cu2_stats.csv"

    @property
    def cim10_freq_path(self) -> Path:
        """Distribution complète des CIM-10 DP (métadonnée obligatoire du guide §5.4)."""
        return Path(self.output_dir) / "cu2_cim10_frequency.csv"

    @property
    def correspondence_path(self) -> Path:
        """Table de correspondance ID anonymisé ↔ numero_admin réel (usage interne)."""
        return Path(self.output_dir) / "cu2_correspondance_INTERNE.csv"

    def ensure_dirs(self):
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)


@dataclass
class CU2Config:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def set_password(self, password: str):
        self.db.password = password


DEFAULT_CONFIG = CU2Config()
