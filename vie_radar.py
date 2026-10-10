#!/usr/bin/env python3
"""VIE Radar : collecte les offres VIE, les note selon profile.toml, publie une page web.

Python 3.11+, aucune dépendance externe.
Usage : VIE_API_KEY=... python vie_radar.py   ->   docs/index.html, docs/offres.json, docs/offres.csv
"""
import csv, json, os, re, sys, time, unicodedata
from datetime import date
from functools import lru_cache, partial
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("Python 3.11 ou plus récent requis : https://www.python.org/downloads/")

ROOT = Path(__file__).resolve().parent  # le script est à la racine du dépôt
DOCS, DATA = ROOT / "docs", ROOT / "data"
API_URL = os.environ.get("VIE_API_URL", "https://civiweb-api-prd.azurewebsites.net/api/Offers/search")
WD_BASE = os.environ.get("VIE_WD_BASE", "https://{tenant}.{wd}.myworkdayjobs.com")
SITE = "https://mon-vie-via.businessfrance.fr"
UA = "Mozilla/5.0 (compatible; VIE-Radar/2.0)"
MAX_BYTES = 20_000_000  # une réponse plus grosse est tronquée
# « VIE » en majuscules seulement : le mot français « vie » ne doit pas passer
TITLE_VIE = re.compile(r"\bV\.?I\.?E\b|(?i:volontariat international|volunteer for international)")
EN_FR = dict(p.split("=") for p in (
    "united states=Etats-Unis|united states of america=Etats-Unis|usa=Etats-Unis|germany=Allemagne|"
    "united kingdom=Royaume-Uni|spain=Espagne|italy=Italie|belgium=Belgique|switzerland=Suisse|"
    "netherlands=Pays-Bas|japan=Japon|china=Chine|india=Inde|singapore=Singapour|brazil=Bresil|"
    "mexico=Mexique|australia=Australie|south korea=Coree du Sud|united arab emirates=Emirats Arabes Unis|"
    "poland=Pologne|sweden=Suede|norway=Norvege|denmark=Danemark|ireland=Irlande|austria=Autriche|"
    "czech republic=Tchequie|romania=Roumanie|morocco=Maroc|south africa=Afrique du Sud|thailand=Thailande|"
    "vietnam=Vietnam|malaysia=Malaisie|indonesia=Indonesie|turkey=Turquie|saudi arabia=Arabie saoudite|"
    "hungary=Hongrie|argentina=Argentine").split("|"))


# ───────────── outils ─────────────
def http(url, data=None, headers=None, retries=3):
    """GET (ou POST JSON si `data`) avec nouveaux essais sur les erreurs temporaires. Renvoie le texte."""
    body = json.dumps(data).encode() if data is not None else None
    h = {"User-Agent": UA, **({"Content-Type": "application/json"} if body else {}), **(headers or {})}
    for attempt in range(retries + 1):
        try:
            with urlopen(Request(url, body, h), timeout=30) as r:
                return r.read(MAX_BYTES).decode("utf-8", "replace")
        except HTTPError as e:  # le message ne reprend ni l'URL complète ni les en-têtes (clé API)
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f"HTTP {e.code} ({urlsplit(url).netloc})") from None
        except (URLError, TimeoutError) as e:
            if attempt == retries:
                raise RuntimeError(f"réseau : {getattr(e, 'reason', e)} ({urlsplit(url).netloc})") from None
        time.sleep(2 ** attempt)


def jget(*args, **kwargs):
    try:
        return json.loads(http(*args, **kwargs))
    except json.JSONDecodeError:
        raise RuntimeError("réponse non JSON") from None


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ")


def clean(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(h or ""))).strip()


def to_int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def months_in(t):
    m = re.search(r"\b(6|9|12|18|24)\s*(?:months|mois|monate)\b", t, re.I)
    return int(m.group(1)) if m else 0


def day(v):
    """Date AAAA-MM-JJ valide, sinon chaîne vide."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(v or ""))
    return m.group(0) if m else ""


def safe_url(u):
    return u if urlsplit(u).scheme in ("http", "https") else ""  # pas de javascript:, data:…


@lru_cache(maxsize=None)
def pattern(term):
    """Le terme doit apparaître en mot entier (pluriel simple toléré) : « sale » ≠ « disposable »."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm(term)) + r"(?:s|x)?(?![a-z0-9])")


def found(terms, text):
    return [t for t in terms if pattern(t).search(text)]


def offer(oid, source, title, url, company, city="", country="", typ="VIE",
          months=0, pay=0, posted="", deadline="", text="", start=""):
    return {"id": oid, "source": source, "title": title.strip(), "company": company, "city": city,
            "country": EN_FR.get(norm(country), country), "type": typ, "months": months, "pay": pay,
            "posted": day(posted), "deadline": day(deadline), "start": day(start),
            "url": safe_url(url), "text": text}


# ───────────── profil ─────────────
FIELDS = {"metiers": list, "competences": list, "entreprises_visees": list, "pays_preferes": list,
          "pays_exclus": list, "exclure": list, "duree_min_mois": int, "indemnite_min": int, "inclure_via": bool}


def load_profile(path=ROOT / "profile.toml"):
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"{path.name} introuvable.")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"{path.name} : erreur de syntaxe ({e}). Vérifie les guillemets et les virgules.")
    if unknown := sorted(set(raw) - set(FIELDS)):
        sys.exit(f"{path.name} : clé inconnue {unknown} (faute de frappe ?)")
    profile = {}
    for key, kind in FIELDS.items():
        v = raw.get(key, kind())
        if type(v) is not kind or (kind is list and not all(isinstance(x, str) for x in v)):
            sys.exit(f"{path.name} : « {key} » doit être {'une liste de mots entre guillemets' if kind is list else {int: 'un nombre entier (sans guillemets)', bool: 'true ou false (sans guillemets)'}[kind]}.")
        profile[key] = v
    return profile


# ───────────── sources ─────────────
def from_bf(r):
    g = lambda *ks: next((r[k] for k in ks if r.get(k) not in (None, "", [])), "")
    return offer(f"bf-{r['id']}", "Business France", str(g("missionTitle", "title")), f"{SITE}/offres/{r['id']}",
                 str(g("organizationName", "companyName")), str(g("cityName")), str(g("countryName")),
                 str(g("missionType") or "VIE"), to_int(g("missionDuration")), to_int(g("indemnite")),
                 g("startBroadcastDate", "creationDate"), g("endBroadcastDate"),
                 " ".join(v for v in r.values() if isinstance(v, str)),
                 next((v for k, v in r.items() if "startdate" in k.lower() and v), ""))  # date « à pourvoir »


def business_france():
    key = os.environ.get("VIE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("secret VIE_API_KEY absent (voir README)")
    headers = {"X-API-KEY": key, "Origin": SITE, "Referer": SITE + "/"}
    body = {"limit": 100, "skip": 0, "query": "", "activitySectorId": [], "missionsTypesIds": [],
            "countriesIds": [], "studiesLevelId": [], "companiesSizes": [], "specializationsIds": [],
            "entreprisesIds": [], "missionStartDate": None, "gerographicZones": [],
            "countriesFilterOperator": "OR", "specializationsFilterOperator": "OR"}
    out, seen, dates = [], set(), set()
    for page in range(40):  # 100 offres max par appel : on pagine
        d = jget(API_URL, {**body, "skip": page * 100}, headers)
        rows = d.get("result") if isinstance(d, dict) else d
        if not isinstance(rows, list):
            raise RuntimeError("format de réponse inattendu")
        fresh = [r for r in rows if isinstance(r, dict) and r.get("id") is not None and r["id"] not in seen]
        for r in fresh:
            seen.add(r["id"])
            out.append(from_bf(r))
            dates.update(k for k in r if "date" in k.lower())
        if not fresh or len(rows) < 100:
            break
        time.sleep(0.3)
    print(f"  champs de date de l'API : {sorted(dates)}")
    return out


def workday(company, cfg):
    """API commune à tous les sites Workday (POST .../wday/cxs/<tenant>/<site>/jobs)."""
    tenant, wd, site = cfg
    base = WD_BASE.format(tenant=tenant, wd=wd)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    rows, total, offset = [], None, 0
    while True:  # 20 résultats max par appel ; le total n'est donné qu'à la 1re page
        d = jget(api + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "VIE"})
        page = d.get("jobPostings", [])
        total = d.get("total", 0) if total is None else total
        rows += page
        offset += 20
        if not page or offset >= min(total, 600):
            break
        time.sleep(0.3)
    out = []
    for j in rows:
        if not TITLE_VIE.search(j.get("title", "")):
            continue
        try:
            info = jget(urljoin(api + "/", j["externalPath"].lstrip("/"))).get("jobPostingInfo", {})
        except RuntimeError:
            info = {}
        loc = info.get("location") or j.get("locationsText", "")
        text = clean(info.get("jobDescription"))
        out.append(offer(f"wd-{company}-{info.get('jobReqId') or j['externalPath']}", f"{company} (site carrière)",
                         j["title"], info.get("externalUrl") or f"{base}/{site}{j['externalPath']}", company,
                         loc.split(",")[0].strip(),
                         (info.get("country") or {}).get("descriptor") or loc.split(",")[-1].strip(),
                         months=months_in(text), text=text))
    return out


def avature(company, base):
    """Sites Avature (pages HTML) : lecture au mieux, plus fragile que Workday."""
    out, seen = [], set()
    for off in range(0, 300, 50):
        html = http(f"{base}/SearchJobs/VIE?jobRecordsPerPage=50&jobOffset={off}")
        links = [(urljoin(base + "/", unescape(u)), clean(t)) for u, t in
                 re.findall(r'href="([^"]*/careers/JobDetail/[^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I)]
        links = [(u, t) for u, t in links if t and u not in seen]
        if not links:
            break
        for u, t in links:
            seen.add(u)
            if not TITLE_VIE.search(t):
                continue
            text = clean(http(u))
            m = re.search(r"Country\s+(.+?)\s+City\s+(.+?)\s+(?:Workplace|Employer|Domain)", text)
            out.append(offer(f"av-{company}-{u.rstrip('/').split('/')[-1]}", f"{company} (site carrière)", t, u,
                             company, m.group(2) if m else "", m.group(1) if m else "",
                             months=months_in(text), text=text))
        time.sleep(0.3)
    return out


CAREER_SITES = [  # (groupe, connecteur, réglage). Thales confirmé ; les autres à vérifier au 1er lancement
    ("Thales", workday, ("thales", "wd3", "Careers")),
    ("Sanofi", workday, ("sanofi", "wd3", "SanofiCareers")),
    ("Airbus", workday, ("ag", "wd3", "Airbus")),
    ("Schneider Electric", workday, ("schneider", "wd3", "careers")),
    ("Michelin", workday, ("michelin", "wd3", "Michelin")),
    ("TotalEnergies", avature, "https://jobs.totalenergies.com/en_US/careers"),
]
NON_COUVERTS = ["Arkema", "Capgemini", "LVMH", "L'Oréal", "Richemont", "Air Liquide", "Safran"]


# ───────────── score ─────────────
def score(o, P):
    text, title, country = norm(o["title"] + " " + o["text"]), norm(o["title"]), norm(o["country"])
    if found(P["exclure"], title):
        return 0, ["✗ mot exclu dans le titre"]
    if o["type"].upper() == "VIA" and not P["inclure_via"]:
        return 0, ["✗ VIA (administration)"]
    if country in {norm(c) for c in P["pays_exclus"]}:
        return 0, [f"✗ pays exclu : {o['country']}"]
    s, why = 0, []
    if hits := found(P["metiers"], text):
        s += min(40, 25 + 5 * (len(hits) - 1))
        why.append("✓ métier : " + ", ".join(hits))
    else:
        why.append("✗ aucun métier ciblé repéré")
    if skills := found(P["competences"], text):
        s += min(15, 5 * len(skills))
        why.append("✓ compétences : " + ", ".join(skills))
    else:
        why.append("• compétences non mentionnées")
    if country in {norm(c) for c in P["pays_preferes"]}:
        s += 15
        why.append(f"✓ pays souhaité : {o['country']}")
    if found(P["entreprises_visees"], norm(o["company"])):
        s += 10
        why.append(f"✓ entreprise visée : {o['company']}")
    for label, value, minimum, unit in (("durée", o["months"], P["duree_min_mois"], "mois"),
                                         ("indemnité", o["pay"], P["indemnite_min"], "€/mois")):
        if value:
            ok = value >= minimum
            s += 10 if ok else -10
            why.append(f"{'✓' if ok else '✗'} {label} {value} {unit} (min {minimum})")
        else:
            why.append(f"• {label} non précisée")
    return max(0, min(100, s)), why


# ───────────── sorties ─────────────
def csv_safe(v):
    """Empêche Excel d'exécuter un titre commençant par = + - @ comme une formule."""
    return "'" + v if isinstance(v, str) and v[:1] and v[0] in "=+-@\t\r" else v


def render_html(offers, today):
    data = json.dumps(offers, ensure_ascii=False).replace("<", "\\u003c")  # ferme la porte à </script>
    page = (ROOT / "template.html").read_text(encoding="utf-8")
    return page.replace("__DATE__", today.strftime("%d/%m/%Y")).replace("__DATA__", data)


def write_outputs(offers, today):
    DOCS.mkdir(exist_ok=True)
    (DOCS / "offres.json").write_text(json.dumps(offers, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = [("score", "score"), ("title", "titre"), ("company", "entreprise"), ("city", "ville"), ("country", "pays"),
            ("type", "type"), ("months", "mois"), ("pay", "indemnité"), ("deadline", "date limite"), ("start", "à pourvoir"),
            ("source", "source"), ("url", "lien")]
    with open(DOCS / "offres.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([name for _, name in cols])
        for o in offers:
            w.writerow([csv_safe(o[k]) for k, _ in cols])
    (DOCS / "index.html").write_text(render_html(offers, today), encoding="utf-8")


def write_summary(report):
    """Tableau lisible en haut de l'exécution GitHub (onglet Actions)."""
    if not (path := os.environ.get("GITHUB_STEP_SUMMARY")):
        return
    rows = [f"| {n} | {c} | {'✓' if not e else '✗ ' + e.replace('|', '/').replace('<', '')} |" for n, c, e in report]
    text = "### VIE Radar\n\n| Source | Offres | Statut |\n|---|---|---|\n" + "\n".join(rows)
    text += "\n\nSans connecteur : " + ", ".join(NON_COUVERTS) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def key(o):
    words = set(re.findall(r"[a-z0-9]+", norm(o["title"]))) - {"vie", "v", "i", "e", "h", "f", "m", "d", "all", "gender"}
    return " ".join(sorted(words)) + "|" + norm(o["city"])


def deduplicate(offers):
    """Une offre déjà sur Business France n'est pas répétée depuis un site carrière."""
    bf = {key(o) for o in offers if o["source"] == "Business France"}
    return [o for o in offers if o["source"] == "Business France" or key(o) not in bf]


def main():
    profile = load_profile()
    sources = [("Business France", business_france)] + [(c, partial(f, c, cfg)) for c, f, cfg in CAREER_SITES]
    offers, report = [], []
    for name, run in sources:
        try:
            got = run()
            offers += got
            report.append((name, len(got), ""))
            print(f"✓ {name} : {len(got)} offres")
        except Exception as e:  # un site carrière en panne ne bloque pas les autres
            report.append((name, 0, str(e)))
            print(f"✗ {name} : {e}", file=sys.stderr)
    print("• sans connecteur : " + ", ".join(NON_COUVERTS))
    write_summary(report)
    if report[0][2]:  # Business France est la source principale : sans elle, on ne publie rien
        hint = " (clé refusée : mets à jour le secret VIE_API_KEY)" if "401" in report[0][2] else ""
        sys.exit(f"Business France indisponible{hint} : publication annulée, l'ancienne page reste en ligne.")

    offers = deduplicate([o for o in offers if o["title"]])
    known = sum(bool(o["start"]) for o in offers if o["source"] == "Business France")
    print(f"• date « à pourvoir » connue pour {known} offres Business France")
    DATA.mkdir(exist_ok=True)
    seen_file = DATA / "vie_seen.json"
    try:
        seen = set(json.loads(seen_file.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        seen = set()
    today = date.today()
    for o in offers:
        o["score"], o["why"] = score(o, profile)
        o["targeted"] = bool(found(profile["entreprises_visees"], norm(o["company"])))
        o["new"] = bool(seen) and o["id"] not in seen  # 1er lancement : rien n'est marqué « nouvelle »
        try:
            o["days_left"] = (date.fromisoformat(o["deadline"]) - today).days
        except ValueError:
            o["days_left"] = None
        o.pop("text")
    offers.sort(key=lambda o: (-o["score"], o["deadline"] or "9999-12-31", o["title"].lower()))
    seen_file.write_text(json.dumps(sorted(o["id"] for o in offers)), encoding="utf-8")
    write_outputs(offers, today)
    print(f"✓ {len(offers)} offres, dont {sum(o['score'] >= 70 for o in offers)} à 70+ → {DOCS / 'index.html'}")


if __name__ == "__main__":
    main()
