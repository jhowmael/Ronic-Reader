"""Gera um PDF de teste com os problemas típicos de PDFs reais:

- cabeçalho e rodapé repetidos em todas as páginas;
- número de página;
- palavras hifenizadas no fim da linha;
- frase que continua na página seguinte;
- capítulos com bookmarks (sumário) no PDF.

Uso:  python tests/make_sample_pdf.py [saida.pdf]
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF

CHAPTERS = [
    ("Capítulo 1 - A chegada", [
        "Era uma manhã fria quando Marina desceu do ônibus na pequena cidade do interior. "
        "O vento trazia o cheiro de terra molhada e de café recém-passado.",
        "Ela olhou ao redor, procurando a casa da avó, que não visitava havia mais de dez anos. "
        "Tudo parecia menor do que nas suas lembranças, mas igualmente acolhedor.",
    ]),
    ("Capítulo 2 - O segredo do sótão", [
        "Na segunda noite, um barulho estranho vindo do sótão acordou Marina. "
        "Com uma lanterna na mão, ela subiu a escada de madeira, degrau por degrau, "
        "tentando não fazer nenhum ruído.",
        "Lá em cima encontrou uma caixa antiga, coberta de poeira, com o nome do avô "
        "gravado na tampa. Dentro havia cartas, fotografias e um mapa desenhado à mão.",
    ]),
]


class BookPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "I", 9)
        self.cell(0, 8, "Histórias da Serra - Edição de Teste", align="C")
        self.ln(12)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 10, str(self.page_no()), align="C")


def build(path: Path) -> Path:
    pdf = BookPDF(format=(148, 210))  # A5
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(18, 15, 18)

    for title, paragraphs in CHAPTERS:
        pdf.add_page()
        pdf.start_section(title)  # cria bookmark no sumário do PDF
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 8, title)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 11)
        for para in paragraphs * 5:  # repete para ocupar mais de uma página
            pdf.multi_cell(0, 6, para)
            pdf.ln(3)

    # Página final com hifenização manual de fim de linha (comum em livros)
    pdf.add_page()
    pdf.start_section("Epílogo")
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, "Epílogo")
    pdf.set_font("Helvetica", "", 11)
    for line in [
        "Marina guardou o mapa com cuidado e decidiu que, na manhã se-",
        "guinte, seguiria as pistas deixadas pelo avô até o fim da es-",
        "trada de terra, onde a história verdadeira finalmente come-",
        "çaria.",
    ]:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(path))
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("exemplo.pdf")
    print(f"PDF de teste criado: {build(out)}")
