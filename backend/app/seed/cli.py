"""Seeding CLI: ``python -m app.seed.cli [--reset] [--count N]``."""

from __future__ import annotations

import argparse
import json
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.seed.generator import seed_database

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    settings = get_settings()
    parser = argparse.ArgumentParser(description=f"Seed the {settings.product_name} database.")
    parser.add_argument("--count", type=int, default=settings.seed_customer_count, help="number of customers")
    parser.add_argument("--seed", type=int, default=settings.seed_random_seed, help="random seed")
    parser.add_argument("--reset", action="store_true", help="delete existing customer data first")
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="skip embedding generation (semantic retrieval will return nothing)",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    arguments = parser.parse_args(argv)

    def progress(done: int, total: int) -> None:
        percent = done / total * 100 if total else 100
        print(f"  seeded {done:,}/{total:,} customers ({percent:.0f}%)", file=sys.stderr)

    print(
        f"Seeding {arguments.count:,} customers "
        f"(seed={arguments.seed}, embeddings={'off' if arguments.no_embed else settings.effective_embedding_provider})",
        file=sys.stderr,
    )
    with session_scope() as session:
        stats = seed_database(
            session,
            customer_count=arguments.count,
            seed=arguments.seed,
            reset=arguments.reset,
            embed=not arguments.no_embed,
            batch_size=arguments.batch_size,
            progress=progress,
        )

    print(json.dumps(stats.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
