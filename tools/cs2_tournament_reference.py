"""Preserve the public per-map BO3.gg scorecards for three historical tournaments."""
import gzip
from pathlib import Path
from urllib.request import Request, urlopen

MATCHES = {
    "vertigo": "furia-vs-pain-gaming-07-12-2024",
    "cache": "furia-vs-faze-02-11-2026",
    "train": "furia-vs-g2-04-11-2025",
}


def main():
    out = Path("build/pro-tournaments")
    out.mkdir(parents=True, exist_ok=True)
    for name, slug in MATCHES.items():
        for tab in ("", "/grenades", "/economy"):
            url = f"https://bo3.gg/matches/{slug}/{name}{tab}"
            request = Request(url, headers={"User-Agent": "EsportSim/1.0 (public research scorecards)"})
            with urlopen(request, timeout=60) as response:
                page = response.read()
            if len(page) < 2000:
                raise ValueError(f"Empty scorecard at {url}")
            (out / (name + (tab or "/score").replace("/", "-") + ".html.gz")).write_bytes(gzip.compress(page))
            print(url, len(page), flush=True)


if __name__ == "__main__":
    main()
