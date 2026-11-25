#!/usr/bin/env bash
# Rebuild ACME_case_memo.pdf from the Markdown. Needs pandoc and wkhtmltopdf:
#   sudo apt install pandoc wkhtmltopdf
set -euo pipefail
cd "$(dirname "$0")"
pandoc ACME_case_memo.md -f markdown-implicit_figures -s --section-divs --metadata pagetitle="ACME case memo" \
  -c memo.css -o memo.html
wkhtmltopdf -q --enable-local-file-access --disable-smart-shrinking -s Letter -T 18mm -B 18mm -L 18mm -R 18mm memo.html ACME_case_memo.pdf
rm memo.html
echo "Wrote $(pwd)/ACME_case_memo.pdf"
