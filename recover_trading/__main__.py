"""Public demo market data smoke check; never submits orders."""
import argparse
import json
from .broker import DeltaDemo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    args = parser.parse_args()
    print(json.dumps(DeltaDemo().ticker(args.symbol), indent=2))


if __name__ == "__main__":
    main()
