"""Point d'entrée : `python -m reunion_resume` ou exe PyInstaller."""

from __future__ import annotations

# ============================================================================
# CRITIQUE : initialiser COM en STA AVANT tout autre import.
#
# Plusieurs deps natives (PyAV, soundcard, sounddevice, ctranslate2, mss...) sont
# susceptibles d'appeler CoInitializeEx en mode MTA pendant leur import. Une fois
# le thread principal en MTA, Qt ne peut plus initialiser OLE en STA et echoue avec
# RPC_E_CHANGED_MODE (0x80010106) -> drag-drop casse, file dialogs hangent.
#
# On gagne la course en initialisant COM en STA en tout premier. Les appels MTA
# ulterieurs renverront RPC_E_CHANGED_MODE mais COM reste STA, et la plupart des
# libs ignorent le code retour et fonctionnent quand meme.
#
# NE PAS DEPLACER ce bloc plus bas dans le fichier. Aucun import lourd au-dessus.
# ============================================================================
import sys as _sys

if _sys.platform == "win32":
    import ctypes as _ctypes
    # COINIT_APARTMENTTHREADED = 0x2 ; COINIT_DISABLE_OLE1DDE = 0x4
    _hr = _ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)
    # 0 = S_OK, 1 = S_FALSE (deja init en mode compatible). Tout le reste = pb.
    if _hr not in (0, 1):
        # On ne peut rien faire de plus depuis Python : juste garder trace
        _sys.stderr.write(f"[wrok-video] CoInitializeEx HRESULT=0x{_hr & 0xFFFFFFFF:08X}\n")

import argparse
import logging
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="wrok-video", description=__doc__)
    parser.add_argument("--cli", metavar="MEDIA", help="Mode CLI : traiter un fichier sans GUI")
    parser.add_argument("--title", help="Titre du résumé (CLI)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    # Imports absolus (compatibles `python -m reunion_resume` ET exe PyInstaller,
    # qui exécute __main__.py comme script standalone sans contexte de package).
    if args.cli:
        from reunion_resume.app import setup_logging
        from reunion_resume.config import load_config
        from reunion_resume.core.pipeline import Pipeline

        setup_logging()
        cfg = load_config()
        pipeline = Pipeline(cfg)
        try:
            res = pipeline.process_file(Path(args.cli), title=args.title,
                                         progress=lambda s, p: print(f"[{p*100:5.1f}%] {s}"))
            print(f"\nRésumé écrit : {res.output_md}")
            return 0
        finally:
            pipeline.shutdown()
    else:
        from reunion_resume.app import run_gui
        return run_gui()


if __name__ == "__main__":
    _sys.exit(main())
