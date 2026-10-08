#!/usr/bin/env python3
"""VIE Radar : rassemble les offres VIE, les note selon ton profil, génère une page HTML.

Usage :  pip install requests  &&  python vie_radar.py
Sorties : vie_offres.html (à ouvrir), offres.csv, offres.json
"""
import csv, json, os, re, sys, time, unicodedata
from datetime import date
from html import unescape
from pathlib import Path

import requests

# ═════════════ 1. TON PROFIL : à modifier (les valeurs ci-dessous sont des EXEMPLES) ═════════════
PROFILE = {
    "metiers": ["data", "analyst", "finance", "supply chain", "business developer"],  # mots du poste visé
    "competences": ["python", "sql", "excel", "power bi", "sap"],                     # compétences de ton CV
    "entreprises_visees": [
        "Arkema", "Capgemini", "Thales", "LVMH", "L'Oréal", "Sanofi", "Airbus", "Schneider", "Michelin",
        "Richemont", "Air Liquide", "TotalEnergies", "Total Energies", "Safran",
        "Louis Vuitton", "Dior", "Sephora", "Moët", "Hennessy", "Guerlain", "Fendi", "Celine", "Bulgari",  # maisons LVMH
        "Cartier", "Van Cleef", "Piaget", "Jaeger", "Vacheron", "Montblanc", "Chloé",                     # maisons Richemont
    ],
    "pays_preferes": ["Etats-Unis", "Canada", "Singapour", "Japon"],
    "pays_exclus": [],
    "exclure": ["stage", "alternance", "internship"],   # mots interdits dans le titre
    "duree_min_mois": 12,
    "indemnite_min": 2200,                               # € / mois
    "inclure_via": False,                                # VIA = volontariat en administration
}

# ═════════════ 2. SOURCES ═════════════
API_URL = os.environ.get("VIE_API_URL", "https://civiweb-api-prd.azurewebsites.net/api/Offers/search")
# Clé statique que le site Business France envoie à tous les navigateurs.
# Si l'API répond 401 un jour : F12 > Network > en-tête X-API-KEY, puis `export VIE_API_KEY=...`
API_KEY = os.environ.get("VIE_API_KEY", "l+KwpoLPiXlsjxNT/NQ2iOFz8+iuygxAODs9FeAEWYM=")
SITE = "https://mon-vie-via.businessfrance.fr"


def to_int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def to_offer(o):
    g = lambda *ks: next((o[k] for k in ks if o.get(k) not in (None, "", [])), "")
    return {
        "id": f"bf-{g('id')}", "source": "Business France",
        "title": str(g("missionTitle", "title")), "company": str(g("organizationName", "companyName")),
        "city": str(g("cityName")), "country": str(g("countryName")),
        "type": str(g("missionType") or "VIE"),
        "months": to_int(g("missionDuration")), "pay": to_int(g("indemnite")),
        "posted": str(g("startBroadcastDate", "creationDate"))[:10],
        "deadline": str(g("endBroadcastDate"))[:10],
        "url": f"{SITE}/offres/{g('id')}",
        "text": " ".join(v for v in o.values() if isinstance(v, str)),  # sert au scoring uniquement
    }


def source_business_france():
    headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY, "Origin": SITE,
               "Referer": SITE + "/", "User-Agent": "Mozilla/5.0 (VIE-Radar usage perso)"}
    body = {"limit": 100, "skip": 0, "query": "", "activitySectorId": [], "missionsTypesIds": [],
            "countriesIds": [], "studiesLevelId": [], "companiesSizes": [], "specializationsIds": [],
            "entreprisesIds": [], "missionStartDate": None, "gerographicZones": [],
            "countriesFilterOperator": "OR", "specializationsFilterOperator": "OR"}
    seen, out = set(), []
    for page in range(40):  # l'API plafonne à 100 offres par appel : on pagine
        r = requests.post(API_URL, json=dict(body, skip=page * 100), headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        rows = data.get("result", []) if isinstance(data, dict) else data
        fresh = [o for o in rows if o.get("id") not in seen]
        if not fresh:
            break
        for o in fresh:
            seen.add(o["id"])
            out.append(to_offer(o))
        time.sleep(0.3)  # on reste poli avec le serveur
    return out


# ── Sites carrière : deux connecteurs réutilisables ──
UA = "Mozilla/5.0 (VIE-Radar usage perso)"
TITLE_VIE = re.compile(r"\bV\.?I\.?E\b|(?i:volontariat international|volunteer for international)")
WD_BASE = os.environ.get("VIE_WD_BASE", "https://{tenant}.{wd}.myworkdayjobs.com")
EN_FR = {"united states": "Etats-Unis", "united states of america": "Etats-Unis", "usa": "Etats-Unis",
         "germany": "Allemagne", "united kingdom": "Royaume-Uni", "spain": "Espagne", "italy": "Italie",
         "belgium": "Belgique", "switzerland": "Suisse", "netherlands": "Pays-Bas", "japan": "Japon",
         "china": "Chine", "india": "Inde", "singapore": "Singapour", "brazil": "Bresil", "mexico": "Mexique",
         "australia": "Australie", "south korea": "Coree du Sud", "united arab emirates": "Emirats Arabes Unis",
         "poland": "Pologne", "sweden": "Suede", "norway": "Norvege", "denmark": "Danemark", "ireland": "Irlande",
         "austria": "Autriche", "czech republic": "Tchequie", "romania": "Roumanie", "morocco": "Maroc",
         "south africa": "Afrique du Sud", "thailand": "Thailande", "vietnam": "Vietnam", "malaysia": "Malaisie",
         "indonesia": "Indonesie", "turkey": "Turquie", "saudi arabia": "Arabie saoudite", "hungary": "Hongrie"}


def clean(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(h or ""))).strip()


def months_in(t):
    m = re.search(r"\b(6|9|12|18|24)\s*(?:months|mois|monate)", t, re.I)
    return int(m.group(1)) if m else 0


def mk(company, uid, title, url, city="", country="", text=""):
    return {"id": f"cs-{company}-{uid}", "source": company + " (site carrière)", "title": title.strip(),
            "company": company, "city": city, "country": EN_FR.get(norm(country), country), "type": "VIE",
            "months": months_in(text), "pay": 0, "posted": "", "deadline": "", "url": url, "text": text}


def workday(company, cfg):
    """API publique commune à tous les sites Workday (POST .../wday/cxs/<tenant>/<site>/jobs)."""
    tenant, wd, site = cfg
    base = WD_BASE.format(tenant=tenant, wd=wd)
    api = f"{base}/wday/cxs/{tenant}/{site}"
    H = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA}
    rows, offset, total = [], 0, None
    while True:  # 20 résultats max par appel
        r = requests.post(api + "/jobs", headers=H, timeout=30,
                          json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "VIE"})
        r.raise_for_status()
        d = r.json()
        page = d.get("jobPostings", [])
        total = d.get("total", 0) if total is None else total  # Workday ne renvoie le total qu'à la 1re page
        rows += page
        offset += 20
        if not page or offset >= min(total, 600):
            break
        time.sleep(0.3)
    out = []
    for j in rows:
        if not TITLE_VIE.search(j.get("title", "")):  # la recherche « VIE » ramène aussi le mot français « vie »
            continue
        try:
            info = requests.get(api + j["externalPath"], headers=H, timeout=30).json().get("jobPostingInfo", {})
        except Exception:
            info = {}
        loc = info.get("location") or j.get("locationsText", "")
        country = (info.get("country") or {}).get("descriptor") or loc.split(",")[-1].strip()
        out.append(mk(company, info.get("jobReqId") or j["externalPath"], j["title"],
                      info.get("externalUrl") or f"{base}/{site}{j['externalPath']}",
                      loc.split(",")[0].strip(), country, clean(info.get("jobDescription"))))
    return out


def avature(company, base):
    """Sites Avature (pages HTML /careers/SearchJobs/…). Lecture « au mieux » : plus fragile que Workday."""
    out, seen = [], set()
    for off in range(0, 300, 50):
        r = requests.get(f"{base}/SearchJobs/VIE", params={"jobRecordsPerPage": 50, "jobOffset": off},
                         headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        links = [(u, clean(t)) for u, t in re.findall(r'href="([^"]*/careers/JobDetail/[^"]+)"[^>]*>(.*?)</a>', r.text, re.S)]
        links = [(u, t) for u, t in links if t and u not in seen]
        if not links:
            break
        for u, t in links:
            seen.add(u)
            if not TITLE_VIE.search(t):
                continue
            text = clean(requests.get(u, headers={"User-Agent": UA}, timeout=30).text)
            m = re.search(r"Country\s+(.+?)\s+City\s+(.+?)\s+(?:Workplace|Employer|Domain)", text)
            out.append(mk(company, u.rstrip("/").split("/")[-1], t, u,
                          m.group(2) if m else "", m.group(1) if m else "", text))
        time.sleep(0.3)
    return out


CAREER_SITES = [  # (groupe, connecteur, paramètres, statut du réglage)
    ("Thales", workday, ("thales", "wd3", "Careers"), "confirmé"),
    ("Sanofi", workday, ("sanofi", "wd3", "SanofiCareers"), "tenant confirmé, nom du site à vérifier"),
    ("Airbus", workday, ("ag", "wd3", "Airbus"), "à vérifier"),
    ("Schneider Electric", workday, ("schneider", "wd3", "careers"), "à vérifier"),
    ("Michelin", workday, ("michelin", "wd3", "Michelin"), "à vérifier"),
    ("TotalEnergies", avature, "https://jobs.totalenergies.com/en_US/careers", "à vérifier"),
]
NON_COUVERTS = ["Arkema", "Capgemini", "LVMH", "L'Oréal", "Richemont", "Air Liquide", "Safran"]


def source_career_sites():
    out = []
    for company, connector, cfg, status in CAREER_SITES:
        try:
            got = connector(company, cfg)
            print(f"  ✓ {company} : {len(got)} offres VIE ({status})")
            out += got
        except Exception as e:  # un site en panne ne bloque pas les autres
            print(f"  ✗ {company} ({status}) : {e}", file=sys.stderr)
    print("  • sans connecteur pour l'instant : " + ", ".join(NON_COUVERTS))
    return out


SOURCES = [source_business_france, source_career_sites]


# ═════════════ 3. SCORING (sur 100, expliqué critère par critère) ═════════════
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ")


def score(o, P=PROFILE):
    text, title = norm(o["title"] + " " + o["text"]), norm(o["title"])
    if any(norm(x) in title for x in P["exclure"]):
        return 0, ["✗ mot exclu dans le titre"]
    if o["type"].upper() == "VIA" and not P["inclure_via"]:
        return 0, ["✗ VIA (administration)"]
    if norm(o["country"]) in [norm(c) for c in P["pays_exclus"]]:
        return 0, [f"✗ pays exclu : {o['country']}"]
    s, why = 0, []
    hits = [m for m in P["metiers"] if norm(m) in text]
    if hits:
        s += min(40, 25 + 5 * (len(hits) - 1)); why.append("✓ métier : " + ", ".join(hits))
    else:
        why.append("✗ aucun de tes métiers repéré")
    skills = [c for c in P["competences"] if norm(c) in text]
    if skills:
        s += min(15, 5 * len(skills)); why.append("✓ compétences : " + ", ".join(skills))
    else:
        why.append("• compétences non mentionnées dans l'offre (ne compte pas comme acquis)")
    if norm(o["country"]) in [norm(c) for c in P["pays_preferes"]]:
        s += 15; why.append(f"✓ pays souhaité : {o['country']}")
    if any(norm(e) in norm(o["company"]) for e in P["entreprises_visees"]):
        s += 10; why.append(f"✓ entreprise visée : {o['company']}")
    if o["months"]:
        ok = o["months"] >= P["duree_min_mois"]
        s += 10 if ok else -10; why.append(f"{'✓' if ok else '✗'} durée {o['months']} mois (min {P['duree_min_mois']})")
    else:
        why.append("• durée non précisée")
    if o["pay"]:
        ok = o["pay"] >= P["indemnite_min"]
        s += 10 if ok else -10; why.append(f"{'✓' if ok else '✗'} indemnité {o['pay']} €/mois (min {P['indemnite_min']})")
    else:
        why.append("• indemnité non précisée")
    return max(0, min(100, s)), why


# ═════════════ 4. SORTIES ═════════════
HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VIE Radar</title>
<style>
:root{--bg:#eef1f4;--card:#fff;--ink:#14212b;--mute:#5b6b78;--line:#d8dee4;--ok:#0b7a4b;--mid:#b26a00;--low:#8a949c}
@media(prefers-color-scheme:dark){:root{--bg:#10171d;--card:#18222a;--ink:#e8eef2;--mute:#9aabb8;--line:#2a3a46}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);padding:12px;border-bottom:1px solid var(--line);z-index:2}
h1{font-size:1.1rem;margin:0 0 8px}.row{display:flex;gap:6px;flex-wrap:wrap}
input,select{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);min-width:0}
#q{flex:1 1 100%}#cnt{color:var(--mute);font-size:.85rem;margin-top:6px}
main{padding:12px;display:grid;gap:10px;max-width:760px;margin:auto}
article{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;grid-template-columns:52px 1fr;gap:10px}
.sc{font-size:1.4rem;font-weight:700;text-align:center;align-self:start}.hi{color:var(--ok)}.md{color:var(--mid)}.lo{color:var(--low)}
article h2{font-size:1rem;margin:0}a{color:inherit}.sub{color:var(--mute);font-size:.9rem}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.chips span{border:1px solid var(--line);border-radius:99px;padding:1px 9px;font-size:.8rem}
.chips .new{border-color:var(--ok);color:var(--ok)}.chips .soon{border-color:#c0392b;color:#c0392b}
details{font-size:.88rem;color:var(--mute)}li{margin:2px 0}ul{padding-left:18px;margin:6px 0 0}
</style></head><body>
<header><h1>VIE Radar <span class="sub">mis à jour le __DATE__</span></h1><div class="row">
<input id="q" type="search" placeholder="Poste, entreprise, ville…">
<select id="c"></select>
<select id="m"><option value="0">Tous scores</option><option value="40">Score 40+</option><option value="60">Score 60+</option><option value="80">Score 80+</option></select>
<select id="s"><option value="score">Meilleur score</option><option value="deadline">Date limite</option></select>
<label><input id="n" type="checkbox"> nouvelles</label></div><div id="cnt"></div></header>
<main id="list"></main>
<script>
const D=__DATA__,$=i=>document.getElementById(i);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('c').innerHTML='<option value="">Tous pays</option>'+[...new Set(D.map(o=>o.country))].filter(Boolean).sort().map(c=>`<option>${esc(c)}</option>`).join('');
function render(){
 const q=$('q').value.toLowerCase(),c=$('c').value,m=+$('m').value,n=$('n').checked;
 const L=D.filter(o=>(!q||(o.title+o.company+o.city).toLowerCase().includes(q))&&(!c||o.country==c)&&o.score>=m&&(!n||o.new));
 L.sort($('s').value=='score'?(a,b)=>b.score-a.score:(a,b)=>(a.deadline||'9').localeCompare(b.deadline||'9'));
 $('cnt').textContent=L.length+' offres sur '+D.length+(L.length>200?' (200 affichées)':'');
 $('list').innerHTML=L.slice(0,200).map(o=>`<article><div class="sc ${o.score>=70?'hi':o.score>=40?'md':'lo'}">${o.score}</div><div>
 <h2><a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.title)}</a></h2>
 <div class="sub">${esc(o.company)} – ${esc([o.city,o.country].filter(Boolean).join(', '))}</div>
 <div class="chips">${o.new?'<span class="new">nouvelle</span>':''}<span>${esc(o.type)}</span>
 ${o.months?`<span>${o.months} mois</span>`:''}${o.pay?`<span>${o.pay} €/mois</span>`:''}
 ${o.deadline?`<span class="${o.days_left!=null&&o.days_left<=7?'soon':''}">${o.days_left!=null?(o.days_left>=0?'J-'+o.days_left:'expirée'):o.deadline}</span>`:''}
 <span>${esc(o.source)}</span></div>
 <details><summary>Pourquoi ce score</summary><ul>${o.why.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details></div></article>`).join('');
}
['q','c','m','s','n'].forEach(i=>$(i).addEventListener('input',render));render();
</script></body></html>"""


def main():
    offers = []
    for src in SOURCES:
        try:
            got = src()
            print(f"✓ {src.__name__} : {len(got)} offres")
            offers += got
        except Exception as e:  # une source en panne ne bloque pas les autres
            print(f"✗ {src.__name__} : {e}", file=sys.stderr)
    if not offers:
        sys.exit("Aucune offre récupérée (voir les messages ci-dessus).")

    # une offre déjà présente sur Business France n'est pas répétée depuis le site carrière
    def key(o):
        words = set(re.findall(r"[a-z0-9]+", norm(o["title"]))) - {"vie", "v", "i", "e", "h", "f", "m", "d", "all", "gender"}
        return " ".join(sorted(words)) + "|" + norm(o["city"])
    bf = {key(o) for o in offers if o["source"] == "Business France"}
    offers = [o for o in offers if o["source"] == "Business France" or key(o) not in bf]

    seen_file = Path("vie_seen.json")
    seen = set(json.loads(seen_file.read_text())) if seen_file.exists() else set()
    today = date.today()
    for o in offers:
        o["score"], o["why"] = score(o)
        o["new"] = bool(seen) and o["id"] not in seen  # 1er lancement : on ne marque rien
        try:
            o["days_left"] = (date.fromisoformat(o["deadline"]) - today).days
        except ValueError:
            o["days_left"] = None
        o.pop("text")
    offers.sort(key=lambda o: -o["score"])
    seen_file.write_text(json.dumps(sorted(o["id"] for o in offers)))

    Path("offres.json").write_text(json.dumps(offers, ensure_ascii=False, indent=1), encoding="utf-8")
    with open("offres.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["score", "titre", "entreprise", "ville", "pays", "type", "mois", "indemnité", "date limite", "source", "lien"])
        for o in offers:
            w.writerow([o["score"], o["title"], o["company"], o["city"], o["country"], o["type"],
                        o["months"], o["pay"], o["deadline"], o["source"], o["url"]])
    data = json.dumps(offers, ensure_ascii=False).replace("</", "<\\/")
    Path("vie_offres.html").write_text(HTML.replace("__DATA__", data).replace("__DATE__", today.strftime("%d/%m/%Y")),
                                       encoding="utf-8")
    top = sum(o["score"] >= 70 for o in offers)
    print(f"{len(offers)} offres, dont {top} à 70+ → ouvre vie_offres.html")


if __name__ == "__main__":
    main()
