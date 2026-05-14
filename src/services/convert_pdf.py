# RSWS Algorithm: Read → Store → Write → Style
# اختراع: Read PDF, Store words+formatting, Write word-by-word into Word, Style each word
import sys
import os
import json
import uuid
import time
from dataclasses import dataclass, field
from typing import List, Tuple

import fitz
from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ── Data structures ──

@dataclass
class WordInfo:
    text: str
    font: str
    size: float
    bold: bool
    italic: bool
    color: Tuple[int, int, int]

@dataclass
class LineInfo:
    words: List[WordInfo]
    alignment: str
    has_arabic: bool
    y: float
    x: float

@dataclass
class TableInfo:
    rows: List[List[str]]
    has_arabic: bool

@dataclass
class ImageInfo:
    png_bytes: bytes
    width_in: float
    height_in: float

@dataclass
class PageInfo:
    lines: List[LineInfo]
    tables: List[TableInfo]
    images: List[ImageInfo]


# ── Helpers ──

def has_arabic(text: str) -> bool:
    return any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F'
               or '\u08A0' <= c <= '\u08FF' or '\uFB50' <= c <= '\uFDFF'
               or '\uFE70' <= c <= '\uFEFF' for c in text)


def set_rtl(paragraph):
    pPr = paragraph._element.get_or_add_pPr()
    bidi = OxmlElement('w:bidi')
    pPr.append(bidi)


def set_arabic_font(run):
    rPr = run._element.get_or_add_rPr()
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:eastAsia'), 'Traditional Arabic')
    rFonts.set(qn('w:cs'), 'Traditional Arabic')
    rFonts.set(qn('w:ascii'), 'Traditional Arabic')
    rFonts.set(qn('w:hAnsi'), 'Traditional Arabic')
    rPr.insert(0, rFonts)


def detect_alignment(bbox, page_width) -> str:
    x0, _, x1, _ = bbox
    margin_left = x0
    margin_right = page_width - x1
    text_width = x1 - x0
    if text_width < page_width * 0.3:
        if margin_left < page_width * 0.05: return 'left'
        elif margin_right < page_width * 0.05: return 'right'
        elif margin_left > page_width * 0.3 and margin_right > page_width * 0.3: return 'center'
    return 'justify'


def extract_color(span) -> Tuple[int, int, int]:
    c = span.get('color', 0)
    if isinstance(c, int):
        return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
    return (0, 0, 0)


# ═══════════════════════════════════════════════
#  STEP 1 - READ & EXTRACT
#  ═══════════════════════════════════════════════
#  اقرأ الـ PDF كامل
#  احفظ كل كلمة + تنسيقها بالذاكرة
#  lines = [LineInfo[WordInfo, WordInfo, ...], ...]

def extract_from_pdf(pdf_path: str) -> List[PageInfo]:
    pdf = fitz.open(pdf_path)
    pages = []

    for page_num in range(pdf.page_count):
        page = pdf[page_num]
        pw = page.rect.width

        blocks = page.get_text('dict')['blocks']

        lines_info = []
        tables_info = []
        images_info = []

        # Images
        for block in blocks:
            if block['type'] != 1: continue
            try:
                b = block['bbox']
                w = b[2]-b[0]
                h = b[3]-b[1]
                if w < 20 or h < 20: continue
                pix = page.get_pixmap(clip=b, width=int(w), height=int(h))
                images_info.append(ImageInfo(
                    png_bytes=pix.tobytes('png'),
                    width_in=w/72,
                    height_in=h/72,
                ))
            except: pass

        # Extract text blocks with words
        text_blocks = [b for b in blocks if b['type'] == 0]

        # Simple table detection
        used_blocks = set()
        if len(text_blocks) >= 6:
            grid_map = {}
            for bi, b in enumerate(text_blocks):
                for line in b.get('lines', []):
                    for span in line.get('spans', []):
                        txt = span['text'].strip()
                        if txt:
                            grid_map[(round(b['bbox'][1], -1), round(b['bbox'][0], -1), bi)] = txt

            if len(grid_map) >= 4:
                rows = {}
                for (ry, cx, bi), txt in grid_map.items():
                    rows.setdefault(ry, {})[cx] = txt
                sorted_rows = sorted(rows.keys())
                if len(sorted_rows) >= 2:
                    all_cols = sorted(set(cx for (_, cx, _) in grid_map))
                    if len(all_cols) >= 2:
                        table_rows = []
                        for ry in sorted_rows:
                            row = [rows[ry].get(cx, '') for cx in all_cols]
                            if any(c.strip() for c in row):
                                table_rows.append(row)
                        if len(table_rows) >= 2:
                            tables_info.append(TableInfo(
                                rows=table_rows,
                                has_arabic=any(has_arabic(c) for row in table_rows for c in row),
                            ))
                            for ry, _, _ in grid_map:
                                for bi2, b2 in enumerate(text_blocks):
                                    if round(b2['bbox'][1], -1) == ry:
                                        used_blocks.add(id(b2))

        # Extract words from remaining blocks
        all_words = []
        for bi, block in enumerate(text_blocks):
            if id(block) in used_blocks: continue
            block_y = block['bbox'][1]
            block_x = block['bbox'][0]
            line_words = []

            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    txt = span['text']
                    if not txt.strip() and not txt:
                        # Whitespace-only span - still need to preserve as word
                        line_words.append(WordInfo(
                            text=txt,
                            font=span.get('font', 'Arial'),
                            size=span.get('size', 11),
                            bold=bool(span['flags'] & 2),
                            italic=bool(span['flags'] & 1),
                            color=extract_color(span),
                        ))
                        continue
                    # Split into individual words (preserving spaces between)
                    words = txt.split(' ')
                    for wi, w in enumerate(words):
                        if wi < len(words) - 1:
                            w += ' '
                        line_words.append(WordInfo(
                            text=w,
                            font=span.get('font', 'Arial'),
                            size=span.get('size', 11),
                            bold=bool(span['flags'] & 2),
                            italic=bool(span['flags'] & 1),
                            color=extract_color(span),
                        ))

            block_text = ''.join(w.text for w in line_words)
            if not block_text.strip(): continue
            block_arabic = has_arabic(block_text)
            block_align = 'right' if block_arabic else detect_alignment(block['bbox'], pw)

            lines_info.append(LineInfo(
                words=line_words,
                alignment=block_align,
                has_arabic=block_arabic,
                y=block_y,
                x=block_x,
            ))

        # Sort: top-to-bottom, right-to-left for Arabic
        lines_info.sort(key=lambda l: (l.y, -l.x if l.has_arabic else l.x))

        pages.append(PageInfo(
            lines=lines_info,
            tables=tables_info,
            images=images_info,
        ))

    pdf.close()
    return pages


# ═══════════════════════════════════════════════
#  STEP 2 - TYPE INTO WORD (word by word)
#  ═══════════════════════════════════════════════
#  افتح Word جديد
#  اكتب كل كلمة وحدة وحدة كـ run
#  مثل ما يكتبها انسان على لوحة المفاتيح

def type_into_word(doc: Document, pages: List[PageInfo]) -> List:
    """Step 2: اكتب النص في Word كلمة كلمة.
    يرجع refs = [(paragraph, run, word_info), ...] عشان الخطوة 3 تنسّق كل كلمة."""
    refs = []

    for page_idx, page in enumerate(pages):
        for line in page.lines:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.line_spacing = 1.3
            for word in line.words:
                run = p.add_run(word.text)
                refs.append((p, run, word, line))
        # Tables
        for table in page.tables:
            if not table.rows: continue
            cols = max(len(r) for r in table.rows)
            wt = doc.add_table(rows=len(table.rows), cols=cols)
            wt.style = 'Table Grid'
            for ri, row in enumerate(table.rows):
                for ci in range(min(len(row), cols)):
                    cell = wt.cell(ri, ci)
                    cell.text = ''
                    cell_p = cell.paragraphs[0]
                    cell_p.add_run(row[ci])
            refs.append(('table', wt, table))
        # Images
        for img in page.images:
            if img.width_in > 0.5 and img.height_in > 0.5:
                w = min(img.width_in, 6.0)
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run()
                run.add_picture(img.png_bytes, width=Inches(w))
                refs.append(('image', p, None))
        if page_idx < len(pages) - 1:
            doc.add_page_break()

    return refs


# ═══════════════════════════════════════════════
#  STEP 3 - FORMAT LIKE HUMAN
#  ═══════════════════════════════════════════════
#  طبق التنسيق اللي حفظناه على كل كلمة
#  كأن انسان ينسّق بالماوس: خط، لون، محاذاة

def format_like_human(refs: List):
    last_p = None
    for item in refs:
        if len(item) == 4:
            p, run, word, line = item

            # Paragraph-level formatting (مرة واحدة لكل فقرة)
            if p is not last_p:
                align_map = {
                    'left': WD_ALIGN_PARAGRAPH.LEFT,
                    'right': WD_ALIGN_PARAGRAPH.RIGHT,
                    'center': WD_ALIGN_PARAGRAPH.CENTER,
                    'justify': WD_ALIGN_PARAGRAPH.JUSTIFY,
                }
                if line.alignment in align_map:
                    p.alignment = align_map[line.alignment]
                if line.has_arabic:
                    set_rtl(p)
                last_p = p

            # Word-level formatting ← هنا التنسيق كلمة كلمة
            if line.has_arabic or has_arabic(run.text):
                run.font.name = 'Traditional Arabic'
                set_arabic_font(run)
            else:
                run.font.name = 'Arial'

            size = max(7, min(word.size, 72))
            run.font.size = Pt(size)
            run.bold = word.bold
            run.italic = word.italic
            if word.color != (0, 0, 0):
                try: run.font.color.rgb = RGBColor(*word.color)
                except: pass

        elif item[0] == 'table':
            _, wt, table = item
            if table.has_arabic:
                for row in wt.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            set_rtl(p)
                            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                            for run in p.runs:
                                run.font.name = 'Traditional Arabic'
                                set_arabic_font(run)


# ═══════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════

def convert_pdf_to_word(input_path: str, output_dir: str) -> str:
    t0 = time.time()

    # ── STEP 1: اقرأ الـ PDF واحفظ كل كلمة + تنسيقها ──
    t1 = time.time()
    pages = extract_from_pdf(input_path)
    extract_time = time.time() - t1

    # ── STEP 2: اكتب في Word كلمة كلمة ──
    t2 = time.time()
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    refs = type_into_word(doc, pages)
    type_time = time.time() - t2

    # ── STEP 3: طبق التنسيق المحفوظ ──
    t3 = time.time()
    format_like_human(refs)
    format_time = time.time() - t3

    output_filename = f"{uuid.uuid4()}.docx"
    output_path = os.path.join(output_dir, output_filename)
    doc.save(output_path)

    total_text = sum(len(w.text) for p in pages for l in p.lines for w in l.words)

    return json.dumps({
        'outputPath': output_path.replace('\\', '/'),
        'outputFileName': output_filename,
        'pageCount': len(pages),
        'textLength': total_text,
        'method': 'rsws',
        'timing': {
            'extract': round(extract_time, 2),
            'type': round(type_time, 2),
            'format': round(format_time, 2),
            'total': round(time.time() - t0, 2),
        }
    })


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'Missing arguments'}))
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.exists(input_path):
        print(json.dumps({'error': f'Input file not found: {input_path}'}))
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    try:
        result = convert_pdf_to_word(input_path, output_dir)
        print(result)
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
