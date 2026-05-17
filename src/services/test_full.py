import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from convert_pdf import convert_pdf_to_word

pdf_path = os.path.expanduser(r'~\Downloads\نموذج-عقد-ايجار-شقة-بيت-2021-وفقا-لأحدث-التعديلات.pdf')
output_dir = os.path.expanduser(r'~\Downloads')

result_json = convert_pdf_to_word(pdf_path, output_dir)
result = json.loads(result_json)
print('=== RESULT ===')
for k, v in result.items():
    print(f'{k}: {v}')
