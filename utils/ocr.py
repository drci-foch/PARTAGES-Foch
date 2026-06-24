"""
OCR pour PDF scannés (ex. CR de génétique/génomique scannés de l'Institut Curie).

Stratégie : rastérisation des pages via PyMuPDF (fitz) → OCR via pytesseract (moteur Tesseract).
Se dégrade proprement si pytesseract / le binaire Tesseract ne sont pas installés
(is_available() == False, ocr_pdf_bytes() == None) afin que le pipeline puisse
sauvegarder le PDF brut et le marquer « à océriser plus tard ».

Pré-requis pour activer l'OCR :
  pip install pytesseract
  + installer le moteur Tesseract (binaire) et les données de langue françaises (fra) :
    Windows : https://github.com/UB-Mannheim/tesseract/wiki  (cocher « French »)
    Puis renseigner éventuellement TESSERACT_CMD dans .env si tesseract.exe n'est pas dans le PATH.
"""

import io
import os
from typing import Optional

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image
    _TESS_IMPORT = True
except ImportError:
    _TESS_IMPORT = False


# Localisation du binaire tesseract.exe :
#   1. variable d'environnement TESSERACT_CMD (.env)
#   2. sinon, auto-détection des emplacements d'installation usuels sous Windows
_TESS_CMD = os.environ.get("TESSERACT_CMD", "")
if _TESS_IMPORT:
    if not _TESS_CMD:
        for _candidate in (
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(_candidate):
                _TESS_CMD = _candidate
                break
    if _TESS_CMD:
        pytesseract.pytesseract.tesseract_cmd = _TESS_CMD


def is_available() -> bool:
    """True si l'OCR est réellement utilisable (fitz + pytesseract + binaire Tesseract)."""
    if not (_FITZ_AVAILABLE and _TESS_IMPORT):
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_pdf_bytes(
    pdf_bytes: bytes,
    lang: str = "fra",
    dpi: int = 300,
    max_pages: int = 40,
) -> Optional[str]:
    """
    Océrise un PDF scanné et retourne le texte, ou None si l'OCR est indisponible/échoue.

    lang : langue Tesseract ('fra'). Repli automatique sur la langue par défaut si 'fra' absent.
    dpi  : résolution de rastérisation (300 = bon compromis qualité/temps).
    """
    if not (_FITZ_AVAILABLE and _TESS_IMPORT):
        return None
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        try:
            pdf_bytes = bytes(pdf_bytes)
        except Exception:
            return None

    def _run(use_lang: Optional[str]) -> Optional[str]:
        texts = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(dpi=dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                kwargs = {"lang": use_lang} if use_lang else {}
                t = pytesseract.image_to_string(img, **kwargs)
                if t:
                    texts.append(t)
        result = "\n".join(texts).strip()
        return result or None

    try:
        return _run(lang)
    except pytesseract.TesseractError:
        # Données de langue 'fra' probablement absentes → repli sur la langue par défaut
        try:
            return _run(None)
        except Exception:
            return None
    except Exception:
        return None
