"""Interface de linha de comando do Ronic Reader.

Uso rápido:
    ronic livro.pdf                         # lê o PDF inteiro, divide por capítulos
    ronic livro.pdf -p 10-35 -v antonio     # só páginas 10 a 35, voz masculina
    ronic livro.pdf --preset narrador       # calibragem pronta para audiolivro
    ronic --preview -v thalita --rate +10%  # ouve uma amostra antes de gerar tudo
    ronic                                   # modo interativo (escolhe PDF, calibra a voz ouvindo)
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__
from .cleaner import clean_pages
from .extractor import count_pages, extract_outline, extract_pages, parse_page_range
from .output import merge_audio, safe_filename, write_playlist, write_srt
from .splitter import Part, chunk_text, make_parts
from .voice_settings import (
    CONFIG_PATH, PRESET_HELP, PRESETS, VoiceSettings, describe,
    normalize_expressiveness, normalize_pitch, normalize_rate, normalize_volume,
    resolve_settings, save_config,
)

SAMPLE_TEXT = (
    "Olá! Esta é uma amostra da voz escolhida. "
    "Era uma manhã fria quando Marina desceu do ônibus; o vento trazia o cheiro de terra molhada "
    "e de café recém-passado. Você prefere uma leitura mais calma, ou mais animada?"
)
EDGE_PT_VOICES = [
    ("francisca", "pt-BR-FranciscaNeural", "feminina, pt-BR, clara e natural"),
    ("antonio", "pt-BR-AntonioNeural", "masculina, pt-BR, grave e firme"),
    ("thalita", "pt-BR-ThalitaMultilingualNeural", "feminina, pt-BR, multilíngue, bem expressiva"),
    ("raquel", "pt-PT-RaquelNeural", "feminina, português de Portugal (servidor às vezes instável)"),
    ("duarte", "pt-PT-DuarteNeural", "masculina, português de Portugal"),
]
PIPER_PT_VOICES = [
    ("pt_BR-faber-medium", "masculina, pt-BR (offline, recomendada)"),
    ("pt_BR-cadu-medium", "masculina, pt-BR (offline)"),
    ("pt_BR-jeff-medium", "masculina, pt-BR (offline)"),
]

# --------------------------------------------------------------------------- #
# Argumentos
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ronic",
        description="Converte PDF em audiolivro com voz humanizada, sem custo por uso.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  ronic livro.pdf\n"
            "  ronic livro.pdf -p 5-20 -v antonio --rate +10% --volume +5% --pitch -3Hz\n"
            "  ronic livro.pdf --preset narrador --split pages --pages-per-part 15 --merge\n"
            "  ronic livro.pdf --preview                 # amostra com o texto do próprio PDF\n"
            "  ronic --compare-voices                    # ouve todas as vozes em português\n"
            "  ronic -v thalita --preset calmo --save-config   # salva como padrão\n"
            "  ronic livro.pdf --engine piper            # 100% offline\n"
        ),
    )
    p.add_argument("pdf", nargs="?", type=Path, help="arquivo PDF (se omitido, abre o modo interativo)")
    p.add_argument("-p", "--pages", help='páginas a ler, ex.: "5-20", "1,3,10-12", "30-" (padrão: todas)')
    p.add_argument("-o", "--output", type=Path, help="pasta de saída (padrão: <nome-do-pdf>_audio ao lado do PDF)")

    # default=None em todos os ajustes de voz: assim sabemos o que o usuário digitou
    # de fato e podemos combinar com --preset e com a config salva.
    voz = p.add_argument_group("voz e calibragem")
    voz.add_argument("-e", "--engine", choices=["edge", "kokoro", "piper"],
                     help="edge = vozes neurais Microsoft, grátis, precisa de internet (padrão); "
                          "piper = 100%% offline")
    voz.add_argument("-v", "--voice", help="francisca, antonio, thalita, raquel, duarte ou nome completo da voz")
    voz.add_argument("--preset", choices=list(PRESETS),
                     help="calibragem pronta: " + "; ".join(f"{k} = {v}" for k, v in PRESET_HELP.items()))
    voz.add_argument("--rate", help='velocidade, de -50%% a +100%%, ex.: "+15%%" ou "-10%%"')
    voz.add_argument("--volume", help='intensidade/volume, de -50%% a +50%%, ex.: "+10%%"')
    voz.add_argument("--pitch", help='tom (edge), de -50Hz a +50Hz, ex.: "-5Hz" = mais grave')
    voz.add_argument("--expressiveness", type=float,
                     help="expressividade da entonação (piper), de 0 (monótono) a 1 (bem expressivo)")
    voz.add_argument("--concurrency", type=int, default=3, help="blocos sintetizados em paralelo (edge)")

    cal = p.add_argument_group("testar e salvar a voz")
    cal.add_argument("--preview", action="store_true", help="gera e toca só uma amostra curta com os ajustes atuais")
    cal.add_argument("--preview-text", help="texto próprio para a amostra")
    cal.add_argument("--compare-voices", action="store_true", help="gera e toca uma amostra de cada voz em português")
    cal.add_argument("--no-play", action="store_true", help="não tocar a amostra automaticamente")
    cal.add_argument("--save-config", action="store_true", help=f"salva os ajustes de voz como padrão ({CONFIG_PATH})")
    cal.add_argument("--list-voices", action="store_true", help="lista todas as vozes em português e sai")

    div = p.add_argument_group("divisão do áudio")
    div.add_argument("-s", "--split", choices=["auto", "chapters", "pages", "size", "none"], default="auto",
                     help="auto = capítulos se houver, senão por tamanho (padrão)")
    div.add_argument("--pages-per-part", type=int, default=10, help="páginas por parte com --split pages")
    div.add_argument("--minutes-per-part", type=float, default=15,
                     help="duração aproximada de cada parte com --split size (padrão: 15)")
    div.add_argument("--outline-level", type=int, help="nível do sumário para capítulos (0 = mais alto)")
    div.add_argument("--merge", action="store_true", help="também gera um único arquivo com tudo")

    ext = p.add_argument_group("extração e saída")
    ext.add_argument("--extractor", choices=["pypdf", "pdfplumber"], default="pypdf",
                     help="biblioteca de extração (tente pdfplumber se o texto sair embaralhado)")
    ext.add_argument("--keep-urls", action="store_true", help="não remover links do texto")
    ext.add_argument("--srt", action="store_true", help="gera legendas .srt sincronizadas para cada parte")
    ext.add_argument("--save-text", action="store_true", help="salva o texto limpo de cada parte em .txt")
    ext.add_argument("--dry-run", action="store_true", help="só extrai/limpa/divide, sem gerar áudio")
    ext.add_argument("--overwrite", action="store_true", help="regera partes que já existem")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def settings_from_args(args: argparse.Namespace) -> VoiceSettings:
    cli = {k: getattr(args, k) for k in ("engine", "voice", "rate", "volume", "pitch", "expressiveness")}
    return resolve_settings(cli, args.preset)


# --------------------------------------------------------------------------- #
# Motor de voz, amostras e reprodução
# --------------------------------------------------------------------------- #


def build_engine(s: VoiceSettings, concurrency: int = 3):
    from .tts import get_engine

    return get_engine(s.engine, voice=s.voice, rate=s.rate, volume=s.volume, pitch=s.pitch,
                      expressiveness=s.expressiveness, concurrency=concurrency)


def play(path: Path) -> None:
    """Toca o áudio com o player do sistema (sem dependências extras)."""
    system = platform.system()
    candidates = (
        [["afplay", str(path)]] if system == "Darwin" else
        [["paplay", str(path)], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
         ["mpv", "--really-quiet", str(path)], ["aplay", str(path)]]
    )
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False)
            except KeyboardInterrupt:
                pass  # Ctrl+C só interrompe a amostra
            return
    if system == "Windows":
        import os

        os.startfile(path)  # type: ignore[attr-defined]
        return
    print(f"  (abra o arquivo para ouvir: {path})")


def make_preview(s: VoiceSettings, text: str, name: str = "ronic-amostra", autoplay: bool = True) -> Path:
    engine = build_engine(s)
    path = Path(tempfile.gettempdir()) / f"{safe_filename(name)}{engine.extension}"
    print(f"  Amostra: {describe(s)}")
    engine.synthesize_part(chunk_text(text), path, label="  amostra")
    print(f"  Salva em {path}")
    if autoplay:
        play(path)
    return path


def compare_voices(base: VoiceSettings, text: str, autoplay: bool = True) -> None:
    """Gera (e toca) a mesma frase em cada voz, para escolher de ouvido."""
    voices = ([(full, desc) for _, full, desc in EDGE_PT_VOICES] if base.engine == "edge" else PIPER_PT_VOICES)
    for i, (voice, desc) in enumerate(voices, 1):
        print(f"\n[{i}/{len(voices)}] {voice} — {desc}")
        s = VoiceSettings(**{**base.__dict__, "voice": voice})
        try:
            make_preview(s, text, name=f"ronic-amostra-{voice}", autoplay=autoplay)
        except Exception as exc:  # ex.: voz Piper indisponível para download
            print(f"  ! não foi possível gerar: {exc}")


def print_voices() -> None:
    from .tts.edge import list_voices

    print("Vozes edge-tts (online, grátis) — atalhos: francisca, antonio, thalita, raquel, duarte")
    for v in asyncio.run(list_voices("pt-")):
        print(f"  {v['ShortName']:<35} {v['Gender']}")
    print("\nVozes Piper (offline) em pt-BR:")
    for name, desc in PIPER_PT_VOICES:
        print(f"  {name:<35} {desc}")
    print("  lista completa: https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR")
    print("\nPredefinições (--preset):")
    for k, v in PRESET_HELP.items():
        cfg = PRESETS[k]
        print(f"  {k:<10} {v}  (velocidade {cfg['rate']}, tom {cfg['pitch']}, volume {cfg['volume']})")


# --------------------------------------------------------------------------- #
# Modo interativo
# --------------------------------------------------------------------------- #


def pick_pdf_dialog() -> Path | None:
    """Abre uma janela para escolher o PDF (tkinter, ou AppleScript no macOS)."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title="Escolha o PDF", filetypes=[("PDF", "*.pdf")])
        root.destroy()
        return Path(path) if path else None
    except Exception:
        pass

    if platform.system() == "Darwin":
        script = 'POSIX path of (choose file with prompt "Escolha o PDF" of type {"com.adobe.pdf"})'
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None

    if shutil.which("zenity"):
        res = subprocess.run(["zenity", "--file-selection", "--file-filter=*.pdf"], capture_output=True, text=True)
        return Path(res.stdout.strip()) if res.returncode == 0 else None
    return None


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _ask_valid(prompt: str, current, normalizer):
    while True:
        try:
            return normalizer(ask(prompt, str(current)))
        except ValueError as exc:
            print(f"  {exc}")


def calibrate(s: VoiceSettings, sample: str) -> VoiceSettings:
    """Menu para trocar voz e ajustar intensidades, ouvindo o resultado a cada mudança."""
    while True:
        print(f"\nVoz atual: {describe(s)}")
        print("  1) ouvir amostra        2) trocar voz          3) usar predefinição\n"
              "  4) velocidade           5) volume/intensidade  6) " +
              ("tom (grave/agudo)" if s.engine == "edge" else "expressividade") + "\n"
              "  7) comparar todas as vozes   8) trocar motor (edge online / piper offline)\n"
              "  Enter) está bom, continuar")
        op = ask("Opção")
        if not op:
            return s
        try:
            if op == "1":
                make_preview(s, sample)
            elif op == "2":
                if s.engine == "edge":
                    for i, (alias, _, desc) in enumerate(EDGE_PT_VOICES, 1):
                        print(f"   {i}) {alias:<10} {desc}")
                    c = ask("Voz (número ou nome completo)", "1")
                    s.voice = EDGE_PT_VOICES[int(c) - 1][1] if c.isdigit() else c
                else:
                    for i, (name, desc) in enumerate(PIPER_PT_VOICES, 1):
                        print(f"   {i}) {name:<22} {desc}")
                    c = ask("Voz (número ou nome do modelo)", "1")
                    s.voice = PIPER_PT_VOICES[int(c) - 1][0] if c.isdigit() else c
                make_preview(s, sample)
            elif op == "3":
                names = list(PRESETS)
                for i, k in enumerate(names, 1):
                    print(f"   {i}) {k:<10} {PRESET_HELP[k]}")
                c = ask("Predefinição", "1")
                preset = names[int(c) - 1] if c.isdigit() else c
                for k, v in PRESETS[preset].items():
                    setattr(s, k, v)
                make_preview(s, sample)
            elif op == "4":
                s.rate = _ask_valid("Velocidade (-50% lento .. +100% rápido)", s.rate, normalize_rate)
                make_preview(s, sample)
            elif op == "5":
                s.volume = _ask_valid("Volume (-50% .. +50%)", s.volume, normalize_volume)
                make_preview(s, sample)
            elif op == "6" and s.engine == "edge":
                s.pitch = _ask_valid("Tom (-50Hz grave .. +50Hz agudo)", s.pitch, normalize_pitch)
                make_preview(s, sample)
            elif op == "6":
                s.expressiveness = _ask_valid("Expressividade (0 monótono .. 1 expressivo)",
                                              s.expressiveness, normalize_expressiveness)
                make_preview(s, sample)
            elif op == "7":
                compare_voices(s, sample)
            elif op == "8":
                s.engine = "piper" if s.engine == "edge" else "edge"
                s.voice = None
                print(f"  Motor agora: {s.engine}")
        except (ValueError, IndexError, KeyError) as exc:
            print(f"  Opção inválida: {exc}")
        except Exception as exc:
            print(f"  ! erro ao gerar amostra: {exc}")


def interactive(args: argparse.Namespace) -> argparse.Namespace:
    print("=== Ronic Reader — modo interativo ===\n")
    pdf = pick_pdf_dialog()
    if not pdf:
        typed = ask("Caminho do PDF (pode arrastar o arquivo para cá)")
        pdf = Path(typed.strip("'\" ")).expanduser() if typed else None
    if not pdf:
        sys.exit("Nenhum PDF escolhido.")
    args.pdf = pdf
    print(f"PDF: {pdf}  ({count_pages(pdf)} páginas)")
    args.pages = ask("Páginas (ex.: 5-20; Enter = todas)") or None

    settings = calibrate(settings_from_args(args), sample_from_pdf(args) or SAMPLE_TEXT)
    args.settings = settings
    if ask("Salvar esta voz como padrão para as próximas vezes? (s/N)", "n").lower().startswith("s"):
        print(f"  Salvo em {save_config(settings)}")

    modes = {"1": "auto", "2": "chapters", "3": "pages", "4": "size", "5": "none"}
    print("\nDivisão: 1) automática  2) capítulos  3) a cada N páginas  4) por duração  5) arquivo único")
    args.split = modes.get(ask("Escolha", "1"), "auto")
    if args.split == "pages":
        args.pages_per_part = int(ask("Páginas por parte", str(args.pages_per_part)))
    elif args.split == "size":
        args.minutes_per_part = float(ask("Minutos por parte", str(int(args.minutes_per_part))))
    args.merge = ask("Gerar também um arquivo único com tudo? (s/N)", "n").lower().startswith("s")
    print()
    return args


# --------------------------------------------------------------------------- #
# Fluxo principal
# --------------------------------------------------------------------------- #


def sample_from_pdf(args: argparse.Namespace, max_chars: int = 450) -> str | None:
    """Primeiro trecho "de verdade" do PDF, para testar a voz com o conteúdo real."""
    if not args.pdf:
        return None
    pdf = args.pdf.expanduser()
    pages = parse_page_range(args.pages, count_pages(pdf))[:5]
    text = "\n\n".join(p.text for p in clean_pages(extract_pages(pdf, pages, args.extractor)))
    sample = ""
    for para in (p for p in text.split("\n\n") if len(p) > 60):
        sample = f"{sample} {para}".strip()
        if len(sample) >= max_chars:
            break
    if len(sample) > max_chars:
        cut = sample.rfind(". ", 0, max_chars)
        sample = sample[: cut + 1] if cut > 100 else sample[:max_chars]
    return sample or None


def fmt_minutes(m: float) -> str:
    return f"{int(m // 60)}h{int(m % 60):02d}min" if m >= 60 else f"{m:.0f}min"


def print_summary(parts: list[Part], strategy: str) -> None:
    print(f"\nDivisão usada: {strategy} — {len(parts)} parte(s)")
    print(f"  {'#':>3}  {'páginas':<9} {'duração':>8}  título")
    for i, part in enumerate(parts, 1):
        pages = f"{part.first_page}-{part.last_page}"
        print(f"  {i:>3}  {pages:<9} {'~' + fmt_minutes(part.minutes):>8}  {part.title[:60]}")
    print(f"  Total estimado: ~{fmt_minutes(sum(p.minutes for p in parts))} de áudio\n")


def run(args: argparse.Namespace, settings: VoiceSettings) -> int:
    pdf: Path = args.pdf.expanduser().resolve()
    if not pdf.exists():
        print(f"Arquivo não encontrado: {pdf}", file=sys.stderr)
        return 1

    # 1) Extração ----------------------------------------------------------
    from .epub import is_epub

    if is_epub(pdf):  # EPUB: texto já limpo, capítulos do próprio sumário
        from .epub import paginate, read_epub
        from .extractor import OutlineItem, Page

        eb = read_epub(pdf)
        by_page: dict[int, list[str]] = {}
        outline = []
        seen = set()
        for page, block, ci in paginate(eb):
            by_page.setdefault(page, []).append(block.text)
            if ci not in seen:
                seen.add(ci)
                outline.append(OutlineItem(eb.chapters[ci].title, page, 0))
        pages = [Page(n, "\n\n".join(t)) for n, t in sorted(by_page.items())]
        print(f"Lendo {pdf.name}: EPUB, {len(eb.chapters)} capítulos")
        return _synthesize(args, settings, pdf, pages, outline)

    total = count_pages(pdf)
    pages_wanted = parse_page_range(args.pages, total)
    print(f"Lendo {pdf.name}: {len(pages_wanted)} de {total} páginas ({args.extractor})...")
    raw_pages = extract_pages(pdf, pages_wanted, engine=args.extractor)

    empty = sum(1 for p in raw_pages if len(p.text.strip()) < 20)
    if empty == len(raw_pages):
        print("Nenhum texto encontrado. O PDF parece ser escaneado (imagem).\n"
              "Rode um OCR gratuito antes, ex.:  brew install ocrmypdf && "
              "ocrmypdf -l por entrada.pdf saida.pdf", file=sys.stderr)
        return 2
    if empty > len(raw_pages) * 0.3:
        print(f"! {empty} página(s) sem texto (imagens/escaneadas) serão puladas.")

    # 2) Limpeza e divisão ------------------------------------------------
    pages = clean_pages(raw_pages, keep_urls=args.keep_urls)
    return _synthesize(args, settings, pdf, pages, extract_outline(pdf))


def _synthesize(args, settings: VoiceSettings, pdf: Path, pages, outline) -> int:
    parts, strategy = make_parts(
        pages, outline, args.split,
        pages_per_part=args.pages_per_part,
        max_chars=int(args.minutes_per_part * 900),
        outline_level=args.outline_level,
    )
    if not parts:
        print("Nada para ler depois da limpeza.", file=sys.stderr)
        return 2
    print_summary(parts, strategy)

    out_dir: Path = (args.output or pdf.with_name(f"{pdf.stem}_audio")).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    names = [f"{i:02d} - {safe_filename(p.title)}" for i, p in enumerate(parts, 1)]

    if args.save_text or args.dry_run:
        for name, part in zip(names, parts):
            (out_dir / f"{name}.txt").write_text(part.text, encoding="utf-8")
        print(f"Texto limpo salvo em {out_dir}/")
    if args.dry_run:
        return 0

    # 3) Síntese de voz --------------------------------------------------
    engine = build_engine(settings, args.concurrency)
    print(f"Voz: {describe(settings)}\nSaída: {out_dir}\n")

    start = time.time()
    audio_files: list[Path] = []
    try:
        for i, (name, part) in enumerate(zip(names, parts), 1):
            target = out_dir / f"{name}{engine.extension}"
            audio_files.append(target)
            if target.exists() and not args.overwrite:
                print(f"  [{i}/{len(parts)}] já existe, pulando: {target.name}")
                continue
            print(f"  [{i}/{len(parts)}] {part.title[:60]}")
            cues = engine.synthesize_part(chunk_text(part.text), target, label=f"[{i}/{len(parts)}]")
            if args.srt:
                write_srt(cues, target.with_suffix(".srt"))
    except KeyboardInterrupt:
        print("\n\nInterrompido. Rode o mesmo comando de novo para continuar de onde parou.")
        return 130

    # 4) Arquivos extras --------------------------------------------------
    write_playlist(audio_files, out_dir / f"{safe_filename(pdf.stem)}.m3u")
    if args.merge and len(audio_files) > 1:
        merged = out_dir / f"{safe_filename(pdf.stem)} - completo{engine.extension}"
        merge_audio(audio_files, merged)
        print(f"\nArquivo único: {merged.name}")

    elapsed = time.time() - start
    print(f"\nPronto em {elapsed / 60:.1f} min. {len(audio_files)} arquivo(s) em: {out_dir}")
    return 0


SIGNED_OPTIONS = {"--rate", "--volume", "--pitch"}


def _fix_negative_values(argv: list[str]) -> list[str]:
    """Transforma ["--volume", "-10%"] em ["--volume=-10%"] para o argparse aceitar."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] in SIGNED_OPTIONS and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    argv = _fix_negative_values(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        if args.list_voices:
            print_voices()
            return 0

        settings = settings_from_args(args)
        if args.save_config:
            print(f"Ajustes salvos como padrão em {save_config(settings)}:\n  {describe(settings)}")

        if args.preview or args.compare_voices:
            text = args.preview_text or sample_from_pdf(args) or SAMPLE_TEXT
            if args.compare_voices:
                compare_voices(settings, text, autoplay=not args.no_play)
            else:
                make_preview(settings, text, autoplay=not args.no_play)
            return 0

        if args.pdf is None:
            if args.save_config:
                return 0  # só queria salvar a configuração
            args = interactive(args)
            settings = args.settings
        return run(args, settings)
    except ValueError as exc:  # ex.: intervalo de páginas ou ajuste de voz inválido
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
