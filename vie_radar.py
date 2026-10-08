#!/usr/bin/env python3
"""VIE Radar - collecte, score et publie les offres VIE/VIA.

Aucune dépendance externe : Python standard uniquement.
GitHub Actions peut donc exécuter ce script sans pip install.

Fichiers générés :
- docs/index.html  : interface web
- docs/offres.json : données exploitables comme API statique
- docs/offres.csv  : export CSV
- data/vie_seen.json: historique des offres déjà vues
"""

import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
DATA_DIR = ROOT / "data"
SEEN_FILE = DATA_DIR / "vie_seen.json"

DOCS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

PROFILE = {
    "metiers": [
        "sales",
        "commercial",
        "business development",
        "business developer",
        "sales data",
        "sales analyst",
        "data analyst",
        "marketing",
        "product manager",
        "product management",
        "account manager",
        "key account",
        "customer success",
        "supply chain",
    ],
    "competences": [
        "salesforce",
        "power bi",
        "sap",
        "excel",
        "data analysis",
        "business intelligence",
        "crm",
        "portfolio management",
        "sale",
    ],
    "entreprises_visees": [
        "Arkema",
        "Capgemini",
        "Thales",
        "LVMH",
        "L'Oréal",
        "Sanofi",
        "Airbus",
        "Schneider Electric",
        "Michelin",
        "Richemont",
        "Air Liquide",
        "TotalEnergies",
        "Safran",
        "Louis Vuitton",
        "Dior",
        "Sephora",
        "Moët",
        "Hennessy",
        "Guerlain",
        "Fendi",
        "Celine",
        "Bulgari",
        "Cartier",
        "Van Cleef",
        "Piaget",
        "Jaeger",
        "Vacheron",
        "Montblanc",
        "Chloé",
    ],
    "pays_preferes": [],
    "pays_exclus": [],
    "exclure": ["stage", "alternance", "internship"],
    "duree_min_mois": 6,
    "indemnite_min": 1800,
    "inclure_via": False,
}

API_URL = os.environ.get(
    "VIE_API_URL",
    "https://civiweb-api-prd.azurewebsites.net/api/Offers/search",
)
# La valeur peut être remplacée proprement par le secret GitHub VIE_API_KEY.
# Le fallback reprend la valeur présente dans le script d'origine.
API_KEY = os.environ.get(
    "VIE_API_KEY",
    "l+KwpoLPiXlsjxNT/NQ2iOFz8+iuygxAODs9FeAEWYM=",
)
SITE = "https://mon-vie-via.businessfrance.fr"

UA = "Mozilla/5.0 (compatible; VIE-Radar/1.0; +https://github.com/)"
TITLE_VIE = re.compile(
    r"\bV\.?I\.?E\b|volontariat international|volunteer for international",
    re.I,
)
WD_BASE = os.environ.get(
    "VIE_WD_BASE",
    "https://{tenant}.{wd}.myworkdayjobs.com",
)

EN_FR = {
    "united states": "Etats-Unis",
    "united states of america": "Etats-Unis",
    "usa": "Etats-Unis",
    "germany": "Allemagne",
    "united kingdom": "Royaume-Uni",
    "spain": "Espagne",
    "italy": "Italie",
    "belgium": "Belgique",
    "switzerland": "Suisse",
    "netherlands": "Pays-Bas",
    "japan": "Japon",
    "china": "Chine",
    "india": "Inde",
    "singapore": "Singapour",
    "brazil": "Bresil",
    "mexico": "Mexique",
    "australia": "Australie",
    "south korea": "Coree du Sud",
    "united arab emirates": "Emirats Arabes Unis",
    "poland": "Pologne",
    "sweden": "Suede",
    "norway": "Norvege",
    "denmark": "Danemark",
    "ireland": "Irlande",
    "austria": "Autriche",
    "czech republic": "Tchequie",
    "romania": "Roumanie",
    "morocco": "Maroc",
    "south africa": "Afrique du Sud",
    "thailand": "Thailande",
    "vietnam": "Vietnam",
    "malaysia": "Malaisie",
    "indonesia": "Indonesie",
    "turkey": "Turquie",
    "saudi arabia": "Arabie saoudite",
    "hungary": "Hongrie",
    "Argentina": "Argentine",
    "canada": "Canada",
}


def http_request(url, method="GET", data=None, headers=None, timeout=30):
    """Requête HTTP avec uniquement la bibliothèque standard Python."""
    req_headers = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        req_headers.update(headers)

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    request = Request(url, data=body, headers=req_headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} sur {url}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Erreur réseau sur {url}: {exc.reason}") from exc


def http_json(url, method="GET", data=None, headers=None, timeout=30):
    raw = http_request(url, method, data, headers, timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse JSON invalide depuis {url}") from exc


def to_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def first_value(obj, *keys):
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", []):
            return value
    return ""


def to_offer(obj):
    offer_id = first_value(obj, "id")
    return {
        "id": f"bf-{offer_id}",
        "source": "Business France",
        "title": str(first_value(obj, "missionTitle", "title")),
        "company": str(first_value(obj, "organizationName", "companyName")),
        "city": str(first_value(obj, "cityName")),
        "country": str(first_value(obj, "countryName")),
        "type": str(first_value(obj, "missionType") or "VIE"),
        "months": to_int(first_value(obj, "missionDuration")),
        "pay": to_int(first_value(obj, "indemnite")),
        "posted": str(
            first_value(obj, "startBroadcastDate", "creationDate")
        )[:10],
        "deadline": str(first_value(obj, "endBroadcastDate"))[:10],
        "url": f"{SITE}/offres/{offer_id}",
        "text": " ".join(
            str(value) for value in obj.values() if isinstance(value, str)
        ),
    }


def source_business_france():
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": API_KEY,
        "Origin": SITE,
        "Referer": SITE + "/",
    }

    body = {
        "limit": 100,
        "skip": 0,
        "query": "",
        "activitySectorId": [],
        "missionsTypesIds": [],
        "countriesIds": [],
        "studiesLevelId": [],
        "companiesSizes": [],
        "specializationsIds": [],
        "entreprisesIds": [],
        "missionStartDate": None,
        "gerographicZones": [],
        "countriesFilterOperator": "OR",
        "specializationsFilterOperator": "OR",
    }

    seen = set()
    offers = []

    for page in range(40):
        data = http_json(
            API_URL,
            method="POST",
            data={**body, "skip": page * 100},
            headers=headers,
            timeout=30,
        )

        rows = data.get("result", []) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise RuntimeError("Format inattendu de la réponse Business France.")

        fresh = [item for item in rows if item.get("id") not in seen]
        if not fresh:
            break

        for item in fresh:
            if item.get("id") is None:
                continue
            seen.add(item["id"])
            offers.append(to_offer(item))

        if len(rows) < 100:
            break

        time.sleep(0.3)

    return offers


def clean(html):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"<[^>]+>", " ", unescape(html or "")),
    ).strip()


def months_in(text):
    match = re.search(
        r"\b(6|9|12|18|24)\s*(?:months|mois|monate)\b",
        text,
        re.I,
    )
    return int(match.group(1)) if match else 0


def mk(company, uid, title, url, city="", country="", text=""):
    return {
        "id": f"cs-{company}-{uid}",
        "source": company + " (site carrière)",
        "title": title.strip(),
        "company": company,
        "city": city,
        "country": EN_FR.get(norm(country), country),
        "type": "VIE",
        "months": months_in(text),
        "pay": 0,
        "posted": "",
        "deadline": "",
        "url": url,
        "text": text,
    }


def workday(company, cfg):
    tenant, wd, site = cfg
    base = WD_BASE.format(tenant=tenant, wd=wd)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    rows = []
    offset = 0
    total = None

    while True:
        data = http_json(
            api + "/jobs",
            method="POST",
            data={
                "appliedFacets": {},
                "limit": 20,
                "offset": offset,
                "searchText": "VIE",
            },
            headers=headers,
            timeout=30,
        )

        page = data.get("jobPostings", [])
        total = data.get("total", 0) if total is None else total
        rows.extend(page)
        offset += 20

        if not page or offset >= min(total, 600):
            break

        time.sleep(0.3)

    offers = []

    for job in rows:
        if not TITLE_VIE.search(job.get("title", "")):
            continue

        try:
            info = http_json(
                urljoin(api + "/", job["externalPath"].lstrip("/")),
                headers=headers,
                timeout=30,
            ).get("jobPostingInfo", {})
        except Exception as exc:
            print(
                f"  ! détails Workday indisponibles pour {job.get('title', '')}: {exc}",
                file=sys.stderr,
            )
            info = {}

        location = info.get("location") or job.get("locationsText", "")
        country = (
            (info.get("country") or {}).get("descriptor")
            or location.split(",")[-1].strip()
        )

        offers.append(
            mk(
                company,
                info.get("jobReqId") or job["externalPath"],
                job["title"],
                info.get("externalUrl")
                or f"{base}/{site}{job['externalPath']}",
                location.split(",")[0].strip(),
                country,
                clean(info.get("jobDescription")),
            )
        )

    return offers


def avature(company, base):
    """Connecteur Avature. Plus fragile que Workday car basé sur le HTML."""
    offers = []
    seen = set()

    for offset in range(0, 300, 50):
        url = f"{base}/SearchJobs/VIE"
        query = f"?jobRecordsPerPage=50&jobOffset={offset}"

        html = http_request(url + query, timeout=30)

        links = re.findall(
            r'href="([^"]*/careers/JobDetail/[^"]+)"[^>]*>(.*?)</a>',
            html,
            re.S | re.I,
        )
        links = [
            (urljoin(base, href), clean(title))
            for href, title in links
            if title
        ]
        links = [(url, title) for url, title in links if url not in seen]

        if not links:
            break

        for url, title in links:
            seen.add(url)

            if not TITLE_VIE.search(title):
                continue

            detail = clean(http_request(url, timeout=30))
            match = re.search(
                r"Country\s+(.+?)\s+City\s+(.+?)\s+(?:Workplace|Employer|Domain)",
                detail,
                re.I,
            )

            offers.append(
                mk(
                    company,
                    url.rstrip("/").split("/")[-1],
                    title,
                    url,
                    match.group(2) if match else "",
                    match.group(1) if match else "",
                    detail,
                )
            )

        time.sleep(0.3)

    return offers


CAREER_SITES = [
    ("Thales", workday, ("thales", "wd3", "Careers"), "à vérifier régulièrement"),
    ("Sanofi", workday, ("sanofi", "wd3", "SanofiCareers"), "à vérifier régulièrement"),
    ("Airbus", workday, ("ag", "wd3", "Airbus"), "à vérifier régulièrement"),
    ("Schneider Electric", workday, ("schneider", "wd3", "careers"), "à vérifier régulièrement"),
    ("Michelin", workday, ("michelin", "wd3", "Michelin"), "à vérifier régulièrement"),
    ("TotalEnergies", avature, "https://jobs.totalenergies.com/en_US/careers", "connecteur HTML"),
]

NON_COUVERTS = [
    "Arkema",
    "Capgemini",
    "LVMH",
    "L'Oréal",
    "Richemont",
    "Air Liquide",
    "Safran",
]


def source_career_sites():
    offers = []

    for company, connector, config, status in CAREER_SITES:
        try:
            found = connector(company, config)
            print(f"  ✓ {company}: {len(found)} offres VIE ({status})")
            offers.extend(found)
        except Exception as exc:
            print(f"  ✗ {company}: {exc}", file=sys.stderr)

    print("  • sans connecteur: " + ", ".join(NON_COUVERTS))
    return offers


SOURCES = [source_business_france, source_career_sites]


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(
        char for char in value if not unicodedata.combining(char)
    ).lower().replace("-", " ")


def score(offer, profile=PROFILE):
    text = norm(offer["title"] + " " + offer["text"])
    title = norm(offer["title"])

    if any(norm(word) in title for word in profile["exclure"]):
        return 0, ["✗ mot exclu dans le titre"]

    if offer["type"].upper() == "VIA" and not profile["inclure_via"]:
        return 0, ["✗ VIA (administration)"]

    if norm(offer["country"]) in [norm(c) for c in profile["pays_exclus"]]:
        return 0, [f"✗ pays exclu : {offer['country']}"]

    total = 0
    why = []

    jobs = [job for job in profile["metiers"] if norm(job) in text]
    if jobs:
        total += min(40, 25 + 5 * (len(jobs) - 1))
        why.append("✓ métier : " + ", ".join(jobs))
    else:
        why.append("✗ aucun métier ciblé repéré")

    skills = [
        skill for skill in profile["competences"] if norm(skill) in text
    ]
    if skills:
        total += min(15, 5 * len(skills))
        why.append("✓ compétences : " + ", ".join(skills))
    else:
        why.append("• compétences non mentionnées")

    if norm(offer["country"]) in [
        norm(country) for country in profile["pays_preferes"]
    ]:
        total += 15
        why.append(f"✓ pays souhaité : {offer['country']}")

    if any(
        norm(company) in norm(offer["company"])
        for company in profile["entreprises_visees"]
    ):
        total += 10
        why.append(f"✓ entreprise visée : {offer['company']}")

    if offer["months"]:
        ok = offer["months"] >= profile["duree_min_mois"]
        total += 10 if ok else -10
        why.append(
            f"{'✓' if ok else '✗'} durée {offer['months']} mois "
            f"(min {profile['duree_min_mois']})"
        )
    else:
        why.append("• durée non précisée")

    if offer["pay"]:
        ok = offer["pay"] >= profile["indemnite_min"]
        total += 10 if ok else -10
        why.append(
            f"{'✓' if ok else '✗'} indemnité {offer['pay']} €/mois "
            f"(min {profile['indemnite_min']})"
        )
    else:
        why.append("• indemnité non précisée")

    return max(0, min(100, total)), why


HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIE Radar</title>
<style>
:root{--bg:#eef1f4;--card:#fff;--ink:#14212b;--mute:#5b6b78;--line:#d8dee4;--ok:#0b7a4b;--mid:#b26a00;--low:#8a949c}
@media(prefers-color-scheme:dark){:root{--bg:#10171d;--card:#18222a;--ink:#e8eef2;--mute:#9aabb8;--line:#2a3a46}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);padding:12px;border-bottom:1px solid var(--line);z-index:2}
h1{font-size:1.1rem;margin:0 0 8px}
.row{display:flex;gap:6px;flex-wrap:wrap}
input,select{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);min-width:0}
#q{flex:1 1 100%}
#cnt{color:var(--mute);font-size:.85rem;margin-top:6px}
main{padding:12px;display:grid;gap:10px;max-width:760px;margin:auto}
article{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;grid-template-columns:52px 1fr;gap:10px}
.sc{font-size:1.4rem;font-weight:700;text-align:center;align-self:start}
.hi{color:var(--ok)}.md{color:var(--mid)}.lo{color:var(--low)}
article h2{font-size:1rem;margin:0}
a{color:inherit}
.sub{color:var(--mute);font-size:.9rem}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.chips span{border:1px solid var(--line);border-radius:99px;padding:1px 9px;font-size:.8rem}
.chips .new{border-color:var(--ok);color:var(--ok)}
.chips .soon{border-color:#c0392b;color:#c0392b}
details{font-size:.88rem;color:var(--mute)}
li{margin:2px 0}
ul{padding-left:18px;margin:6px 0 0}
</style>
</head>
<body>
<header>
<h1>VIE Radar <span class="sub">mis à jour le __DATE__</span></h1>
<div class="row">
<input id="q" type="search" placeholder="Poste, entreprise, ville…">
<select id="c"></select>
<select id="m">
<option value="0">Tous scores</option>
<option value="40">Score 40+</option>
<option value="60">Score 60+</option>
<option value="80">Score 80+</option>
</select>
<select id="s">
<option value="score">Meilleur score</option>
<option value="deadline">Date limite</option>
</select>
<label><input id="n" type="checkbox"> nouvelles</label>
</div>
<div id="cnt"></div>
</header>
<main id="list"></main>
<script>
const D=__DATA__, $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('c').innerHTML='<option value="">Tous pays</option>'+
[...new Set(D.map(o=>o.country))].filter(Boolean).sort()
.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');

function render(){
 const q=$('q').value.toLowerCase(), c=$('c').value,
       m=+$('m').value, n=$('n').checked;
 const L=D.filter(o=>
   (!q||(o.title+' '+o.company+' '+o.city).toLowerCase().includes(q)) &&
   (!c||o.country===c) &&
   o.score>=m &&
   (!n||o.new)
 );
 L.sort($('s').value==='score'
   ? (a,b)=>b.score-a.score
   : (a,b)=>(a.deadline||'9999').localeCompare(b.deadline||'9999'));
 $('cnt').textContent=L.length+' offres sur '+D.length+
   (L.length>200?' (200 affichées)':'');
 $('list').innerHTML=L.slice(0,200).map(o=>`
 <article>
  <div class="sc ${o.score>=70?'hi':o.score>=40?'md':'lo'}">${o.score}</div>
  <div>
   <h2><a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.title)}</a></h2>
   <div class="sub">${esc(o.company)} – ${esc([o.city,o.country].filter(Boolean).join(', '))}</div>
   <div class="chips">
    ${o.new?'<span class="new">nouvelle</span>':''}
    <span>${esc(o.type)}</span>
    ${o.months?`<span>${o.months} mois</span>`:''}
    ${o.pay?`<span>${o.pay} €/mois</span>`:''}
    ${o.deadline?`<span class="${o.days_left!=null&&o.days_left<=7?'soon':''}">${
      o.days_left!=null?(o.days_left>=0?'J-'+o.days_left:'expirée'):esc(o.deadline)
    }</span>`:''}
    <span>${esc(o.source)}</span>
   </div>
   <details>
    <summary>Pourquoi ce score</summary>
    <ul>${o.why.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>
   </details>
  </div>
 </article>`).join('');
}
['q','c','m','s','n'].forEach(id=>$(id).addEventListener('input',render));
render();
</script>
</body>
</html>
"""


def read_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data)
    except (json.JSONDecodeError, TypeError):
        print("⚠ historique invalide : il sera recréé.", file=sys.stderr)
        return set()


def offer_key(offer):
    words = set(re.findall(r"[a-z0-9]+", norm(offer["title"])))
    words -= {
        "vie", "v", "i", "e", "h", "f", "m", "d",
        "all", "gender",
    }
    return " ".join(sorted(words)) + "|" + norm(offer["city"])


def deduplicate(offers):
    """Supprime les doublons carrière quand Business France possède la même offre."""
    business_france = {
        offer_key(offer)
        for offer in offers
        if offer["source"] == "Business France"
    }
    return [
        offer
        for offer in offers
        if offer["source"] == "Business France"
        or offer_key(offer) not in business_france
    ]


def write_outputs(offers, today):
    json_data = json.dumps(offers, ensure_ascii=False, indent=1)

    (DOCS_DIR / "offres.json").write_text(
        json_data,
        encoding="utf-8",
    )

    with (DOCS_DIR / "offres.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow([
            "score", "titre", "entreprise", "ville", "pays",
            "type", "mois", "indemnité", "date limite",
            "source", "lien",
        ])
        for offer in offers:
            writer.writerow([
                offer["score"],
                offer["title"],
                offer["company"],
                offer["city"],
                offer["country"],
                offer["type"],
                offer["months"],
                offer["pay"],
                offer["deadline"],
                offer["source"],
                offer["url"],
            ])

    data = json.dumps(offers, ensure_ascii=False).replace("</", "<\\/")
    html = (
        HTML
        .replace("__DATA__", data)
        .replace("__DATE__", today.strftime("%d/%m/%Y"))
    )
    (DOCS_DIR / "index.html").write_text(html, encoding="utf-8")


def main():
    offers = []

    for source in SOURCES:
        try:
            found = source()
            print(f"✓ {source.__name__}: {len(found)} offres")
            offers.extend(found)
        except Exception as exc:
            print(
                f"✗ {source.__name__}: {exc}",
                file=sys.stderr,
            )

    if not offers:
        raise SystemExit(
            "Aucune offre récupérée. Vérifie les sources/API dans les logs GitHub."
        )

    offers = deduplicate(offers)

    seen = read_seen()
    today = date.today()

    for offer in offers:
        offer["score"], offer["why"] = score(offer)
        offer["new"] = bool(seen) and offer["id"] not in seen

        try:
            offer["days_left"] = (
                date.fromisoformat(offer["deadline"]) - today
            ).days
        except (TypeError, ValueError):
            offer["days_left"] = None

        offer.pop("text", None)

    offers.sort(
        key=lambda offer: (
            -offer["score"],
            offer["deadline"] or "9999-12-31",
            offer["title"].lower(),
        )
    )

    SEEN_FILE.write_text(
        json.dumps(sorted(offer["id"] for offer in offers), indent=1),
        encoding="utf-8",
    )

    write_outputs(offers, today)

    top = sum(offer["score"] >= 70 for offer in offers)
    print(f"✓ {len(offers)} offres, dont {top} à 70+")
    print(f"✓ Site : {DOCS_DIR / 'index.html'}")
    print(f"✓ API statique : {DOCS_DIR / 'offres.json'}")


if __name__ == "__main__":
    main()
