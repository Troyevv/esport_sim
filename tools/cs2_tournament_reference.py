"""Read match and round metadata published by BO3.gg for maps outside patch 14141."""
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE="https://api.bo3.gg/api/v1"
MATCHES = {
    "de_vertigo":"furia-vs-pain-gaming-07-12-2024",
    "de_cache":"furia-vs-faze-02-11-2026",
    "de_train":"furia-vs-g2-04-11-2025",
}


def fetch(path, query=None):
    url=BASE+"/"+path
    if query:
        url+="?"+urlencode(query)
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def main():
    out=Path("build/pro-tournaments")
    out.mkdir(parents=True,exist_ok=True)
    for name,slug in MATCHES.items():
        metadata=fetch("matches/"+slug)
        print(name, "match", list(metadata), flush=True)
        record=metadata.get("data",metadata)
        games=fetch("match-games", {"filter[games.match_id][eq]":record["id"],"with":"rounds,game_side_results"})
        (out/(name+".json")).write_text(json.dumps(dict(match=metadata,games=games)))
        print(name, "games",list(games),str(games)[:900],flush=True)


if __name__=="__main__":
    main()
