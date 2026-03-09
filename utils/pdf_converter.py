"""
Conversion PDF → TXT
Stratégie :
  1. fil_data_fs non-null → texte natif décodé directement
  2. fil_data (PDF binaire) → pdfplumber (Python, pas de Java)
  3. Fallback Java jar si pdfplumber n'est pas disponible
"""

import hashlib
import io
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False


class PdfConverter:

    def __init__(self, java_path: str = "", jar_path: str = ""):
        self.java_path = java_path
        self.jar_path = jar_path
        self._java_available = bool(java_path and jar_path and Path(java_path).exists() and Path(jar_path).exists())

        if _PDFPLUMBER_AVAILABLE:
            print("✅ Convertisseur PDF : pdfplumber")
        elif self._java_available:
            print("✅ Convertisseur PDF : Java jar (fallback)")
        else:
            print("⚠️  Aucun convertisseur PDF disponible — seuls les documents texte natifs seront traités.")
            print("   → Installer pdfplumber : pip install pdfplumber")

    def from_bytes(self, pdf_bytes: bytes) -> Optional[str]:
        """Extrait le texte d'un PDF binaire."""
        if not isinstance(pdf_bytes, (bytes, bytearray)):
            try:
                pdf_bytes = bytes(pdf_bytes)
            except Exception:
                return None

        # 1. pdfplumber (préféré)
        if _PDFPLUMBER_AVAILABLE:
            return self._from_bytes_pdfplumber(pdf_bytes)

        # 2. Fallback Java jar
        if self._java_available:
            return self._from_bytes_java(pdf_bytes)

        return None

    def _from_bytes_pdfplumber(self, pdf_bytes: bytes) -> Optional[str]:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
                result = "\n".join(pages).strip()
                return result if result else None
        except Exception:
            return None

    def _from_bytes_java(self, pdf_bytes: bytes) -> Optional[str]:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf.write(pdf_bytes)
            tmp_pdf_path = tmp_pdf.name
        tmp_txt_path = tmp_pdf_path.replace(".pdf", ".txt")
        try:
            result = subprocess.run(
                [self.java_path, "-jar", self.jar_path, tmp_pdf_path, tmp_txt_path],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0 and Path(tmp_txt_path).exists():
                text = Path(tmp_txt_path).read_text(encoding="utf-8", errors="replace").strip()
                return text if text else None
            return None
        except (subprocess.TimeoutExpired, Exception):
            return None
        finally:
            Path(tmp_pdf_path).unlink(missing_ok=True)
            Path(tmp_txt_path).unlink(missing_ok=True)

    def from_text_bytes(self, text_bytes: bytes) -> Optional[str]:
        """Décode des bytes texte (fil_data_fs) directement."""
        if not isinstance(text_bytes, (bytes, bytearray)):
            try:
                text_bytes = bytes(text_bytes)
            except Exception:
                return None
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                text = text_bytes.decode(encoding).strip()
                return text if text else None
            except (UnicodeDecodeError, AttributeError):
                continue
        return None

    def convert(self, fil_data: Optional[bytes], fil_data_fs: Optional[bytes], doc_extension: str = "pdf") -> Optional[str]:
        """Point d'entrée : essaie fil_data_fs (texte natif), puis fil_data (PDF)."""
        if fil_data_fs is not None:
            text = self.from_text_bytes(fil_data_fs)
            if text:
                return text

        if fil_data is not None:
            return self.from_bytes(fil_data)

        return None


def hash_doc_id(doc_id: str) -> str:
    """Identifiant court et anonyme pour nommer les fichiers."""
    return hashlib.sha256(str(doc_id).encode()).hexdigest()[:12]
