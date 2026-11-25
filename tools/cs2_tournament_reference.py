"""Read the three public tournament scorecards through their ordinary rendered pages."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

MATCHES = {
    "vertigo": "furia-vs-pain-gaming-07-12-2024",
    "cache": "furia-vs-faze-02-11-2026",
    "train": "furia-vs-g2-04-11-2025",
}


def main():
    out = Path("build/pro-tournaments")
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as web:
        browser = web.chromium.launch()
        for name, slug in MATCHES.items():
            pg = browser.new_page()
            public = []
            def response(item):
                url = urlsplit(item.url)
                if url.hostname == "api.bo3.gg" and item.ok and any(
                    key in url.path for key in ("match-games", "games/", "rounds", "player-stats")
                ) and "json" in item.headers.get("content-type", ""):
                    try:
                        public.append({"path":url.path, "data":item.json()})
                    except Exception:
                        pass  # a navigation can cancel an outstanding page request
            pg.on("response", response)
            for tab in ("", "/grenades", "/economy"):
                url = f"https://bo3.gg/matches/{slug}/{name}{tab}"
                pg.goto(url, wait_until="domcontentloaded",timeout=90000)
                pg.get_by_text("FURIA",exact=False).first.wait_for(timeout=90000)
                pg.wait_for_timeout(2500)
                body = pg.locator("body").inner_text()
                (out / (name + (tab or "/score").replace("/", "-") + ".txt")).write_text(body)
                print(url,len(body),flush=True)
            (out / (name+"-round-data.json")).write_text(json.dumps(public))
            print(name, [(r["path"], len(str(r["data"]))) for r in public], flush=True)
            pg.close()
        browser.close()


if __name__ == "__main__":
    main()
