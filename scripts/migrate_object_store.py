"""Leave the bundled MinIO for another S3-compatible store.

Run from the repo root (or in the api container) with the API settings, the
destination given by S3_BUCKET / S3_ENDPOINT_URL / S3_REGION and the AWS_*
keys:

    python -m scripts.migrate_object_store copy --dry-run   # what would be copied
    python -m scripts.migrate_object_store copy             # copy (resumable)
    python -m scripts.migrate_object_store verify           # every object there?
    python -m scripts.migrate_object_store switch           # database → S3 backend

Then set ENABLE_AWS_S3=true (and S3_PUBLIC_ENDPOINT_URL if the S3 endpoint is
internal) and restart the API. See docs/deployment/object-storage.mdx.
"""

import argparse
import asyncio
import sys

from api.services.filesystem.migration import MigrationReport, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("action", choices=["copy", "verify", "switch"])
    parser.add_argument("--dry-run", action="store_true", help="copy: only count")
    args = parser.parse_args()
    if args.action == "switch":
        answer = input(
            "Les fichiers seront lus depuis le stockage S3. Tapez BASCULER : "
        )
        if answer.strip() != "BASCULER":
            sys.exit(1)
    result = asyncio.run(run(args.action, dry_run=args.dry_run))
    if isinstance(result, MigrationReport):
        print(
            f"{result.objects} objets ({result.bytes} octets) : {result.copied} copiés, "
            f"{result.skipped} déjà présents, {len(result.missing)} manquants, "
            f"{len(result.mismatched)} de taille différente"
        )
        for key in (result.missing + result.mismatched)[:20]:
            print(f"  ✗ {key}")
        if args.action == "verify" and not result.complete:
            sys.exit(2)
    else:
        print(f"Lignes mises à jour : {result}")


if __name__ == "__main__":
    main()
