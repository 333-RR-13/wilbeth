import pypdf

files = [
    r'C:\Claude\KIB3\Berufsschulpläne\Blockplan_2526_v260112_IT.pdf',
    r'C:\Claude\KIB3\Berufsschulpläne\Blockplan_2627_v260112_IT.pdf',
]
for fname in files:
    print('=== ' + fname + ' ===')
    reader = pypdf.PdfReader(fname)
    for i, page in enumerate(reader.pages):
        print('--- Seite ' + str(i+1) + ' ---')
        print(page.extract_text())
    print()
