"""Monta amostras/index.html para ouvir e comparar os narradores lado a lado.

Uso: python make_page.py   (depois: open amostras/index.html)
"""

import html
import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "amostras"

NAMES = {
    "padrao": ("Voz padrão do Chatterbox", "sem referência"),
    "leni": ("Leni", "narradora do LibriVox · O Alienista"),
    "vicente": ("Vicente Costa Filho", "narrador do LibriVox · Cinco Minutos"),
    "miramontes": ("Miramontes", "narrador do LibriVox · Policarpo Quaresma"),
    "ana_florence": ("Ana Florence", "voz de estúdio pronta do XTTS"),
    "gracie_wise": ("Gracie Wise", "voz de estúdio pronta do XTTS"),
    "damien_black": ("Damien Black", "voz de estúdio pronta do XTTS"),
    "viktor_menelaos": ("Viktor Menelaos", "voz de estúdio pronta do XTTS"),
}

rows = [json.loads(line) for line in (OUT / "resultados.jsonl").read_text().splitlines() if line.strip()]
seen, unique = set(), []
for r in reversed(rows):  # a execução mais recente vale
    key = (r["engine"], r["voice"])
    if key not in seen:
        seen.add(key)
        unique.append(r)
unique.reverse()


CLAREZA = json.loads((OUT / "clareza.json").read_text()) if (OUT / "clareza.json").exists() else {}
ENGINE = {"chatterbox": "Chatterbox", "xtts": "XTTS v2", "edge": "Microsoft (online)", "kokoro": "Kokoro (no seu Mac)", "macos": "macOS (no seu Mac)"}
VOICE_NAMES = {
    "pf_dora": "Dora", "pm_alex": "Alex", "pm_santa": "Santa", "Luciana": "Luciana",
}


def verdict(rtf: float) -> str:
    if rtf <= 0.9:
        return '<span class="ok">toca na hora</span>'
    if rtf <= 1.3:
        return '<span class="mid">quase em tempo real</span>'
    return '<span class="slow">precisa preparar antes</span>'


unique.sort(key=lambda r: -CLAREZA.get(r["file"], {}).get("clareza", 0))
cards = []
for r in unique:
    engine = ENGINE.get(r["engine"].split("_")[0], r["engine"])
    v = r["voice"]
    pretty = VOICE_NAMES.get(v) or (v.split("-")[2].replace("MultilingualNeural", "").replace("Neural", "") if v.count("-") >= 2 else v)
    name, desc = NAMES.get(v, (pretty, "multilíngue" if "Multilingual" in v else ""))
    clar = CLAREZA.get(r["file"], {}).get("clareza")
    cards.append(f"""
    <div class="card">
      <div class="top"><div><b>{html.escape(name)}</b><small>{html.escape(engine)} · {html.escape(desc)}</small></div>
      {verdict(r['rtf'])}</div>
      <audio controls preload="none" src="{html.escape(r['file'])}"></audio>
      <div class="meta"><b>Clareza {clar if clar is not None else "—"}%</b> · {r['audio_s']} s de áudio gerados em {r['gen_s']} s · {r['rtf']}× o tempo real</div>
    </div>""")

page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Amostras de narradores</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{ color-scheme: light dark; --bg:#f5f4f7; --card:#fff; --muted:#6e6e73; --line:#e3e2e8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1c1b1f; --card:#2a292e; --muted:#a1a1a6; --line:#3a393f; }} }}
body {{ margin:0; background:var(--bg); font:14px/1.45 -apple-system, sans-serif; padding:32px 16px; }}
main {{ max-width:760px; margin:0 auto; }}
h1 {{ font-size:26px; margin:0 0 6px; }}
p {{ color:var(--muted); margin:0 0 20px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:12px; }}
.top {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px; }}
.top small {{ display:block; color:var(--muted); }}
audio {{ width:100%; }}
.meta {{ color:var(--muted); font-size:12px; margin-top:6px; }}
.ok, .mid, .slow {{ font-size:12px; font-weight:600; padding:3px 9px; border-radius:99px; white-space:nowrap; }}
.ok {{ background:#d8f3dc; color:#1b6b33; }} .mid {{ background:#fff1c9; color:#8a5a00; }} .slow {{ background:#ffe0d6; color:#a2361b; }}
blockquote {{ margin:0 0 24px; padding:12px 16px; border-left:3px solid #e2663b; background:var(--card); border-radius:0 10px 10px 0; font-family: ui-serif, Georgia, serif; }}
</style></head><body><main>
<h1>Qual narrador parece uma pessoa lendo?</h1>
<p>Mesmo trecho em todas as vozes. Tudo gerado no seu Mac, sem internet e sem treinar nada.
"Clareza" = palavras que um reconhecedor de fala (Whisper, rodando no seu Mac) entendeu certo; mede nitidez, não sotaque nem emoção, isso só o seu ouvido decide.
"× o tempo real" = quanto tempo leva para gerar cada segundo de fala (abaixo de 1 toca na hora).</p>
<blockquote>Uma noite destas, vindo da cidade para o Engenho Novo, encontrei no trem da Central um rapaz aqui do bairro,
que eu conheço de vista e de chapéu. Cumprimentou-me, sentou-se ao pé de mim, falou da Lua e dos ministros,
e acabou recitando-me versos. A viagem era curta, e os versos pode ser que não fossem inteiramente maus.
<br><small>— Machado de Assis, Dom Casmurro</small></blockquote>
{''.join(cards)}
</main></body></html>"""
(OUT / "index.html").write_text(page, encoding="utf-8")
print(f"Página criada: {OUT / 'index.html'} ({len(unique)} amostras)")
