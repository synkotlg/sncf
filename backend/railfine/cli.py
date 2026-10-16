"""Ligne de commande : lancement du serveur, mise à jour des données, exemples fictifs."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import AppConfig


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_serve(args) -> None:
    import os

    import uvicorn

    from .main import create_app

    if args.host:
        os.environ["RAILFINE_HOST"] = args.host
    if args.port:
        os.environ["RAILFINE_PORT"] = str(args.port)
    cfg = AppConfig()
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        print("ATTENTION : le serveur écoute sur une interface réseau non locale. Vos amendes seraient accessibles "
              "depuis le réseau. Usage déconseillé.", file=sys.stderr)
    print(f"RailFine Analytics : http://{cfg.host}:{cfg.port}")
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


def cmd_update(args) -> None:
    from .reference.update import DEFAULT_GROUPS, run_update

    cfg = AppConfig()
    groups = tuple(g.strip() for g in args.groups.split(",")) if args.groups else DEFAULT_GROUPS
    files = {}
    if args.gtfs_sncf:
        files["sncf_gtfs"] = Path(args.gtfs_sncf)
    if args.gtfs_sncb:
        files["sncb_gtfs"] = Path(args.gtfs_sncb)
    report = run_update(cfg, groups, progress=lambda m: print("  " + m), gtfs_files=files)
    from .user.service import FineService

    n = FineService(cfg).relocate_all()
    print(f"\n{n} amende(s) recalculée(s) sur le nouveau référentiel.")
    failed = {k: v for k, v in report.items() if isinstance(v, dict) and v.get("status") in ("indisponible", "erreur")}
    if failed:
        print("\nSources non importées :")
        for k, v in failed.items():
            print(f" - {k} : {v['status']} - {v.get('message', '')[:300]}")


def cmd_gtfs(args) -> None:
    from .reference.update import import_gtfs_file

    cfg = AppConfig()
    print(json.dumps(import_gtfs_file(cfg, args.source, Path(args.file)), indent=1))
    from .user.service import FineService

    FineService(cfg).relocate_all()


def cmd_status(args) -> None:
    from .reference.store import ReferenceStore

    cfg = AppConfig()
    store = ReferenceStore(cfg.paths.reference_db)
    print(json.dumps({"version": store.version(), "counts": store.counts(), "runs": store.source_runs()}, indent=1, ensure_ascii=False))


def cmd_demo(args) -> None:
    from .demo import load_demo_fines, write_sample_documents
    from .user.service import FineService

    cfg = AppConfig()
    svc = FineService(cfg)
    if args.action == "load":
        if svc.store.counts()["demo_fines"]:
            print("Données d'exemple déjà présentes.")
            return
        print(f"{load_demo_fines(svc)} amendes FICTIVES ajoutées (marquées « exemple »).")
    elif args.action == "remove":
        res = svc.store.delete_demo()
        for name in res.pop("stored_names"):
            (cfg.paths.documents_dir / name).unlink(missing_ok=True)
        print(f"Supprimé : {res}")
    elif args.action == "documents":
        out = Path(args.out or (cfg.paths.exports_dir / "exemples-fictifs"))
        for p in write_sample_documents(out):
            print(f"  {p}")


def cmd_rematch(args) -> None:
    from .user.service import FineService

    print(f"{FineService(AppConfig()).relocate_all()} amende(s) recalculée(s).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="railfine", description="RailFine Analytics - France & Belgique")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="lancer l'application (http://127.0.0.1:8000)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    data = sub.add_parser("data", help="données de référence ferroviaires")
    dsub = data.add_subparsers(dest="data_command")
    p = dsub.add_parser("update", help="télécharger / mettre à jour les sources ouvertes")
    p.add_argument("--groups", help="base,sncf,infrabel,osm,gtfs (défaut : base,sncf,infrabel,gtfs)")
    p.add_argument("--gtfs-sncf", help="fichier GTFS SNCF local (ZIP) au lieu du téléchargement")
    p.add_argument("--gtfs-sncb", help="fichier GTFS SNCB local (ZIP) au lieu du téléchargement")
    p.set_defaults(func=cmd_update)
    p = dsub.add_parser("gtfs", help="importer un fichier GTFS local")
    p.add_argument("--source", choices=["sncf_gtfs", "sncb_gtfs"], required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_gtfs)
    p = dsub.add_parser("status", help="état du référentiel")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("demo", help="données d'exemple FICTIVES")
    p.add_argument("action", choices=["load", "remove", "documents"])
    p.add_argument("--out", help="dossier de sortie des documents fictifs")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("rematch", help="recalculer la géolocalisation de toutes les amendes")
    p.set_defaults(func=cmd_rematch)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    if not getattr(args, "func", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
