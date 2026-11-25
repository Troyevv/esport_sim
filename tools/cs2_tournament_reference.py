"""Read the original HLTV scorecards and published GOTV links for historical maps."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import urlopen

MATCHES = {
    "vertigo": (2377725, "furia-vs-pain-perfect-world-shanghai-major-2024", 189274, "pain-vs-furia"),
    "cache": (2399857, "furia-vs-faze-iem-beijing-2026", 243504, "furia-vs-faze"),
    "train": (2387393, "furia-vs-g2-iem-chengdu-2025", 212588, "furia-vs-g2"),
}


class Outcomes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rounds = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        title, src = values.get("title", ""), values.get("src", "")
        if tag == "img" and "/scoreboard/" in src and re.fullmatch(r"\d+-\d+", title):
            number = sum(map(int, title.split("-")))
            self.rounds[number] = src.split("/")[-1].split(".")[0]


def main():
    out=Path("build/pro-tournaments")
    out.mkdir(parents=True,exist_ok=True)
    for name,(match,slug,stats,teams) in MATCHES.items():
        report={"map":name,"match":match}
        for path in (f"stats/matches/mapstatsid/{stats}/{teams}",f"matches/{match}/{slug}"):
            url="https://www.hltv.org/"+path
            try:
                with urlopen(url,timeout=30) as result:
                    page=result.read().decode()
            except HTTPError as e:
                report[path]={"httpStatus":e.code}
                continue
            if path.startswith("stats/"):
                parser=Outcomes()
                parser.feed(page)
                report["rounds"]=parser.rounds
            else:
                report["demoLinks"]=sorted(set(urljoin(url,x) for x in re.findall(r'/download/demo/\d+',page)))
        (out/(name+".json")).write_text(json.dumps(report))
        print(name,report,flush=True)


if __name__=="__main__":
    main()
