import sys
import os
import json
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextBox, LTTextLine, LTChar, LTAnno, LAParams
from docx import Document
from docx.shared import Pt, Inches, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import uuid

def set_rtl_paragraph(paragraph):
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

def convert_pdf_to_word(input_path, output_dir):
    output_filename = f"{uuid.uuid4()}.docx"
    output_path = os.path.join(output_dir, output_filename)

    doc = Document()

    section = doc.sections[0]
    section.orientation = 1  # WD_ORIENT.PORTRAIT
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    page_count = 0
    total_text = ""

    laparams = LAParams(
        all_texts=True,
        detect_vertical=True,
        box_flow='ltr'
    )

    for page_layout in extract_pages(input_path, laparams=laparams):
        page_count += 1
        elements = []

        for element in page_layout:
            if isinstance(element, (LTTextBox, LTTextLine)):
                text = element.get_text().strip()
                if text:
                    has_arabic = any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' or '\uFB50' <= c <= '\uFDFF' for c in text)
                    elements.append({
                        'text': text,
                        'y': element.y0,
                        'x': element.x0,
                        'width': element.width,
                        'height': element.height,
                        'has_arabic': has_arabic,
                        'font_size': 11,
                        'font_name': 'Arial'
                    })

                    for child in element:
                        if isinstance(child, LTChar):
                            elements[-1]['font_size'] = child.size / 2.0  # points
                            elements[-1]['font_name'] = child.fontname
                            break

        elements.sort(key=lambda e: (-e['y'], e['x']))

        for el in elements:
            p = doc.add_paragraph()

            if el['has_arabic']:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                set_rtl_paragraph(p)
            elif el['x'] < 100:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

            fmt = p.paragraph_format
            fmt.space_after = Pt(4)
            fmt.space_before = Pt(2)
            fmt.line_spacing = 1.15

            run = p.add_run(el['text'])
            font_size = max(8, min(el['font_size'], 24))
            run.font.size = Pt(font_size)

            if el['has_arabic']:
                run.font.name = 'Traditional Arabic'
                set_arabic_font(run)
            else:
                run.font.name = 'Arial'

            total_text += el['text'] + "\n"

    # Add end marker
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run('\u2014 \u0646\u0647\u0627\u064a\u0629 \u0627\u0644\u0645\u0633\u062a\u0646\u062f \u2014')
    run.font.size = Pt(8)
    run.font.color.rgb = None
    run.font.name = 'Traditional Arabic'
    set_arabic_font(run)

    doc.save(output_path)

    return json.dumps({
        'outputPath': output_path.replace('\\', '/'),
        'outputFileName': output_filename,
        'pageCount': page_count,
        'textLength': len(total_text)
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
