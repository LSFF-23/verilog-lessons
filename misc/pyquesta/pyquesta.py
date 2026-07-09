#!/usr/bin/env python3
"""
pyquesta - Lança o Questa GUI com compilação automática,
adiciona sinais à janela de onda e executa "run -all".
Com -c, executa em modo console (sem GUI), exibindo apenas o transcript filtrado.

Compila primeiro pacotes (arquivos com "pkg" no nome), depois os demais.
Gerencia arquivos WLF para evitar conflitos e não deixa resíduos no diretório.
Remove o arquivo "transcript" ao final da simulação.
"""

import argparse
import sys
import os
import glob
import tempfile
import subprocess
import pathlib
import datetime
import traceback
import time

def find_top_level():
    """Encontra o primeiro *_tb.v ou *_tb.sv no diretório atual."""
    patterns = ['*_tb.v', '*_tb.sv']
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    files.sort()
    return files[0] if files else None

def print_full_transcript(transcript_file='transcript'):
    """Imprime todo o conteúdo do arquivo transcript (ignorando cabeçalho)."""
    if not os.path.isfile(transcript_file):
        print("[pyquesta] Arquivo transcript não encontrado.")
        return

    with open(transcript_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    # Pular linhas de cabeçalho
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('#') and (
            '//' in line or
            'Reading pref.tcl' in line or
            'Unpublished' in line or
            'Copyright' in line or
            'Version' in line or
            'Questa' in line
        ):
            continue
        else:
            start_idx = i
            break

    print(''.join(lines[start_idx:]).rstrip())

def tail_vsim_output(proc):
    """Filtra e imprime a saída do vsim em modo console."""
    while True:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        line = line.decode('utf-8', errors='ignore').rstrip()
        if line.startswith('#') and any(k in line for k in [
            '//', 'Reading pref.tcl', 'Unpublished', 'Copyright',
            'Version', 'Questa', 'vsim', 'Loading'
        ]):
            continue
        if line.strip():
            print(line)

def main():
    parser = argparse.ArgumentParser(
        description='Simula com Questa abrindo GUI e formas de onda automaticamente.'
    )
    parser.add_argument('-i', '--input',
                        help='Arquivo top-level .v ou .sv (padrão: primeiro *_tb.v/sv)')
    parser.add_argument('-s', '--signals',
                        help='Sinais separados por vírgulas, ex.: dut.clk,dut.a')
    parser.add_argument('-c', '--console', action='store_true',
                        help='Modo console: compila e simula sem GUI, exibindo apenas o transcript.')

    args = parser.parse_args()

    # Determina o top-level
    top_file = args.input
    if top_file is None:
        top_file = find_top_level()
        if top_file is None:
            print("Erro: nenhum top-level encontrado. Use -i.", file=sys.stderr)
            sys.exit(1)
        print(f"Top-level automático: {top_file}")
    else:
        if not os.path.isfile(top_file):
            print(f"Erro: arquivo '{top_file}' não encontrado.", file=sys.stderr)
            sys.exit(1)
        print(f"Top-level: {top_file}")

    top_module = pathlib.Path(top_file).stem
    print(f"Módulo top: {top_module}")

    # --- Limpeza de resíduos de execuções anteriores ---
    for orphan in glob.glob("wlft*"):
        try:
            os.remove(orphan)
        except OSError:
            pass
    for old_wlf in glob.glob("vsim_*.wlf"):
        try:
            os.remove(old_wlf)
        except OSError:
            pass
    # Remove transcript de execuções anteriores (caso exista)
    if os.path.isfile("transcript"):
        try:
            os.remove("transcript")
        except OSError:
            pass

    # Nome único para o WLF desta simulação
    wlf_name = f"vsim_{os.getpid()}_{int(time.time())}.wlf"

    # Monta o script .do
    if args.console:
        do_content = "run -all\nquit -f\n"
    else:
        if args.signals:
            sig_list = [s.strip() for s in args.signals.split(',') if s.strip()]
            add_wave_cmd = "add wave " + " ".join(sig_list) if sig_list else "add wave *"
        else:
            add_wave_cmd = (
                "if {[catch {add wave dut/*}]} {\n"
                "    if {[catch {add wave uut/*}]} {\n"
                "        add wave *\n"
                "    }\n"
                "}"
            )
        do_content = f"""\
view wave
{add_wave_cmd}
run -all
wave zoom full
"""

    # Arquivo .do temporário
    with tempfile.NamedTemporaryFile(mode='w', suffix='.do',
                                     delete=False, encoding='utf-8') as tmp:
        tmp.write(do_content)
        do_file = tmp.name

    try:
        # Compilação
        all_v = glob.glob('*.v')
        all_sv = glob.glob('*.sv')

        # Adiciona o arquivo especificado por -i (mesmo que esteja em subpasta)
        if top_file.endswith('.v'):
            all_v.append(top_file)
        elif top_file.endswith('.sv'):
            all_sv.append(top_file)
        else:
            print(f"Extensão não suportada para {top_file}", file=sys.stderr)
            sys.exit(1)

        def is_pkg(filename):
            return 'pkg' in pathlib.Path(filename).stem.lower()

        pkg_v = sorted([f for f in all_v if is_pkg(f)])
        pkg_sv = sorted([f for f in all_sv if is_pkg(f)])
        non_pkg_v = [f for f in all_v if not is_pkg(f)]
        non_pkg_sv = [f for f in all_sv if not is_pkg(f)]

        ordered_v = pkg_v + non_pkg_v
        ordered_sv = pkg_sv + non_pkg_sv

        if ordered_v:
            print(f"Compilando {len(ordered_v)} arquivo(s) Verilog...")
            subprocess.run(['vlog'] + ordered_v, check=True)
        if ordered_sv:
            print(f"Compilando {len(ordered_sv)} arquivo(s) SystemVerilog...")
            subprocess.run(['vlog', '-sv'] + ordered_sv, check=True)

        if not all_v and not all_sv:
            print("Aviso: nenhum arquivo .v/.sv encontrado no diretório.",
                  file=sys.stderr)

        # Simulação
        if args.console:
            vsim_cmd = ['vsim', '-c', '-wlf', wlf_name, '-do', do_file, top_module]
            print(f"Iniciando simulação em console para '{top_module}'...")
            proc = subprocess.Popen(vsim_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            tail_vsim_output(proc)
            proc.wait()
        else:
            vsim_cmd = ['vsim', '-gui', '-wlf', wlf_name, '-do', do_file, top_module]
            print(f"Iniciando simulação com Questa para '{top_module}'...")
            proc = subprocess.Popen(vsim_cmd)
            proc.wait()
            print("\n--- Transcript da simulação ---")
            print_full_transcript()
            print("--- Fim do transcript ---")

        # Remove o WLF criado para esta simulação
        try:
            os.remove(wlf_name)
        except OSError:
            pass

    finally:
        # Remove o script .do temporário
        try:
            os.unlink(do_file)
        except OSError:
            pass
        # Remove o transcript gerado nesta execução
        if os.path.isfile("transcript"):
            try:
                os.remove("transcript")
            except OSError:
                pass

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        with open("pyquesta_log.txt", "a") as log_file:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{timestamp}] Error Occurred: {e}\n")
            traceback.print_exc(file=log_file)
            log_file.write("-" * 40 + "\n")
