import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from convert_pdf import extract_from_pdf, check_garbled, detect_remaining_garbled
from text_reader import normalize_arabic

pdf_path = os.path.expanduser(r'~\Downloads\نموذج-عقد-ايجار-شقة-بيت-2021-وفقا-لأحدث-التعديلات.pdf')

# 1 READ
pages = extract_from_pdf(pdf_path)
all_text = ''.join(w.text for p in pages for l in p.lines for w in l.words)
print(f'Pages: {len(pages)}')
print(f'Total chars: {len(all_text)}')

# 2 CHECK garbled before fix
g = check_garbled(all_text)
print(f'Garbled BEFORE: {g["count"]} chars - garbled: {g["garbled"]}')

# 3 FIX
for p in pages:
    for l in p.lines:
        for w in l.words:
            w.text = normalize_arabic(w.text)

all_text_fixed = ''.join(w.text for p in pages for l in p.lines for w in l.words)
g2 = check_garbled(all_text_fixed)
print(f'Garbled AFTER: {g2["count"]} chars - garbled: {g2["garbled"]}')

# 4 DETECT
remaining = detect_remaining_garbled(pages)
print(f'Remaining garbled: {len(remaining)}')

# 5 Sample
print()
print('=== FIRST 800 CHARS ===')
print(all_text_fixed[:800])
