"""PDF Text Reader — Multi-backend extraction with quality scoring
يقرا PDF بـ 4 طرق مختلفة ويختار أفضل نتيجة بناءً على جودة النص
"""
import sys
import os
import json
import subprocess
import re


# ── Unicode blocks for quality scoring ──

ARABIC_BLOCKS = [
    (0x0600, 0x06FF),   # Arabic
    (0x0750, 0x077F),   # Arabic Supplement
    (0x08A0, 0x08FF),   # Arabic Extended-A
    (0xFB50, 0xFDFF),   # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),   # Arabic Presentation Forms-B
]

GARBLED_BLOCKS = [
    (0x0180, 0x024F, 'Latin Extended-B'),
    (0x0250, 0x02AF, 'IPA Extensions'),
    (0x0700, 0x074F, 'Syriac'),
    (0x0780, 0x07BF, 'Thaana'),
    (0x0900, 0x097F, 'Devanagari'),
    (0x0E80, 0x0EFF, 'Lao'),
    (0x0F00, 0x0FFF, 'Tibetan'),
    (0x1000, 0x109F, 'Myanmar'),
    (0x0D00, 0x0D7F, 'Malayalam'),
]


def has_arabic_char(c: str) -> bool:
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi in ARABIC_BLOCKS)


def is_garbled_char(c: str) -> bool:
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi, _ in GARBLED_BLOCKS)


def is_replacement_char(c: str) -> bool:
    return ord(c) == 0xFFFD


def assess_quality(text: str) -> dict:
    """Score text quality 0-100. Higher = better."""
    if not text or not text.strip():
        return {'score': 0, 'issues': 'empty'}
    total = max(len(text), 1)
    arabic_chars = sum(1 for c in text if has_arabic_char(c))
    garbled_chars = sum(1 for c in text if is_garbled_char(c))
    replacement_chars = sum(1 for c in text if is_replacement_char(c))
    printable_chars = sum(1 for c in text if c.isprintable() or c in '\n\r\t')

    # Penalties
    garbled_penalty = (garbled_chars / total) * 100
    repl_penalty = (replacement_chars / total) * 50
    arabic_bonus = min((arabic_chars / max(total, 1)) * 30, 30)
    printable_bonus = (printable_chars / total) * 10
    length_bonus = min(len(text) / 5000, 10)

    score = 100 - garbled_penalty - repl_penalty + arabic_bonus + printable_bonus + length_bonus
    score = max(0, min(100, score))

    return {
        'score': round(score, 1),
        'total_chars': len(text),
        'arabic_chars': arabic_chars,
        'garbled_chars': garbled_chars,
        'replacement_chars': replacement_chars,
        'printable_ratio': round(printable_chars / total, 3),
        'issues': []
        + (['garbled'] if garbled_chars > 0 else [])
        + (['replacement'] if replacement_chars > 0 else [])
        + (['no_arabic'] if arabic_chars == 0 else [])
    }


# ── Extraction backends ──

def extract_pymupdf(path: str) -> dict:
    """Extract text using PyMuPDF (fitz)."""
    try:
        import fitz
        doc = fitz.open(path)
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text("text"))
        doc.close()
        text = '\n'.join(pages_text)
        return {'text': text, 'method': 'pymupdf', 'page_count': len(pages_text), **assess_quality(text)}
    except Exception as e:
        return {'text': '', 'method': 'pymupdf', 'error': str(e), 'score': 0}


def extract_pdftotext(path: str) -> dict:
    """Extract text using pdftotext (poppler-utils)."""
    try:
        r = subprocess.run(
            ['pdftotext', '-layout', '-nopgbrk', '-enc', 'UTF-8', path, '-'],
            capture_output=True, timeout=60,
        )
        if r.returncode == 0 and r.stdout:
            text = r.stdout.decode('utf-8', errors='replace')
            return {'text': text, 'method': 'pdftotext', **assess_quality(text)}
    except Exception as e:
        pass
    return {'text': '', 'method': 'pdftotext', 'score': 0}


def extract_pdfplumber(path: str) -> dict:
    """Extract text using pdfplumber."""
    try:
        import pdfplumber
        pages_text = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ''
                pages_text.append(t)
        text = '\n'.join(pages_text)
        return {'text': text, 'method': 'pdfplumber', 'page_count': len(pages_text), **assess_quality(text)}
    except Exception as e:
        return {'text': '', 'method': 'pdfplumber', 'error': str(e), 'score': 0}


def extract_pypdf(path: str) -> dict:
    """Extract text using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages_text = [p.extract_text() or '' for p in reader.pages]
        text = '\n'.join(pages_text)
        return {'text': text, 'method': 'pypdf', 'page_count': len(pages_text), **assess_quality(text)}
    except Exception as e:
        return {'text': '', 'method': 'pypdf', 'error': str(e), 'score': 0}


def extract_ocr_tesseract(path: str) -> dict:
    """OCR using pdf2image + pytesseract (for scanned or garbled PDFs)."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(path, dpi=300)
        pages_text = []
        for img in images:
            t = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 6')
            pages_text.append(t)
        text = '\n'.join(pages_text)
        return {'text': text, 'method': 'ocr_tesseract', 'page_count': len(pages_text), **assess_quality(text)}
    except Exception as e:
        return {'text': '', 'method': 'ocr_tesseract', 'error': str(e), 'score': 0}


# ── Arabic text normalization ──

ARABIC_NORM_MAP = {
    # Normalize Arabic Presentation Forms to standard Arabic
    0xFE80: 0x0621,  # ء
    0xFE81: 0x0622, 0xFE82: 0x0622,  # آ
    0xFE83: 0x0623, 0xFE84: 0x0623,  # أ
    0xFE85: 0x0624, 0xFE86: 0x0624,  # ؤ
    0xFE87: 0x0625, 0xFE88: 0x0625,  # إ
    0xFE89: 0x0626, 0xFE8A: 0x0626, 0xFE8B: 0x0626, 0xFE8C: 0x0626,  # ئ
    0xFE8D: 0x0627, 0xFE8E: 0x0627,  # ا
    0xFE8F: 0x0628, 0xFE90: 0x0628, 0xFE91: 0x0628, 0xFE92: 0x0628,  # ب
    0xFE93: 0x0629, 0xFE94: 0x0629,  # ة
    0xFE95: 0x062A, 0xFE96: 0x062A, 0xFE97: 0x062A, 0xFE98: 0x062A,  # ت
    0xFE99: 0x062B, 0xFE9A: 0x062B, 0xFE9B: 0x062B, 0xFE9C: 0x062B,  # ث
    0xFE9D: 0x062C, 0xFE9E: 0x062C, 0xFE9F: 0x062C, 0xFEA0: 0x062C,  # ج
    0xFEA1: 0x062D, 0xFEA2: 0x062D, 0xFEA3: 0x062D, 0xFEA4: 0x062D,  # ح
    0xFEA5: 0x062E, 0xFEA6: 0x062E, 0xFEA7: 0x062E, 0xFEA8: 0x062E,  # خ
    0xFEA9: 0x062F, 0xFEAA: 0x062F,  # د
    0xFEAB: 0x0630, 0xFEAC: 0x0630,  # ذ
    0xFEAD: 0x0631, 0xFEAE: 0x0631,  # ر
    0xFEAF: 0x0632, 0xFEB0: 0x0632,  # ز
    0xFEB1: 0x0633, 0xFEB2: 0x0633, 0xFEB3: 0x0633, 0xFEB4: 0x0633,  # س
    0xFEB5: 0x0634, 0xFEB6: 0x0634, 0xFEB7: 0x0634, 0xFEB8: 0x0634,  # ش
    0xFEB9: 0x0635, 0xFEBA: 0x0635, 0xFEBB: 0x0635, 0xFEBC: 0x0635,  # ص
    0xFEBD: 0x0636, 0xFEBE: 0x0636, 0xFEBF: 0x0636, 0xFEC0: 0x0636,  # ض
    0xFEC1: 0x0637, 0xFEC2: 0x0637, 0xFEC3: 0x0637, 0xFEC4: 0x0637,  # ط
    0xFEC5: 0x0638, 0xFEC6: 0x0638, 0xFEC7: 0x0638, 0xFEC8: 0x0638,  # ظ
    0xFEC9: 0x0639, 0xFECA: 0x0639, 0xFECB: 0x0639, 0xFECC: 0x0639,  # ع
    0xFECD: 0x063A, 0xFECE: 0x063A, 0xFECF: 0x063A, 0xFED0: 0x063A,  # غ
    0xFED1: 0x0641, 0xFED2: 0x0641, 0xFED3: 0x0641, 0xFED4: 0x0641,  # ف
    0xFED5: 0x0642, 0xFED6: 0x0642, 0xFED7: 0x0642, 0xFED8: 0x0642,  # ق
    0xFED9: 0x0643, 0xFEDA: 0x0643, 0xFEDB: 0x0643, 0xFEDC: 0x0643,  # ك
    0xFEDD: 0x0644, 0xFEDE: 0x0644, 0xFEDF: 0x0644, 0xFEE0: 0x0644,  # ل
    0xFEE1: 0x0645, 0xFEE2: 0x0645, 0xFEE3: 0x0645, 0xFEE4: 0x0645,  # م
    0xFEE5: 0x0646, 0xFEE6: 0x0646, 0xFEE7: 0x0646, 0xFEE8: 0x0646,  # ن
    0xFEE9: 0x0647, 0xFEEA: 0x0647, 0xFEEB: 0x0647, 0xFEEC: 0x0647,  # ه
    0xFEED: 0x0648, 0xFEEE: 0x0648,  # و
    0xFEEF: 0x0649, 0xFEF0: 0x0649,  # ى
    0xFEF1: 0x064A, 0xFEF2: 0x064A, 0xFEF3: 0x064A, 0xFEF4: 0x064A,  # ي
    0xFEF5: 0x0644, 0xFEF6: 0x0644, 0xFEF7: 0x0644, 0xFEF8: 0x0644,  # لا
    0xFEF9: 0x0644, 0xFEFA: 0x0644, 0xFEFB: 0x0644, 0xFEFC: 0x0644,  # لأ
    # FE70-FEFF presentation forms B
    0xFE70: 0x064B,  ְ
    0xFE71: 0x0640,
    0xFE72: 0x064C,
    0xFE74: 0x064D,
    0xFE76: 0x064E,
    0xFE77: 0x064E,
    0xFE78: 0x064F,
    0xFE79: 0x064F,
    0xFE7A: 0x0650,
    0xFE7B: 0x0650,
    0xFE7C: 0x0651,
    0xFE7D: 0x0651,
    0xFE7E: 0x0652,
    0xFE7F: 0x0652,
}


def normalize_arabic(text: str) -> str:
    """Convert Arabic Presentation Forms to standard Unicode, clean mojibake."""
    result = []
    for c in text:
        cp = ord(c)
        if cp in ARABIC_NORM_MAP:
            result.append(chr(ARABIC_NORM_MAP[cp]))
        elif cp == 0xFFFD:
            # Keep replacement chars as-is (caller decides)
            result.append(c)
        elif 0xFE00 <= cp <= 0xFE0F:
            # Variation selectors — skip
            continue
        elif 0x200B <= cp <= 0x200F or 0x2028 <= cp <= 0x2029 or cp == 0xFEFF:
            # Zero-width, bidi, format chars — skip
            continue
        else:
            result.append(c)
    return ''.join(result)


def clean_garbled(text: str) -> str:
    """Attempt to fix known broken CMap mappings by removing garbled chars.
    This doesn't recover the CORRECT char, but removes the obviously wrong ones.
    """
    # Remove characters from garbled blocks, keeping the rest
    cleaned = []
    for c in text:
        if is_garbled_char(c):
            cleaned.append('')  # remove it
        else:
            cleaned.append(c)
    return ''.join(cleaned)


# ── Detect PDF type ──

def detect_pdf_type(path: str) -> dict:
    """Determine if PDF has selectable text or is scanned/image-based."""
    try:
        import fitz
        doc = fitz.open(path)
        total_text = 0
        total_images = 0
        for page in doc:
            total_text += len(page.get_text("text").strip())
            blocks = page.get_text("dict").get("blocks", [])
            total_images += sum(1 for b in blocks if b.get("type") == 1)
        doc.close()
        return {
            'has_text': total_text > 50,
            'text_chars': total_text,
            'image_count': total_images,
            'page_count': doc.page_count if hasattr(doc, 'page_count') else 0,
            'type': 'text' if total_text > 50 else ('image' if total_images > 0 else 'unknown'),
        }
    except:
        return {'has_text': False, 'text_chars': 0, 'image_count': 0, 'type': 'unknown'}


# ── Main extraction pipeline ──

BACKENDS = [
    ('PyMuPDF (fitz)', extract_pymupdf),
    ('pdftotext (poppler)', extract_pdftotext),
    ('pdfplumber', extract_pdfplumber),
    ('pypdf', extract_pypdf),
    ('OCR Tesseract', extract_ocr_tesseract),
]


def extract_best_text(path: str, prefer_ocr: bool = False) -> dict:
    """
    Try all extraction backends, score each, return best.
    Returns dict with: text, method, quality, page_count, all_results
    """
    results = []
    best = {'text': '', 'method': 'none', 'score': 0}

    for name, extract_fn in BACKENDS:
        print(f"  Trying {name}...", file=sys.stderr)
        try:
            r = extract_fn(path)
            r['backend'] = name
            results.append(r)
            if r['score'] > best['score']:
                best = r
                print(f"    Score: {r['score']} (best so far) ✓", file=sys.stderr)
            else:
                print(f"    Score: {r['score']}", file=sys.stderr)
        except Exception as e:
            results.append({'backend': name, 'method': 'error', 'error': str(e), 'score': 0})
            print(f"    Error: {e}", file=sys.stderr)

    # Normalize the best text
    if best['text']:
        best['text_normalized'] = normalize_arabic(best['text'])
    else:
        best['text_normalized'] = ''

    best['all_results'] = [
        {
            'backend': r.get('backend', r.get('method', '?')),
            'method': r.get('method', '?'),
            'score': r.get('score', 0),
            'total_chars': r.get('total_chars', 0),
            'arabic_chars': r.get('arabic_chars', 0),
            'garbled_chars': r.get('garbled_chars', 0),
            'replacement_chars': r.get('replacement_chars', 0),
            'issues': r.get('issues', []),
            'error': r.get('error', None),
        }
        for r in results
    ] if results else []

    return best


# ── CLI for testing ──

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python text_reader.py <pdf_path> [--ocr]")
        sys.exit(1)
    path = sys.argv[1]
    prefer_ocr = '--ocr' in sys.argv
    result = extract_best_text(path, prefer_ocr)
    # Print summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"BEST: {result.get('method', 'none')} (score={result.get('score', 0)})", file=sys.stderr)
    print(f"Text length: {len(result.get('text', ''))}", file=sys.stderr)
    print(f"\nAll backends:", file=sys.stderr)
    for r in result.get('all_results', []):
        print(f"  {r['backend']:25s} score={r['score']:5.1f} arabic={r['arabic_chars']:5d} "
              f"garbled={r['garbled_chars']:3d} repl={r['replacement_chars']:3d} "
              f"issues={r['issues']}", file=sys.stderr)

    # Output the best text to stdout (for piping)
    print(result['text_normalized'] if result.get('text_normalized') else result.get('text', ''))
