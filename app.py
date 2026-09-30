import os, re, json, time, requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import yt_dlp
import streamlit as st

CHEMIN = "prospects.csv"
COLS_CONTACT = ["email", "instagram", "tiktok", "facebook", "whatsapp", "linktree"]
NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://search.yahoo.com/mrss/"}
HEAD = {"User-Agent": "Mozilla/5.0", "Accept-Language": "fr-FR,fr;q=0.9"}
CK = {"CONSENT": "YES+1"}

def recuperer_chaine(url):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}) as y:
            i = y.extract_info(url, download=False)
        return {"chaine": i.get("channel") or i.get("uploader"), "url": url,
                "abonnes": i.get("channel_follower_count"), "videos": i.get("playlist_count")}
    except Exception as e:
        return {"chaine": "Erreur", "url": url, "abonnes": None, "videos": None, "erreur": str(e)}

def recuperer_channel_id(url):
    m = re.search(r"/channel/(UC[\w-]{22})", url)
    if m:
        return m.group(1)
    r = requests.get(url, headers=HEAD, cookies=CK, timeout=20)
    for motif in (r'"externalId":"(UC[\w-]{22})"', r'channel_id=(UC[\w-]{22})', r'"channelId":"(UC[\w-]{22})"'):
        m = re.search(motif, r.text)
        if m:
            return m.group(1)
    raise ValueError("channel_id introuvable")

def lire_rss(cid):
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=20)
    r.raise_for_status()
    return ET.fromstring(r.content)

def videos_rss(cid):
    out = []
    for e in lire_rss(cid).findall("a:entry", NS):
        s = e.find("m:group/m:community/m:statistics", NS)
        out.append({"date": e.find("a:published", NS).text[:10],
                    "vues": int(s.get("views")) if s is not None else 0})
    return out

def analyser_prospect(url):
    base = recuperer_chaine(url)
    try:
        vids = videos_rss(recuperer_channel_id(url))
    except Exception as e:
        base["erreur"] = str(e)
        return base
    dates = sorted(datetime.strptime(v["date"], "%Y-%m-%d") for v in vids)
    vues = [v["vues"] for v in vids]
    freq = None
    if len(dates) >= 2:
        freq = round(max((dates[-1] - dates[0]).days, 1) / (len(dates) - 1), 1)
    base["vues_moyennes"] = int(sum(vues) / len(vues)) if vues else 0
    base["jours_entre_videos"] = freq
    base["jours_depuis_derniere"] = (datetime.now() - dates[-1]).days if dates else None
    return base

def score_v2(p):
    s, r = 0, []
    ab = p.get("abonnes") or 0
    f = p.get("jours_entre_videos")
    last = p.get("jours_depuis_derniere")
    vm = p.get("vues_moyennes") or 0
    if ab >= 10000: s += 30; r.append("10k+ abonnés")
    elif ab >= 1000: s += 15; r.append("1k+ abonnés")
    if f is not None:
        if f <= 7: s += 30; r.append("publie chaque semaine")
        elif f <= 14: s += 20; r.append("publie toutes les 2 semaines")
        elif f <= 30: s += 10; r.append("publie chaque mois")
    if last is not None and last <= 30: s += 10; r.append("actif récemment")
    if vm >= 5000: s += 20; r.append("bonnes vues moyennes")
    elif vm >= 1000: s += 10; r.append("vues correctes")
    n = "FORT" if s >= 60 else "MOYEN" if s >= 35 else "FAIBLE"
    return s, n, ", ".join(r)

def chercher_chaines(mot, maxi=10):
    r = requests.get("https://www.youtube.com/results", params={"search_query": mot, "sp": "EgIQAg=="},
                     headers=HEAD, cookies=CK, timeout=20)
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text)
    if not m:
        return []
    trouvees = []
    def parcourir(x):
        if isinstance(x, dict):
            if "channelRenderer" in x:
                c = x["channelRenderer"]
                b = c.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("canonicalBaseUrl")
                if b:
                    trouvees.append({"nom": c.get("title", {}).get("simpleText"), "url": "https://www.youtube.com" + b})
            for v in x.values():
                parcourir(v)
        elif isinstance(x, list):
            for v in x:
                parcourir(v)
    parcourir(json.loads(m.group(1)))
    vus, uniques = set(), []
    for t in trouvees:
        if t["url"] not in vus:
            vus.add(t["url"])
            uniques.append(t)
    return uniques[:maxi]

def agent_prospection(mot, maxi=10, abonnes_max=200000):
    lignes = []
    for c in chercher_chaines(mot, maxi):
        try:
            p = analyser_prospect(c["url"])
        except Exception as e:
            p = {"url": c["url"], "erreur": str(e)}
        p["niche"] = mot
        if (p.get("abonnes") or 0) > abonnes_max:
            continue
        p["score"], p["potentiel"], p["raisons"] = score_v2(p)
        lignes.append(p)
        time.sleep(2)
    cols = ["chaine", "url", "abonnes", "vues_moyennes", "jours_entre_videos",
            "score", "potentiel", "raisons", "niche", "erreur"]
    return pd.DataFrame(lignes).reindex(columns=cols)

def sauvegarder(df_new):
    if os.path.exists(CHEMIN):
        df = pd.concat([pd.read_csv(CHEMIN), df_new]).drop_duplicates(subset="url", keep="last")
    else:
        df = df_new
    df.sort_values("score", ascending=False).reset_index(drop=True).to_csv(CHEMIN, index=False, encoding="utf-8-sig")

def contacts_via_rss(url):
    racine = lire_rss(recuperer_channel_id(url))
    texte = " ".join((e.findtext("m:group/m:description", default="", namespaces=NS) or "")
                     for e in racine.findall("a:entry", NS))
    def premier(motif):
        m = re.search(motif, texte)
        return m.group(0).rstrip(".,);") if m else None
    emails = set(re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b", texte))
    return {"email": ", ".join(sorted(emails)) or None,
            "instagram": premier(r"https?://(?:www\.)?instagram\.com/[\w.]+"),
            "tiktok": premier(r"https?://(?:www\.)?tiktok\.com/@[\w.]+"),
            "facebook": premier(r"https?://(?:www\.)?facebook\.com/[\w.\-/]+"),
            "whatsapp": premier(r"https?://(?:wa\.me|api\.whatsapp\.com)/[\w?=&+]+"),
            "linktree": premier(r"https?://(?:www\.)?(?:linktr\.ee|beacons\.ai)/[\w.]+")}

def canal(l):
    for c in ["email", "instagram", "whatsapp", "tiktok", "facebook"]:
        if isinstance(l.get(c), str) and l.get(c):
            return c
    return None

def creer_message(l):
    f, v = l.get("jours_entre_videos"), l.get("vues_moyennes")
    if isinstance(f, (int, float)) and f == f and f <= 7:
        acc = "Je vois que tu publies très régulièrement, c'est du gros travail."
    elif isinstance(v, (int, float)) and v == v and v >= 1000:
        acc = f"Tes vidéos font en moyenne environ {int(v)} vues, bravo."
    else:
        acc = "J'ai découvert ta chaîne et j'aime ce que tu fais."
    return (f"Salut {l['chaine']} 👋\n\n{acc}\n\n"
            "Je fais partie d'une petite équipe de monteurs vidéo. "
            "On aide les créateurs à gagner du temps et à garder les gens plus longtemps "
            "sur leurs vidéos (rythme, sous-titres, miniatures).\n\n"
            "Si tu veux, je peux te monter GRATUITEMENT un extrait d'une de tes vidéos "
            "pour que tu voies le résultat, sans engagement.\n\nÇa te dit ?")

def pipeline(niche, maxi=10):
    d = agent_prospection(niche, maxi)
    if os.path.exists(CHEMIN):
        d = d[~d["url"].isin(set(pd.read_csv(CHEMIN)["url"].dropna()))]
    sauvegarder(d)
    if not os.path.exists(CHEMIN):
        return
    df = pd.read_csv(CHEMIN)
    for c in COLS_CONTACT + ["canal", "message", "statut", "contacts_cherches"]:
        if c not in df.columns:
            df[c] = None
    for i, l in df.iterrows():
        if not isinstance(l["url"], str) or not l["url"].startswith("http") or l["contacts_cherches"] == True:
            continue
        try:
            for k, v in contacts_via_rss(l["url"]).items():
                df.at[i, k] = v
        except Exception:
            pass
        df.at[i, "contacts_cherches"] = True
        time.sleep(2)
    df["canal"] = df.apply(canal, axis=1)
    for i, l in df.iterrows():
        if l["potentiel"] in ("FORT", "MOYEN") and l["canal"] and not isinstance(l["message"], str):
            df.at[i, "message"] = creer_message(l)
            df.at[i, "statut"] = "à contacter"
    df.sort_values("score", ascending=False).reset_index(drop=True).to_csv(CHEMIN, index=False, encoding="utf-8-sig")

def marquer(nom):
    df = pd.read_csv(CHEMIN)
    m = df["chaine"].str.contains(nom, case=False, na=False, regex=False)
    df.loc[m, "statut"] = "contacté"
    df.to_csv(CHEMIN, index=False, encoding="utf-8-sig")

# ---------------- Interface ----------------
st.set_page_config(page_title="Agent de prospection", page_icon="🤖")
st.title("🤖 Agent de prospection")

tab1, tab2, tab3 = st.tabs(["🔎 Recherche", "✉️ À contacter", "💾 Sauvegarde"])

with tab1:
    mot = st.text_input("Niche ou mot-clé", placeholder="ex : vlog Bénin")
    nb = st.slider("Nombre de chaînes", 5, 20, 10)
    if st.button("Lancer la recherche", type="primary"):
        if not mot.strip():
            st.warning("Écris un mot-clé d'abord")
        else:
            with st.spinner("Recherche en cours, ça peut prendre quelques minutes..."):
                try:
                    pipeline(mot.strip(), nb)
                    st.success("✅ Recherche terminée")
                except Exception as e:
                    st.error(f"Erreur : {str(e)[:200]}")
    if os.path.exists(CHEMIN):
        df = pd.read_csv(CHEMIN)
        cols = [c for c in ["chaine", "potentiel", "score", "canal", "statut"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
    else:
        st.info("Aucun prospect pour l'instant.")

with tab2:
    if not os.path.exists(CHEMIN):
        st.info("Aucun prospect pour l'instant.")
    else:
        df = pd.read_csv(CHEMIN)
        if "statut" not in df.columns:
            st.info("Aucun prospect à contacter pour l'instant.")
        else:
            a = df[df["statut"] == "à contacter"]
            if a.empty:
                st.success("Plus personne à contacter 🎉")
            else:
                l = a.iloc[0]
                st.subheader(f"{l['chaine']} — {l['potentiel']} ({l['score']})")
                st.write("Chaîne :", l["url"])
                st.write(f"Contact ({l['canal']}) :", l[l["canal"]])
                st.caption("Message prêt à envoyer (bouton de copie en haut à droite) :")
                st.code(l["message"], language=None)
                if st.button("✅ J'ai contacté ce prospect"):
                    marquer(l["chaine"])
                    st.rerun()

with tab3:
    st.write("Les fichiers en ligne peuvent s'effacer. Télécharge tes prospects de temps en temps.")
    if os.path.exists(CHEMIN):
        with open(CHEMIN, "rb") as f:
            st.download_button("⬇️ Télécharger mes prospects", f.read(),
                               file_name="prospects.csv", mime="text/csv")
    fichier = st.file_uploader("Restaurer un fichier prospects.csv", type="csv")
    if fichier is not None and st.button("Restaurer ce fichier"):
        with open(CHEMIN, "wb") as f:
            f.write(fichier.getvalue())
        st.success("✅ Restauré")
        st.rerun()
