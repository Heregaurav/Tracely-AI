"""Explicitly publish trusted approved offline artifacts to PostgreSQL.

Publishes normalized closed-hour features, scores and observed relationships. Validation-only v5
experiments do not implement this contract and must not be activated here.
"""
import argparse
from src.db.session import database
from src.db.publish import publish_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory')
    parser.add_argument('--allow-fixture', action='store_true', help='Isolated test/development deployment ONLY')
    args = parser.parse_args()
    engine, factory = database()
    try:
        print(publish_run(factory, args.run_directory, allow_fixture=args.allow_fixture))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
