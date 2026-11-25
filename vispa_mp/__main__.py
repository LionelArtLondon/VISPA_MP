"""VISPA MP. ``--download-models`` fetches Silero and the WD tagger."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="Resolve markers for image selection")
    parser.add_argument("--download-models", action="store_true")
    args = parser.parse_args()
    if args.download_models:
        from vispa_mp.models_setup import ensure
        ensure(print)
        return
    from vispa_mp.ui import run
    raise SystemExit(run())


if __name__ == "__main__":
    main()
