"""Read opt-in public metadata, with a positive license and identity match per image."""

import html
import json
import re
import time
import unicodedata
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

AGENT = "EsportSim/1.0 (https://github.com/Troyevv/esport_sim; studio portraits)"
API = "https://commons.wikimedia.org/w/api.php"
COMMONS = {"commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"}
LICENSES = {
    f"https://creativecommons.org/licenses/{kind}/{v}/": f"CC {kind.upper()} {v}"
    for kind in ("by", "by-sa")
    for v in ("2.0", "3.0", "4.0")
}
LICENSES["https://creativecommons.org/publicdomain/zero/1.0/"] = "CC0"
TYPES = (
    "headshot",
    "hero shot",
    "official roster portrait",
    "media day portrait",
    "transparent PNG",
)
STUDIO = re.compile(
    r"head.?shot|hero shot|roster (?:portrait|photo)|player (?:portrait|headshot)|studio (?:portrait|photo)|press portrait|official portrait|media.?day (?:portrait|photo.?shoot)|медиа.?дн.{0,20}портрет|студийн|портрет состава|joueur.*studio",
    re.I,
)
UNSUITABLE = re.compile(
    r"interview|backstage|screens?hot|with (?:a |the )?troph|crowd|headset|full.length|full.body|playing at|интервью|в полный рост|скриншот|наушник|за монитором",
    re.I,
)


class Unavailable(RuntimeError):
    def __init__(self, message, delay=30):
        super().__init__(message)
        self.delay = delay


def plain(text):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", str(text))).split())


def normalized(text):
    return " ".join(
        "".join(
            c if c.isalnum() else " "
            for c in unicodedata.normalize("NFKD", plain(text)).casefold()
            if not unicodedata.combining(c)
        ).split()
    )


def contains(text, term):
    return bool(term and " " + normalized(term) + " " in " " + normalized(text) + " ")


def matches(person, description):
    nick = contains(description, person["name"])
    real = contains(description, person.get("realName"))
    esports = bool(
        re.search(r"counter.?strike|cs.?2\b|cs:?go|esports?", description, re.I)
    )
    team = contains(description, person.get("team"))
    return (real and (nick or esports or team)) or (
        nick and team and esports and len(normalized(person["name"])) >= 3
    )


def allowed_url(url, hosts):
    u = urlsplit(url)
    return (
        u.scheme == "https"
        and u.hostname in hosts
        and u.port in (None, 443)
        and not u.username
        and not u.password
    )


def fetch(url, hosts, limit):
    if not allowed_url(url, hosts):
        raise ValueError("Неразрешённый адрес источника")

    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allowed_url(newurl, hosts):
                raise ValueError("Переадресация за пределы источника")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    try:
        with build_opener(Redirect()).open(
            Request(url, headers={"User-Agent": AGENT}), timeout=12
        ) as response:
            data = response.read(limit + 1)
    except HTTPError as exc:
        if exc.code in (404, 410):
            return b""
        hint = exc.headers.get("Retry-After", "")
        raise Unavailable(
            f"Источник вернул HTTP {exc.code}", int(hint) if hint.isdigit() else 60
        ) from exc
    except (OSError, URLError) as exc:
        raise Unavailable("Источник временно недоступен") from exc
    if len(data) > limit:
        raise ValueError("Файл превышает лимит загрузки")
    return data


def commons_candidate(page, person, linked=False):
    info = next(iter(page.get("imageinfo", ())), {})
    fields = info.get("extmetadata", {})

    def value(k):
        return plain(fields.get(k, {}).get("value", ""))

    title = page.get("title", "")
    detail = " ".join((title, value("ImageDescription"), value("Categories")))
    if (
        (not linked and not matches(person, detail))
        or not STUDIO.search(detail)
        or UNSUITABLE.search(detail)
    ):
        return
    # Owner rejected this full-length frame, including derivative crops.
    if "19.01.202531303" in detail:
        return
    license_url = value("LicenseUrl").replace("http://", "https://").rstrip("/") + "/"
    license = LICENSES.get(license_url)
    if not license or not 0 < len(value("Artist")) <= 240 or value("Restrictions"):
        return
    if (
        info.get("mime") not in ("image/jpeg", "image/png", "image/webp")
        or min(info.get("height", 0), info.get("width", 0)) < 400
    ):
        return
    source = info.get("descriptionurl", "")
    url = info.get("thumburl") or info.get("url", "")
    if not allowed_url(source, {"commons.wikimedia.org"}) or not allowed_url(
        url, COMMONS
    ):
        return
    return dict(
        image=url,
        source=source,
        author=value("Artist"),
        license=license,
        assetKey=info.get("sha1") or source,
        hosts=sorted(COMMONS),
        title=title,
    )


def commons_search(person, read=fetch, pause=time.sleep):
    # Metadata and source bytes are obtained through the documented Commons API.
    seen = set()
    for term in TYPES:
        params = dict(
            action="query",
            format="json",
            generator="search",
            gsrnamespace=6,
            gsrlimit=8,
            gsrsearch=f'"{person["name"].replace(chr(34), "")}" "{term}"',
            prop="imageinfo",
            iiprop="url|size|mime|sha1|extmetadata",
            iiurlwidth=1200,
            maxlag=5,
        )
        data = json.loads(read(API + "?" + urlencode(params), COMMONS, 2_000_000))
        if "error" in data:
            raise Unavailable("Wikimedia: " + str(data["error"].get("code", "API")))
        for page in data.get("query", {}).get("pages", {}).values():
            item = commons_candidate(page, person)
            if item and item["assetKey"] not in seen:
                seen.add(item["assetKey"])
                yield item
        pause(1)


def wikidata_candidates(person, read):
    """P18 is a primary identity link, but does not establish a studio context or license."""
    real = person.get("realName")
    if not real:
        return
    hosts = {"www.wikidata.org"}

    def api(**args):
        return json.loads(
            read(
                "https://www.wikidata.org/w/api.php?"
                + urlencode(dict(format="json", **args)),
                hosts,
                2_000_000,
            )
        )

    hits = api(action="wbsearchentities", language="en", search=real, limit=5).get(
        "search", []
    )
    ids = [x["id"] for x in hits if normalized(x.get("label", "")) == normalized(real)]
    if not ids:
        return
    entities = api(
        action="wbgetentities",
        ids="|".join(ids),
        props="claims|aliases|labels",
        languages="en|ru",
    ).get("entities", {})
    for ent in entities.values():
        claims = ent.get("claims", {})
        aliases = [
            a["value"] for group in ent.get("aliases", {}).values() for a in group
        ]
        hltv = [
            str(v.get("mainsnak", {}).get("datavalue", {}).get("value", ""))
            for v in claims.get("P8878", [])
        ]
        if not hltv or not (
            any(normalized(a) == normalized(person["name"]) for a in aliases)
            or any(
                normalized(v.split("/")[-1]) == normalized(person["name"]) for v in hltv
            )
        ):
            continue
        for item in claims.get("P18", [])[:2]:
            title = item.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not isinstance(title, str):
                continue
            query = dict(
                action="query",
                format="json",
                titles="File:" + title,
                prop="imageinfo",
                iiprop="url|size|mime|sha1|extmetadata",
                iiurlwidth=1200,
                maxlag=5,
            )
            response = json.loads(
                read(API + "?" + urlencode(query), COMMONS, 2_000_000)
            )
            for page in response.get("query", {}).get("pages", {}).values():
                photo = commons_candidate(page, person, linked=True)
                if photo:
                    yield photo


def flickr_candidates(person, read, pause, key):
    """Optional official API; only the specific photo's current license is authoritative."""
    hosts = {"www.flickr.com", "api.flickr.com"}

    def api(method, **args):
        url = "https://api.flickr.com/services/rest/?" + urlencode(
            dict(
                method="flickr." + method,
                api_key=key,
                format="json",
                nojsoncallback=1,
                **args,
            )
        )
        data = json.loads(read(url, hosts, 1_500_000))
        if data.get("stat") != "ok":
            raise Unavailable("Flickr API временно недоступен")
        return data

    licenses = {
        str(v["id"]): LICENSES[url]
        for v in api("photos.licenses.getInfo")["licenses"]["license"]
        if (url := v.get("url", "").replace("http://", "https://").rstrip("/") + "/")
        in LICENSES
    }
    if not licenses:
        return
    for term in TYPES:
        photos = api(
            "photos.search",
            text=person["name"] + " " + term,
            license=",".join(licenses),
            media="photos",
            safe_search=1,
            content_type=1,
            per_page=8,
            extras="description,tags,owner_name,url_l,url_o",
        )
        for thumb in photos.get("photos", {}).get("photo", []):
            summary = " ".join(
                (
                    thumb["title"],
                    thumb.get("description", {}).get("_content", ""),
                    thumb.get("tags", ""),
                )
            )
            if (
                not matches(person, summary)
                or not STUDIO.search(summary)
                or UNSUITABLE.search(summary)
            ):
                continue
            info = api("photos.getInfo", photo_id=thumb["id"])["photo"]
            detail = " ".join(
                [
                    info["title"]["_content"],
                    info["description"]["_content"],
                    *[t.get("raw", "") for t in info.get("tags", {}).get("tag", [])],
                ]
            )
            lic = licenses.get(str(info.get("license", "")))
            if (
                not lic
                or not matches(person, detail)
                or not STUDIO.search(detail)
                or UNSUITABLE.search(detail)
            ):
                continue
            url = thumb.get("url_l") or thumb.get("url_o")
            if not url or not allowed_url(url, {"live.staticflickr.com"}):
                continue
            owner = info["owner"]
            yield dict(
                image=url,
                source=f"https://www.flickr.com/photos/{quote(owner['nsid'], safe='@')}/{info['id']}/",
                author=owner.get("realname") or owner["username"],
                license=lic,
                title=thumb["title"],
                hosts=["live.staticflickr.com"],
                assetKey="flickr-"
                + info["id"]
                + "-"
                + str(info.get("dates", {}).get("lastupdate", "")),
            )
        pause(1)


def discover(person, read=fetch, pause=time.sleep):
    import os

    providers = [
        lambda: team_press_candidates(person, read, pause),
        lambda: wikidata_candidates(person, read),
        lambda: commons_search(person, read, pause),
    ]
    if key := os.environ.get("ESPORTSIM_FLICKR_API_KEY"):
        providers.append(lambda: flickr_candidates(person, read, pause, key))
    failures = []
    seen = set()
    for provider in providers:
        try:
            for candidate in provider():
                if candidate["assetKey"] not in seen:
                    seen.add(candidate["assetKey"])
                    yield candidate
        except Unavailable as e:
            failures.append(e)
    # The caller can retry incomplete searches. A temporary denial is never a
    # permanent declaration that a player does not have an eligible portrait.
    if failures:
        raise failures[0]


class LinkedData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = None
        self.docs = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.parts = []

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.parts is not None:
            try:
                self.docs.append(json.loads("".join(self.parts)))
            except ValueError:
                pass  # A malformed JSON-LD tag confers no permission.
            self.parts = None


def team_press_candidates(person, read, pause):
    from urllib.robotparser import RobotFileParser

    if normalized(person.get("team", "")) not in ("vitality", "team vitality"):
        return
    host = "vitality.gg"
    hosts = {host, "www.vitality.gg", "cdn.shopify.com"}
    page = "https://vitality.gg/en/pages/athletes/" + quote(
        person["name"].lower(), safe=""
    )
    robots = RobotFileParser()
    rules = read("https://" + host + "/robots.txt", {host}, 250_000).decode(
        "utf-8", errors="replace"
    )
    robots.parse(rules.splitlines())
    if not robots.can_fetch(AGENT, page):
        return
    delay = robots.crawl_delay(AGENT) or robots.crawl_delay("*") or 1
    pause(delay)
    markup = read(page, {host}, 2_000_000)
    parser = LinkedData()
    parser.feed(markup.decode("utf-8", errors="replace"))

    def nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from nodes(child)
        if isinstance(value, list):
            for child in value:
                yield from nodes(child)

    for node in nodes(parser.docs):
        if node.get("@type") != "ImageObject":
            continue
        label = " ".join(
            plain(node.get(k, "")) for k in ("name", "caption", "description")
        )
        license = LICENSES.get(str(node.get("license", "")).rstrip("/") + "/")
        creator = node.get("creator")
        author = creator.get("name") if isinstance(creator, dict) else creator
        url = node.get("contentUrl")
        if not (
            license
            and isinstance(url, str)
            and allowed_url(url, hosts)
            and isinstance(author, str)
            and 0 < len(author) <= 240
        ):
            continue
        if (
            not (
                contains(label, person["name"])
                or contains(label, person.get("realName"))
            )
            or not STUDIO.search(label)
            or UNSUITABLE.search(label)
        ):
            continue
        yield dict(
            image=url,
            source=page,
            author=author,
            license=license,
            assetKey=url,
            title=label,
            hosts=sorted(hosts),
        )
