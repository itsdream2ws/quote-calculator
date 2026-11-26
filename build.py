"""Builds single-file versions of the app (everything inlined) so each page works on its own,
e.g. opened straight from a download. Usage: python3 build.py <src_dir> <out_dir>"""
import sys, os, re
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
def read(p): return open(os.path.join(src, p), encoding='utf-8').read()
def inline(html):
    html = html.replace('<link rel="stylesheet" href="styles.css">', '<style>\n' + read('styles.css') + '\n</style>')
    def rep(m):
        js = read(m.group(1)).replace('</script', '<\\/script')
        return '<script>\n' + js + '\n</script>'
    html = re.sub(r'<script src="([^"]+)"></script>', rep, html)
    return html
pages = {'index.html': 'Quote Calculator.html', 'report.html': 'Supplier Report.html'}
for s, d in pages.items():
    h = inline(read(s))
    for a, b in pages.items():
        h = h.replace('href="%s' % a, 'href="%s' % b)
    open(os.path.join(out, d), 'w', encoding='utf-8').write(h)
    print('wrote', d, len(h))
