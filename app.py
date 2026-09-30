import os, re, json, time, requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import yt_dlp
import streamlit as st

# ============================================================
# CONFIGURATION
# ============================================================

CHEMIN = "prospects.csv"

COLS_CONTACT = [
    "email",
    "instagram",
    "tiktok",
    "facebook",
    "whatsapp",
    "linktree"
]

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "m": "http://search.yahoo.com/mrss/"
}

HEAD = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "fr-FR,fr;q=0.9"
}

CK = {
    "CONSENT": "YES+1"
}


# ============================================================
# RÉCUPÉRER LES INFORMATIONS D'UNE CHAÎNE
# ============================================================

def recuperer_chaine(url):
    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "skip_download": True,
            "extract_flat": True
        }) as y:

            i = y.extract_info(url, download=False)

        return {
            "chaine": i.get("channel") or i.get("uploader"),
            "url": url,
            "abonnes": i.get("channel_follower_count"),
            "videos": i.get("playlist_count")
        }

    except Exception as e:
        return {
            "chaine": "Erreur",
            "url": url,
            "abonnes": None,
            "videos": None,
            "erreur": str(e)
        }


# ============================================================
# RÉCUPÉRER LE CHANNEL ID
# ============================================================

def recuperer_channel_id(url):

    m = re.search(r"/channel/(UC[\w-]{22})", url)

    if m:
        return m.group(1)

    r = requests.get(
        url,
        headers=HEAD,
        cookies=CK,
        timeout=20
    )

    for motif in (
        r'"externalId":"(UC[\w-]{22})"',
        r'channel_id=(UC[\w-]{22})',
        r'"channelId":"(UC[\w-]{22})"'
    ):

        m = re.search(motif, r.text)

        if m:
            return m.group(1)

    raise ValueError("channel_id introuvable")


# ============================================================
# LIRE LE RSS YOUTUBE
# ============================================================

def lire_rss(cid):

    r = requests.get(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
        timeout=20
    )

    r.raise_for_status()

    return ET.fromstring(r.content)


# ============================================================
# RÉCUPÉRER LES VIDÉOS RÉCENTES
# ============================================================

def videos_rss(cid):

    out = []

    for e in lire_rss(cid).findall("a:entry", NS):

        s = e.find(
            "m:group/m:community/m:statistics",
            NS
        )

        out.append({
            "date": e.find(
                "a:published",
                NS
            ).text[:10],

            "vues": int(
                s.get("views")
            ) if s is not None else 0
        })

    return out


# ============================================================
# ANALYSER UN PROSPECT
# ============================================================

def analyser_prospect(url):

    base = recuperer_chaine(url)

    try:

        vids = videos_rss(
            recuperer_channel_id(url)
        )

    except Exception as e:

        base["erreur"] = str(e)

        return base

    dates = sorted(
        datetime.strptime(
            v["date"],
            "%Y-%m-%d"
        )
        for v in vids
    )

    vues = [
        v["vues"]
        for v in vids
    ]

    freq = None

    if len(dates) >= 2:

        freq = round(
            max(
                (dates[-1] - dates[0]).days,
                1
            ) / (len(dates) - 1),
            1
        )

    base["vues_moyennes"] = (
        int(sum(vues) / len(vues))
        if vues else 0
    )

    base["jours_entre_videos"] = freq

    base["jours_depuis_derniere"] = (
        (datetime.now() - dates[-1]).days
        if dates
        else None
    )

    return base


# ============================================================
# SCORE D'ACTIVITÉ
# ============================================================

def score_v2(p):

    s = 0
    r = []

    ab = p.get("abonnes") or 0
    f = p.get("jours_entre_videos")
    last = p.get("jours_depuis_derniere")
    vm = p.get("vues_moyennes") or 0

    # Abonnés
    if ab >= 10000:

        s += 30
        r.append("10k+ abonnés")

    elif ab >= 1000:

        s += 15
        r.append("1k+ abonnés")

    # Fréquence
    if f is not None:

        if f <= 7:

            s += 30
            r.append("publie chaque semaine")

        elif f <= 14:

            s += 20
            r.append("publie toutes les 2 semaines")

        elif f <= 30:

            s += 10
            r.append("publie chaque mois")

    # Activité récente
    if last is not None and last <= 30:

        s += 10
        r.append("actif récemment")

    # Vues
    if vm >= 5000:

        s += 20
        r.append("bonnes vues moyennes")

    elif vm >= 1000:

        s += 10
        r.append("vues correctes")

    # Potentiel activité
    n = (
        "FORT"
        if s >= 60
        else "MOYEN"
        if s >= 35
        else "FAIBLE"
    )

    return s, n, ", ".join(r)


# ============================================================
# NOUVEAU : SCORE SPÉCIFIQUE AU POTENTIEL DE MONTAGE
# ============================================================

def score_montage(p):

    score = 0
    raisons = []

    abonnes = p.get("abonnes") or 0
    vues = p.get("vues_moyennes") or 0
    freq = p.get("jours_entre_videos")
    derniere = p.get("jours_depuis_derniere")

    # --------------------------------------------------------
    # AUDIENCE
    # --------------------------------------------------------

    if abonnes >= 50000:

        score += 20
        raisons.append("audience importante")

    elif abonnes >= 10000:

        score += 15
        raisons.append("audience intéressante")

    elif abonnes >= 5000:

        score += 10
        raisons.append("audience en développement")

    # --------------------------------------------------------
    # VUES
    # --------------------------------------------------------

    if vues >= 20000:

        score += 25
        raisons.append("fortes vues")

    elif vues >= 5000:

        score += 20
        raisons.append("bon volume de vues")

    elif vues >= 1000:

        score += 10
        raisons.append("vues régulières")

    # --------------------------------------------------------
    # FRÉQUENCE
    # --------------------------------------------------------

    if freq is not None:

        if freq <= 7:

            score += 25
            raisons.append("publication très fréquente")

        elif freq <= 14:

            score += 20
            raisons.append("publication régulière")

        elif freq <= 30:

            score += 10
            raisons.append("publication mensuelle")

    # --------------------------------------------------------
    # ACTIVITÉ RÉCENTE
    # --------------------------------------------------------

    if derniere is not None:

        if derniere <= 7:

            score += 15
            raisons.append("très actif récemment")

        elif derniere <= 30:

            score += 10
            raisons.append("actif récemment")

    # --------------------------------------------------------
    # CLASSIFICATION
    # --------------------------------------------------------

    if score >= 65:

        potentiel = "TRÈS INTÉRESSANT"

    elif score >= 45:

        potentiel = "INTÉRESSANT"

    elif score >= 25:

        potentiel = "À SURVEILLER"

    else:

        potentiel = "FAIBLE"

    return score, potentiel, ", ".join(raisons)


# ============================================================
# RECHERCHE DE CHAÎNES YOUTUBE
# ============================================================

def chercher_chaines(mot, maxi=10):

    r = requests.get(
        "https://www.youtube.com/results",
        params={
            "search_query": mot,
            "sp": "EgIQAg=="
        },
        headers=HEAD,
        cookies=CK,
        timeout=20
    )

    m = re.search(
        r"var ytInitialData = (\{.*?\});</script>",
        r.text
    )

    if not m:

        return []

    trouvees = []

    def parcourir(x):

        if isinstance(x, dict):

            if "channelRenderer" in x:

                c = x["channelRenderer"]

                b = (
                    c.get("navigationEndpoint", {})
                    .get("browseEndpoint", {})
                    .get("canonicalBaseUrl")
                )

                if b:

                    trouvees.append({
                        "nom": c.get(
                            "title",
                            {}
                        ).get(
                            "simpleText"
                        ),

                        "url":
                            "https://www.youtube.com" + b
                    })

            for v in x.values():

                parcourir(v)

        elif isinstance(x, list):

            for v in x:

                parcourir(v)

    parcourir(
        json.loads(
            m.group(1)
        )
    )

    vus = set()
    uniques = []

    for t in trouvees:

        if t["url"] not in vus:

            vus.add(t["url"])
            uniques.append(t)

    return uniques[:maxi]


# ============================================================
# AGENT PRINCIPAL
# ============================================================

def agent_prospection(
    mot,
    maxi=10,
    abonnes_max=200000
):

    lignes = []

    chaines = chercher_chaines(
        mot,
        maxi
    )

    for c in chaines:

        try:

            p = analyser_prospect(
                c["url"]
            )

        except Exception as e:

            p = {
                "url": c["url"],
                "erreur": str(e)
            }

        p["niche"] = mot

        # Limite d'abonnés
        if (
            p.get("abonnes") or 0
        ) > abonnes_max:

            continue

        # ----------------------------------------------------
        # SCORE ACTIVITÉ
        # ----------------------------------------------------

        (
            p["score_activite"],
            p["potentiel_activite"],
            p["raisons_activite"]
        ) = score_v2(p)

        # ----------------------------------------------------
        # SCORE MONTAGE
        # ----------------------------------------------------

        (
            p["score_montage"],
            p["potentiel_montage"],
            p["raisons_montage"]
        ) = score_montage(p)

        # ----------------------------------------------------
        # SCORE GLOBAL
        #
        # 40 % activité
        # 60 % potentiel montage
        # ----------------------------------------------------

        p["score"] = round(
            p["score_activite"] * 0.4
            +
            p["score_montage"] * 0.6
        )

        # ----------------------------------------------------
        # POTENTIEL GLOBAL
        # ----------------------------------------------------

        if p["score"] >= 65:

            p["potentiel"] = "TRÈS INTÉRESSANT"

        elif p["score"] >= 50:

            p["potentiel"] = "INTÉRESSANT"

        elif p["score"] >= 35:

            p["potentiel"] = "MOYEN"

        else:

            p["potentiel"] = "FAIBLE"

        # Raisons combinées

        p["raisons"] = (
            "ACTIVITÉ : "
            + p["raisons_activite"]
            + " | MONTAGE : "
            + p["raisons_montage"]
        )

        lignes.append(p)

        time.sleep(2)

    # --------------------------------------------------------
    # COLONNES
    # --------------------------------------------------------

    cols = [

        "chaine",
        "url",

        "abonnes",
        "videos",

        "vues_moyennes",
        "jours_entre_videos",
        "jours_depuis_derniere",

        "score_activite",
        "potentiel_activite",
        "raisons_activite",

        "score_montage",
        "potentiel_montage",
        "raisons_montage",

        "score",
        "potentiel",
        "raisons",

        "niche",
        "erreur"
    ]

    return (
        pd.DataFrame(lignes)
        .reindex(columns=cols)
    )


# ============================================================
# RECHERCHE DES CONTACTS PUBLICS
# ============================================================

def contacts_via_rss(url):

    racine = lire_rss(
        recuperer_channel_id(url)
    )

    texte = " ".join(
        (
            e.findtext(
                "m:group/m:description",
                default="",
                namespaces=NS
            )
            or ""
        )
        for e in racine.findall(
            "a:entry",
            NS
        )
    )

    def premier(motif):

        m = re.search(
            motif,
            texte
        )

        return (
            m.group(0).rstrip(
                ".,);"
            )
            if m
            else None
        )

    emails = set(
        re.findall(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
            texte
        )
    )

    return {

        "email":
            ", ".join(
                sorted(emails)
            )
            or None,

        "instagram":
            premier(
                r"https?://(?:www\.)?instagram\.com/[\w.]+"
            ),

        "tiktok":
            premier(
                r"https?://(?:www\.)?tiktok\.com/@[\w.]+"
            ),

        "facebook":
            premier(
                r"https?://(?:www\.)?facebook\.com/[\w.\-/]+"
            ),

        "whatsapp":
            premier(
                r"https?://(?:wa\.me|api\.whatsapp\.com)/[\w?=&+]+"
            ),

        "linktree":
            premier(
                r"https?://(?:www\.)?(?:linktr\.ee|beacons\.ai)/[\w.]+"
            )
    }


# ============================================================
# CHOISIR LE CANAL DE CONTACT
# ============================================================

def canal(l):

    # Linktree ajouté comme solution de secours
    for c in [
        "email",
        "instagram",
        "whatsapp",
        "tiktok",
        "facebook",
        "linktree"
    ]:

        if (
            isinstance(
                l.get(c),
                str
            )
            and l.get(c).strip()
        ):

            return c

    return None


# ============================================================
# GÉNÉRER UN MESSAGE PERSONNALISÉ
# ============================================================

def creer_message(l):

    f = l.get(
        "jours_entre_videos"
    )

    v = l.get(
        "vues_moyennes"
    )

    chaine = l.get(
        "chaine",
        "créateur"
    )

    if (
        isinstance(f, (int, float))
        and f == f
        and f <= 7
    ):

        acc = (
            "Je vois que tu publies "
            "très régulièrement, c'est "
            "du gros travail."
        )

    elif (
        isinstance(v, (int, float))
        and v == v
        and v >= 1000
    ):

        acc = (
            f"Tes vidéos font en moyenne "
            f"environ {int(v)} vues, bravo."
        )

    else:

        acc = (
            "J'ai découvert ta chaîne "
            "et j'aime ce que tu fais."
        )

    return (
        f"Salut {chaine} 👋\n\n"
        f"{acc}\n\n"
        "Je fais partie d'une petite "
        "équipe de monteurs vidéo. "
        "On aide les créateurs à gagner "
        "du temps et à garder les gens "
        "plus longtemps sur leurs vidéos "
        "(rythme, sous-titres, miniatures).\n\n"
        "Si tu veux, je peux te monter "
        "GRATUITEMENT un extrait d'une "
        "de tes vidéos pour que tu voies "
        "le résultat, sans engagement.\n\n"
        "Ça te dit ?"
    )


# ============================================================
# SAUVEGARDER LES PROSPECTS
# ============================================================

def sauvegarder(df_new):

    if df_new.empty:

        return

    if os.path.exists(CHEMIN):

        df = pd.concat([
            pd.read_csv(CHEMIN),
            df_new
        ])

        df = df.drop_duplicates(
            subset="url",
            keep="last"
        )

    else:

        df = df_new

    df.sort_values(
        "score",
        ascending=False
    ).reset_index(
        drop=True
    ).to_csv(
        CHEMIN,
        index=False,
        encoding="utf-8-sig"
    )


# ============================================================
# PIPELINE COMPLET
# ============================================================

def pipeline(
    niche,
    maxi=10
):

    # Recherche
    d = agent_prospection(
        niche,
        maxi
    )

    # Éviter les prospects déjà présents
    if os.path.exists(CHEMIN):

        anciens = pd.read_csv(
            CHEMIN
        )

        if "url" in anciens.columns:

            d = d[
                ~d["url"].isin(
                    set(
                        anciens["url"].dropna()
                    )
                )
            ]

    # Sauvegarde initiale
    sauvegarder(d)

    if not os.path.exists(CHEMIN):

        return

    df = pd.read_csv(
        CHEMIN
    )

    # Ajouter les colonnes manquantes
    for c in (
        COLS_CONTACT
        + [
            "canal",
            "message",
            "statut",
            "contacts_cherches"
        ]
    ):

        if c not in df.columns:

            df[c] = None

    # --------------------------------------------------------
    # RECHERCHE DES CONTACTS
    # --------------------------------------------------------

    for i, l in df.iterrows():

        if (
            not isinstance(
                l["url"],
                str
            )
            or not l["url"].startswith("http")
            or l["contacts_cherches"] is True
            or str(
                l["contacts_cherches"]
            ).lower() == "true"
        ):

            continue

        try:

            contacts = contacts_via_rss(
                l["url"]
            )

            for k, v in contacts.items():

                df.at[i, k] = v

        except Exception:

            pass

        df.at[
            i,
            "contacts_cherches"
        ] = True

        time.sleep(2)

    # --------------------------------------------------------
    # DÉTERMINER LE CANAL
    # --------------------------------------------------------

    df["canal"] = df.apply(
        canal,
        axis=1
    )

    # --------------------------------------------------------
    # GÉNÉRER LES MESSAGES
    # --------------------------------------------------------

    for i, l in df.iterrows():

        potentiel = str(
            l.get(
                "potentiel",
                ""
            )
        )

        if (
            potentiel
            in (
                "TRÈS INTÉRESSANT",
                "INTÉRESSANT",
                "MOYEN"
            )
            and l["canal"]
            and not isinstance(
                l["message"],
                str
            )
        ):

            df.at[
                i,
                "message"
            ] = creer_message(l)

            df.at[
                i,
                "statut"
            ] = "à contacter"

    # --------------------------------------------------------
    # SAUVEGARDE FINALE
    # --------------------------------------------------------

    df.sort_values(
        "score",
        ascending=False
    ).reset_index(
        drop=True
    ).to_csv(
        CHEMIN,
        index=False,
        encoding="utf-8-sig"
    )


# ================================================
