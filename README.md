# Radar VIE

Rassemble les offres de VIE (Business France + sites carrière de grands groupes), les note selon ton profil et les publie sur une page web mise à jour chaque matin en semaine.

## Mise en place (une seule fois)
1. **Secret** : Settings > Secrets and variables > Actions > *New repository secret*. Nom : `VIE_API_KEY`. Valeur : la clé de l'API Business France (celle qui était dans l'ancien `vie_radar.py`, ligne `API_KEY`, ou F12 > Network > en-tête `X-API-KEY` sur mon-vie-via.businessfrance.fr).
2. **Pages** : Settings > Pages > Source : *GitHub Actions*.
3. **Lancer** : onglet Actions > *VIE Radar* > *Run workflow*. Le résumé de l'exécution liste chaque source (✓ / ✗).

## Ton profil
Modifie uniquement `profile.toml` : la page se reconstruit toute seule après chaque modification.

## En local
Python 3.11+ requis, rien à installer : `VIE_API_KEY=... python vie_radar.py`, puis ouvre `docs/index.html`.

## Fichiers
`vie_radar.py` (programme) · `profile.toml` (ton profil) · `template.html` (la page) · `.github/workflows/vie.yml` (automatisation)

## Limites
Sans connecteur : Arkema, Capgemini, LVMH, L'Oréal, Richemont, Air Liquide, Safran. L'API de Business France n'est pas officielle : elle peut changer sans préavis. Le score est un tri par mots-clés, pas une lecture de CV.
