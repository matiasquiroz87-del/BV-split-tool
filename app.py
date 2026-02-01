import re
import math
import html
import xml.etree.ElementTree as ET
import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="Spartizione Detriti (OGame)", layout="wide")

# --- Costi base (presi dal tuo Excel allegato) ---
DEFAULT_COSTS = {
    "Cargo. L": {"M": 2000, "C": 2000, "D": 0},
    "Cargo. P": {"M": 6000, "C": 6000, "D": 0},
    "Caccia. L": {"M": 3000, "C": 1000, "D": 0},
    "Caccia. P": {"M": 6000, "C": 4000, "D": 0},
    "Incrociatori": {"M": 20000, "C": 7000, "D": 2000},
    "BS": {"M": 45000, "C": 15000, "D": 0},
    "Bombardieri": {"M": 50000, "C": 25000, "D": 15000},
    "Corazzate": {"M": 45000, "C": 15000, "D": 15000},
    "Rip": {"M": 5000000, "C": 4000000, "D": 1000000},
    "BC": {"M": 30000, "C": 40000, "D": 15000},
    "Pathfinder": {"M": 8000, "C": 15000, "D": 8000},
    "Reaper": {"M": 85000, "C": 55000, "D": 20000},
    "Satelliti": {"M": 0, "C": 2000, "D": 500},
    "Riciclatrici": {"M": 10000, "C": 6000, "D": 2000},
    "Colonizzatrici": {"M": 10000, "C": 20000, "D": 10000},
    "Sonde Spia": {"M": 0, "C": 1000, "D": 0},
}
SHIP_LIST = list(DEFAULT_COSTS.keys())

# --- Alias nomi navi (IT/EN) ---
SHIP_ALIASES = {
    # IT
    "Cargo leggero": "Cargo. L",
    "Cargo Leggero": "Cargo. L",
    "Cargo pesante": "Cargo. P",
    "Cargo Pesante": "Cargo. P",
    "Caccia leggero": "Caccia. L",
    "Caccia Leggero": "Caccia. L",
    "Caccia pesante": "Caccia. P",
    "Caccia Pesante": "Caccia. P",
    "Incrociatore": "Incrociatori",
    "Incrociatori": "Incrociatori",
    "Nave da battaglia": "BS",
    "Nave da Battaglia": "BS",
    "Incrociatore da battaglia": "BC",
    "Incrociatore da Battaglia": "BC",
    "Bombardiere": "Bombardieri",
    "Bombardieri": "Bombardieri",
    "Corazzata": "Corazzate",
    "Corazzate": "Corazzate",
    "Morte Nera": "Rip",
    "Riciclatrici": "Riciclatrici",
    "Riciclatrice": "Riciclatrici",
    "Colonizzatrice": "Colonizzatrici",
    "Colonizzatrici": "Colonizzatrici",
    "Sonda spia": "Sonde Spia",
    "Sonda Spia": "Sonde Spia",
    "Sonde spia": "Sonde Spia",
    "Sonde Spia": "Sonde Spia",
    "Satellite Solare": "Satelliti",
    "Satellite solare": "Satelliti",
    "Satelliti": "Satelliti",
    "Reaper": "Reaper",
    "Pathfinder": "Pathfinder",

    # EN (se capita)
    "Small Cargo": "Cargo. L",
    "Large Cargo": "Cargo. P",
    "Light Fighter": "Caccia. L",
    "Heavy Fighter": "Caccia. P",
    "Cruiser": "Incrociatori",
    "Battleship": "BS",
    "Battlecruiser": "BC",
    "Bomber": "Bombardieri",
    "Destroyer": "Corazzate",
    "Deathstar": "Rip",
    "Recycler": "Riciclatrici",
    "Colony Ship": "Colonizzatrici",
    "Espionage Probe": "Sonde Spia",
    "Solar Satellite": "Satelliti",
}

def _parse_int(num_str: str) -> int:
    s = (num_str or "").strip().replace(".", "").replace(",", "")
    return int(s) if s else 0

def ship_total_cost(costs: dict, ship: str) -> float:
    c = costs[ship]
    return c["M"] + c["C"] + c["D"]

def parse_cr(text: str):
    """
    Parser "robusto" per i due formati che mi hai incollato:

    1) CR classico:
       - blocchi "Attaccante <nick>" / "Difensore <nick>" con flotte iniziali
       - sezione "Dopo la battaglia..." con flotte finali e perdite tra parentesi
       - righe DF: "At these space coordinates now float ... metal, ... crystal and ... deuterium."

    2) CR riassuntivo:
       - righe del tipo: "Caccia Leggero 8.690.366 -782.497" (finale + delta)
       - sezione "Tutti Attaccante" + "<nick> Difensore"

    Ritorna:
      fleets: {nick: {"initial":{ship:qty}, "final":{ship:qty}}}  (solo per navi in SHIP_LIST)
      meta: {"df":{"M":..,"C":..,"D":..}, "loot":{"M":..,"C":..,"D":..}, "attacker_recycled_all": bool}
    """
    fleets = {}
    meta = {"df": None, "loot": None, "attacker_recycled_all": False}

    if not text or not text.strip():
        return fleets, meta

    lines = [ln.rstrip() for ln in text.splitlines()]

    # --- meta: DF e loot (dal CR classico) ---
    df_pat = re.compile(r'now float\s+([\d\.,]+)\s+metal,\s+([\d\.,]+)\s+crystal\s+and\s+([\d\.,]+)\s+deuterium', re.IGNORECASE)
    loot_pat = re.compile(r"L'attaccante\s+saccheggia:\s*([\d\.,]+)\s+Metallo,\s+([\d\.,]+)\s+Cristallo\s+e\s+([\d\.,]+)\s+Deuterio", re.IGNORECASE)
    for ln in lines:
        mdf = df_pat.search(ln)
        if mdf:
            meta["df"] = {"M": _parse_int(mdf.group(1)), "C": _parse_int(mdf.group(2)), "D": _parse_int(mdf.group(3))}
        mloot = loot_pat.search(ln)
        if mloot:
            meta["loot"] = {"M": _parse_int(mloot.group(1)), "C": _parse_int(mloot.group(2)), "D": _parse_int(mloot.group(3))}
        if "ha riciclato il campo detriti" in ln.lower():
            meta["attacker_recycled_all"] = True

    # --- helper: parse fleet block lines ---
    # Iniziale (classico): "Caccia Leggero 3.226.909"
    ship_line_init = re.compile(r'^\s*([A-Za-zÀ-ÿ\.\s]+?)\s+([\d\.,]+)\s*$')
    # Finale (classico): "Caccia Leggero 2.961.733 ( -265.176 )"
    ship_line_final = re.compile(r'^\s*([A-Za-zÀ-ÿ\.\s]+?)\s+([\d\.,]+)\s*\(\s*([+-]?[\d\.,]+)\s*\)\s*$')
    # Riassuntivo: "Caccia Leggero 8.690.366 -782.497"
    ship_line_summary = re.compile(r'^\s*([A-Za-zÀ-ÿ\.\s]+?)\s+([\d\.,]+)\s+(-|[+-][\d\.,]+)\s*$')

    # Headers classico
    hdr_att = re.compile(r'^\s*Attaccante\s+(.+?)\s*(?:\[|$)', re.IGNORECASE)
    hdr_def = re.compile(r'^\s*Difensore\s+(.+?)\s*(?:\[|$)', re.IGNORECASE)

    # Header riassuntivo
    hdr_all_att = re.compile(r'^\s*Tutti\s+Attaccante\s*:?\s*$', re.IGNORECASE)
    hdr_def_sum = re.compile(r'^\s*(.+?)\s+Difensore\s*:?\s*$', re.IGNORECASE)

    # State machine: pre-battle vs after-battle
    in_after = False

    i = 0
    while i < len(lines):
        ln = lines[i].strip()

        if ln.lower().startswith("dopo la battaglia"):
            in_after = True
            i += 1
            continue

        # Decide which headers we are in
        sec_name = None

        mA = hdr_att.match(ln)
        mD = hdr_def.match(ln)
        if mA:
            sec_name = mA.group(1).strip()
        elif mD:
            sec_name = mD.group(1).strip()

        # Summary-style headers
        if sec_name is None:
            if hdr_all_att.match(ln):
                sec_name = "Attaccanti (tutti)"
            else:
                mds = hdr_def_sum.match(ln)
                if mds and "attaccante" not in ln.lower():  # evita prendere "Tutti Attaccante" qui
                    raw = mds.group(1).strip()
                    raw = raw.split(" di ")[0].strip()
                    sec_name = raw

        if sec_name is None:
            i += 1
            continue

        fleets.setdefault(sec_name, {"initial": {s:0 for s in SHIP_LIST}, "final": {s:0 for s in SHIP_LIST}})
        i += 1

        # consume lines until next header or separator line
        while i < len(lines):
            cur = lines[i].strip()

            if cur.startswith("_____") or cur == "":
                i += 1
                continue

            if cur.lower().startswith("dopo la battaglia"):
                break

            # stop if next header
            if hdr_att.match(cur) or hdr_def.match(cur) or hdr_all_att.match(cur) or hdr_def_sum.match(cur):
                break

            # "Distrutto!"
            if "distrutto" in cur.lower():
                # final = 0 for everything; losses handled later if needed
                i += 1
                continue

            # Parse summary line
            ms = ship_line_summary.match(cur)
            if ms and not in_after:
                raw = re.sub(r'\s+', ' ', ms.group(1).strip())
                final_qty = _parse_int(ms.group(2))
                delta_raw = ms.group(3).strip()
                loss_qty = 0
                if delta_raw != "-" and delta_raw.startswith("-"):
                    loss_qty = _parse_int(delta_raw[1:])
                if raw in SHIP_ALIASES:
                    ship = SHIP_ALIASES[raw]
                    fleets[sec_name]["final"][ship] += final_qty
                    fleets[sec_name]["initial"][ship] += final_qty + loss_qty
                i += 1
                continue

            # Parse final line (after-battle)
            mf = ship_line_final.match(cur)
            if mf and in_after:
                raw = re.sub(r'\s+', ' ', mf.group(1).strip())
                fin_qty = _parse_int(mf.group(2))
                loss_qty = _parse_int(mf.group(3).replace("+","").replace("-",""))  # valore assoluto
                if raw in SHIP_ALIASES:
                    ship = SHIP_ALIASES[raw]
                    fleets[sec_name]["final"][ship] += fin_qty
                    fleets[sec_name]["initial"][ship] += fin_qty + loss_qty
                i += 1
                continue

            # Parse initial line (pre-battle)
            mi = ship_line_init.match(cur)
            if mi and not in_after:
                raw = re.sub(r'\s+', ' ', mi.group(1).strip())
                qty = _parse_int(mi.group(2))
                if raw in SHIP_ALIASES:
                    ship = SHIP_ALIASES[raw]
                    fleets[sec_name]["initial"][ship] += qty
                i += 1
                continue

            i += 1

    # Se nel CR classico abbiamo anche i blocchi "Dopo la battaglia..." per lo stesso nick,
    # il nostro parser aggiunge initial anche lì (fin+loss). Per evitare doppio conteggio:
    # se esiste un initial "pre-battle" e un "after-battle", qui non possiamo distinguerli
    # facilmente; ma nel classico, dopo-battaglia non va sommato al pre: va usato quello dopo.
    # Quindi: se il testo contiene "Dopo la battaglia..." e per un nick abbiamo final>0 o losses,
    # allora ricalcoliamo initial e final SOLO dal dopo-battaglia (già in initial = fin+loss),
    # ma dobbiamo cancellare i valori pre-battle che erano stati messi.
    #
    # Soluzione: in questo parser, nel "dopo-battaglia" abbiamo popolato initial e final,
    # mentre nel pre-battle solo initial. Se un nick ha final>0 in almeno una nave, assumiamo
    # che quel nick sia stato trovato nella sezione dopo-battaglia e *ignora* l'initial pre-battle
    # ricostruendo initial = final + perdite (già).
    # Per farlo, serve riconoscere se abbiamo aggiunto fin in after. Lo facciamo: se final_sum>0
    # e initial_sum>=final_sum => teniamo così e basta. Non possiamo rimuovere il pre aggiunto,
    # quindi in pratica va bene solo se pre NON è stato aggiunto per lo stesso nick.
    # Ma nel CR classico sì, viene aggiunto. Quindi aggiungiamo una seconda passata: estraiamo
    # solo le flotte del dopo-battaglia con un parser dedicato e sovrascriviamo.

    if any("Dopo la battaglia" in ln for ln in lines):
        fleets_after = {}
        in_after = False
        i = 0
        while i < len(lines):
            ln = lines[i].strip()
            if ln.lower().startswith("dopo la battaglia"):
                in_after = True
                i += 1
                continue
            if not in_after:
                i += 1
                continue

            mA = hdr_att.match(ln)
            mD = hdr_def.match(ln)
            if not (mA or mD):
                i += 1
                continue
            nick = (mA.group(1) if mA else mD.group(1)).strip()
            fleets_after.setdefault(nick, {"initial": {s:0 for s in SHIP_LIST}, "final": {s:0 for s in SHIP_LIST}})
            i += 1
            while i < len(lines):
                cur = lines[i].strip()
                if hdr_att.match(cur) or hdr_def.match(cur) or cur.lower().startswith("l'attaccante ha vinto") or cur.lower().startswith("l'attaccante/i"):
                    break
                if "distrutto" in cur.lower():
                    i += 1
                    break
                mf = ship_line_final.match(cur)
                if mf:
                    raw = re.sub(r'\s+', ' ', mf.group(1).strip())
                    fin_qty = _parse_int(mf.group(2))
                    loss_qty = _parse_int(mf.group(3).replace("+","").replace("-",""))
                    if raw in SHIP_ALIASES:
                        ship = SHIP_ALIASES[raw]
                        fleets_after[nick]["final"][ship] += fin_qty
                        fleets_after[nick]["initial"][ship] += fin_qty + loss_qty
                i += 1

        # Sovrascrivi i nick presenti nel dopo-battaglia (quelli affidabili)
        for nick, data in fleets_after.items():
            fleets[nick] = data

        # Defender distrutto: se presente blocco after con "Distrutto!" potrebbe aver lasciato initial=0.
        # In quel caso, se abbiamo un initial pre-battle, calcoliamo final=0 e initial=pre.
        for nick, data in list(fleets.items()):
            if sum(data["final"].values()) == 0 and sum(data["initial"].values()) == 0:
                # prova a recuperare pre-battle
                pass

    return fleets, meta

def _clean_cr_html(raw: str) -> str:
    cleaned = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = html.unescape(cleaned)
    return cleaned.strip()

def fetch_cr_from_api(url: str) -> str:
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    content = response.text
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return _clean_cr_html(content)

    report_el = root.find(".//report")
    if report_el is None:
        return _clean_cr_html(content)
    return _clean_cr_html(report_el.text or "")

st.title("Spartizione detriti (OGame) — logica come l'Excel")

with st.expander("🔧 Impostazioni", expanded=True):
    col1, col2, col3 = st.columns([1,1,2])
    with col1:
        n_players = st.number_input("Numero giocatori (ACS)", min_value=1, max_value=5, value=2, step=1)
    with col2:
        debris_factor = st.number_input("Fattore detriti (nave → DF)", min_value=0.0, max_value=1.0, value=0.70, step=0.01)
    with col3:
        st.caption(
            "Logica 'ibrida' del foglio: **compensazione perdite + quota a peso della flotta in campo**, "
            "meno quanto ciascuno ha già riciclato."
        )

st.divider()

# --- Giocatori ---
st.subheader("1) Giocatori")
player_cols = st.columns(int(n_players))
players = []
for i in range(int(n_players)):
    with player_cols[i]:
        nick = st.text_input(f"Nick giocatore {i+1}", value=f"Player {i+1}", key=f"nick_{i}")
        players.append(nick)

# --- CR Paste helper ---
st.subheader("0) (Opzionale) Incolla Combat Report per auto-compilare")
st.caption("Funziona sia con CR classico (con 'Dopo la battaglia...') sia con CR riassuntivo (tipo il primo che mi hai mandato).")

with st.expander("🌐 Carica CR da API", expanded=False):
    st.caption("Inserisci l'URL completo della API CR (ogame: /api/cr.xml?apiKey=...).")
    api_url = st.text_input("URL API CR", placeholder="https://sXXX-it.ogame.gameforge.com/api/cr.xml?apiKey=...", key="api_url")
    load_api = st.button("📥 Carica CR da API", use_container_width=True)
    if load_api:
        if not api_url.strip():
            st.error("Inserisci un URL valido per la API CR.")
        else:
            try:
                cr_text_api = fetch_cr_from_api(api_url.strip())
                if not cr_text_api:
                    st.error("Nessun CR trovato nella risposta API.")
                else:
                    st.session_state["cr_text"] = cr_text_api
                    st.success("CR caricato dalla API. Ora puoi analizzarlo.")
            except requests.RequestException as exc:
                st.error(f"Errore durante la richiesta API: {exc}")
            except Exception as exc:
                st.error(f"Errore durante la lettura del CR: {exc}")

cr_text = st.text_area("Combat Report", height=260, placeholder="Incolla qui il CR...", key="cr_text")

colA, colB, colC = st.columns([1,1,2])
with colA:
    parse_btn = st.button("🔍 Analizza CR", use_container_width=True)
with colB:
    apply_btn = st.button("✅ Applica ai giocatori (match per nick)", use_container_width=True)
with colC:
    st.caption("Tip: se i nick nel CR combaciano con quelli inseriti sopra, l’app compila tutto in automatico.")

if parse_btn:
    fleets, meta = parse_cr(cr_text)
    st.session_state["cr_fleets"] = fleets
    st.session_state["cr_meta"] = meta

fleets = st.session_state.get("cr_fleets", {})
meta = st.session_state.get("cr_meta", {})

if fleets:
    with st.expander("🧾 Dettagli estratti dal CR", expanded=True):
        st.write("Nick trovati:", ", ".join(fleets.keys()))
        if meta and meta.get("df"):
            st.write("DF trovato (metal/crystal/deut):", meta["df"])
        if meta and meta.get("loot"):
            st.write("Bottino (metal/crystal/deut):", meta["loot"])
        if meta and meta.get("attacker_recycled_all"):
            st.info("Nel CR risulta che gli attaccanti hanno riciclato il campo detriti.")

        # Opzione: distribuire DF totale sui ricicli (utile quando il CR non dice chi ha riciclato cosa)
        if meta and meta.get("df"):
            st.markdown("**Auto-compila riciclo totale (opzionale)**")
            mode = st.selectbox(
                "Come vuoi assegnare il DF riciclato?",
                ["Non compilare automaticamente", "Assegna tutto a un giocatore", "Dividi per quota peso (flotta in campo)"],
                index=0,
                key="df_mode",
            )
            collector = None
            if mode == "Assegna tutto a un giocatore":
                collector = st.selectbox("Giocatore che ha riciclato", players, key="df_collector")
            st.caption("Nota: verrà compilato nel riquadro Riciclo → 'Riciclatrici' (non distingue Reaper).")

if apply_btn and fleets:
    applied = 0
    # Applica flotta in campo e perdite ai giocatori con nick combaciante (case-insensitive)
    for p in players:
        match = None
        for k in fleets.keys():
            if k.lower() == p.lower():
                match = k
                break
        if not match:
            continue

        init = fleets[match]["initial"]
        fin = fleets[match]["final"]

        for ship in SHIP_LIST:
            st.session_state[f"field_{p}_{ship}"] = int(init.get(ship, 0))
            lost_qty = max(int(init.get(ship, 0)) - int(fin.get(ship, 0)), 0)
            if lost_qty > 0:
                st.session_state[f"lost_{p}_{ship}"] = int(lost_qty)

        applied += 1

    # Se scelto, compila anche riciclo DF
    if meta and meta.get("df"):
        mode = st.session_state.get("df_mode", "Non compilare automaticamente")
        if mode == "Assegna tutto a un giocatore":
            collector = st.session_state.get("df_collector")
            if collector:
                st.session_state[f"recM_rec_{collector}"] = int(meta["df"]["M"])
                st.session_state[f"recC_rec_{collector}"] = int(meta["df"]["C"])
                st.session_state[f"recD_rec_{collector}"] = int(meta["df"]["D"])
        elif mode == "Dividi per quota peso (flotta in campo)":
            # Calcola pesi usando COSTS default (basta per ripartizione; si può rifare dopo anche se modifichi costi)
            def weight_from_init(player_name):
                w = 0.0
                # usa init fleet del CR se esiste
                for k in fleets.keys():
                    if k.lower() == player_name.lower():
                        init = fleets[k]["initial"]
                        for ship in SHIP_LIST:
                            c = DEFAULT_COSTS[ship]
                            w += float(init.get(ship, 0)) * (c["M"] + c["C"] + c["D"])
                return w

            weights = {p: weight_from_init(p) for p in players}
            tot = sum(weights.values())
            if tot > 0:
                for p in players:
                    share = weights[p] / tot
                    st.session_state[f"recM_rec_{p}"] = int(round(meta["df"]["M"] * share))
                    st.session_state[f"recC_rec_{p}"] = int(round(meta["df"]["C"] * share))
                    st.session_state[f"recD_rec_{p}"] = int(round(meta["df"]["D"] * share))

    if applied == 0:
        st.warning("Nessun nick del CR combacia con i giocatori inseriti sopra. Rinomina i giocatori (anche solo maiuscole/minuscole) e riprova.")
    else:
        st.success(f"Auto-compilazione applicata a {applied} giocatori (match per nick).")

st.divider()

# --- Costi modificabili (opzionale) ---
with st.expander("💰 Tabella costi (modificabile)", expanded=False):
    costs_df = pd.DataFrame(
        [{"Nave": s, "M": DEFAULT_COSTS[s]["M"], "C": DEFAULT_COSTS[s]["C"], "D": DEFAULT_COSTS[s]["D"]} for s in SHIP_LIST]
    )
    edited = st.data_editor(costs_df, use_container_width=True, num_rows="fixed", key="costs_editor")
    COSTS = {row["Nave"]: {"M": float(row["M"]), "C": float(row["C"]), "D": float(row["D"])} for _, row in edited.iterrows()}

# --- Input flotte perse ---
st.subheader("2) Flotta persa (per giocatore)")
lost = {p: {s: 0 for s in SHIP_LIST} for p in players}
lost_tabs = st.tabs(players)
for p, tab in zip(players, lost_tabs):
    with tab:
        cols = st.columns(4)
        for idx, ship in enumerate(SHIP_LIST):
            with cols[idx % 4]:
                lost[p][ship] = st.number_input(
                    f"{ship}",
                    min_value=0,
                    value=int(st.session_state.get(f"lost_{p}_{ship}", 0)),
                    step=1,
                    key=f"lost_{p}_{ship}",
                )

# --- Input flotta in campo ---
st.subheader("3) Flotta in campo (per il peso)")
in_field = {p: {s: 0 for s in SHIP_LIST} for p in players}
field_tabs = st.tabs(players)
for p, tab in zip(players, field_tabs):
    with tab:
        cols = st.columns(4)
        for idx, ship in enumerate(SHIP_LIST):
            with cols[idx % 4]:
                in_field[p][ship] = st.number_input(
                    f"{ship}",
                    min_value=0,
                    value=int(st.session_state.get(f"field_{p}_{ship}", 0)),
                    step=1,
                    key=f"field_{p}_{ship}",
                )

# --- Input riciclo (riciclatrici + reaper) ---
st.subheader("4) Riciclo per giocatore")
recycle = {p: {"M": {"Riciclatrici": 0, "Reaper": 0},
              "C": {"Riciclatrici": 0, "Reaper": 0},
              "D": {"Riciclatrici": 0, "Reaper": 0}} for p in players}

rec_tabs = st.tabs(players)
for p, tab in zip(players, rec_tabs):
    with tab:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Metallo (M)**")
            recycle[p]["M"]["Riciclatrici"] = st.number_input("Riciclatrici", min_value=0, value=int(st.session_state.get(f"recM_rec_{p}", 0)), step=1, key=f"recM_rec_{p}")
            recycle[p]["M"]["Reaper"] = st.number_input("Reaper", min_value=0, value=int(st.session_state.get(f"recM_rea_{p}", 0)), step=1, key=f"recM_rea_{p}")
        with c2:
            st.markdown("**Cristallo (C)**")
            recycle[p]["C"]["Riciclatrici"] = st.number_input("Riciclatrici ", min_value=0, value=int(st.session_state.get(f"recC_rec_{p}", 0)), step=1, key=f"recC_rec_{p}")
            recycle[p]["C"]["Reaper"] = st.number_input("Reaper ", min_value=0, value=int(st.session_state.get(f"recC_rea_{p}", 0)), step=1, key=f"recC_rea_{p}")
        with c3:
            st.markdown("**Deuterio (D)**")
            recycle[p]["D"]["Riciclatrici"] = st.number_input("Riciclatrici  ", min_value=0, value=int(st.session_state.get(f"recD_rec_{p}", 0)), step=1, key=f"recD_rec_{p}")
            recycle[p]["D"]["Reaper"] = st.number_input("Reaper  ", min_value=0, value=int(st.session_state.get(f"recD_rea_{p}", 0)), step=1, key=f"recD_rea_{p}")

st.divider()

# --- Calcoli ---
lost_res = {p: {"M": 0.0, "C": 0.0, "D": 0.0} for p in players}
for p in players:
    for ship in SHIP_LIST:
        qty = float(lost[p][ship] or 0)
        c = COSTS[ship]
        lost_res[p]["M"] += qty * c["M"]
        lost_res[p]["C"] += qty * c["C"]
        lost_res[p]["D"] += qty * c["D"]

weights = {p: 0.0 for p in players}
for p in players:
    for ship in SHIP_LIST:
        qty = float(in_field[p][ship] or 0)
        weights[p] += qty * ship_total_cost(COSTS, ship)

total_weight = sum(weights.values())
shares = {p: (weights[p] / total_weight if total_weight > 0 else 0.0) for p in players}

recycled = {p: {"M": 0.0, "C": 0.0, "D": 0.0} for p in players}
for p in players:
    for r in ["M","C","D"]:
        recycled[p][r] = float(recycle[p][r]["Riciclatrici"] or 0) + float(recycle[p][r]["Reaper"] or 0)

lost_total = {r: sum(lost_res[p][r] for p in players) for r in ["M","C","D"]}
recycled_total = {r: sum(recycled[p][r] for p in players) for r in ["M","C","D"]}

gain = {r: recycled_total[r] - lost_total[r] for r in ["M","C","D"]}

due_hybrid = {p: {r: (gain[r] * shares[p]) + lost_res[p][r] - recycled[p][r] for r in ["M","C","D"]} for p in players}


# --- Trasporti necessari per la ridistribuzione ---
st.subheader("5) Trasporti necessari (post-raccolta)")
st.caption("Calcolo dei carichi necessari per trasferire le risorse tra i giocatori in base alla spartizione finale.")

with st.expander("🚚 Impostazioni trasporti", expanded=True):
    colA, colB = st.columns(2)
    with colA:
        cargo_type = st.selectbox(
            "Tipo di nave da trasporto",
            ["Cargo Leggero (5.000)", "Cargo Pesante (25.000)"],
            index=1,
        )
    with colB:
        st.caption("Capacità standard OGame, senza bonus tecnologia.")

cargo_capacity = 5000 if "Leggero" in cargo_type else 25000

# Calcolo risorse nette per giocatore
net = {p: {r: round(due_hybrid[p][r]) for r in ["M","C","D"]} for p in players}

# Totale da spedire per chi deve dare (valori negativi)
rows_t = []
for p in players:
    give = sum(-v for v in net[p].values() if v < 0)
    receive = sum(v for v in net[p].values() if v > 0)
    ships_needed = math.ceil(max(give, receive) / cargo_capacity) if max(give, receive) > 0 else 0
    rows_t.append({
        "Giocatore": p,
        "Deve dare (tot risorse)": give,
        "Deve ricevere (tot risorse)": receive,
        "Capacità nave": cargo_capacity,
        "Trasporti minimi": ships_needed,
    })

transport_df = pd.DataFrame(rows_t)

st.dataframe(transport_df, use_container_width=True)
st.caption("Nota: il numero di trasporti è una stima minima (carichi ottimizzati, senza vuoti).")


st.subheader("Risultati")

rows = []
for p in players:
    rows.append({
        "Giocatore": p,
        "Peso flotta": round(weights[p]),
        "Quota peso": shares[p],
        "Perdite M": round(lost_res[p]["M"]),
        "Perdite C": round(lost_res[p]["C"]),
        "Perdite D": round(lost_res[p]["D"]),
        "Riciclato M": round(recycled[p]["M"]),
        "Riciclato C": round(recycled[p]["C"]),
        "Riciclato D": round(recycled[p]["D"]),
        "Ibrida: M dovuto(+) / da dare(-)": round(due_hybrid[p]["M"]),
        "Ibrida: C dovuto(+) / da dare(-)": round(due_hybrid[p]["C"]),
        "Ibrida: D dovuto(+) / da dare(-)": round(due_hybrid[p]["D"]),
    })
out_df = pd.DataFrame(rows)

c1, c2 = st.columns([2,1])
with c1:
    st.dataframe(out_df, use_container_width=True)
with c2:
    st.markdown("**Totali**")
    st.write({
        "Perdite": {k: round(v) for k,v in lost_total.items()},
        "Riciclato": {k: round(v) for k,v in recycled_total.items()},
        "Gain da dividere": {k: round(v) for k,v in gain.items()},
    })

st.caption("Interpretazione: valori **positivi** in 'Ibrida' = risorse che il giocatore deve ricevere; valori **negativi** = risorse che deve trasferire agli altri.")

# ----------------------------
# Trasferimenti consigliati (per ridistribuire dopo le raccolte)
# ----------------------------
def settle_transactions(amounts_by_player: dict):
    """
    amounts_by_player: {player: amount} dove:
      >0 = deve ricevere
      <0 = deve dare
    Ritorna lista transazioni: (da, a, amount)
    """
    eps = 0.5  # tolleranza arrotondamenti
    creditors = [(p, v) for p, v in amounts_by_player.items() if v > eps]
    debtors = [(p, -v) for p, v in amounts_by_player.items() if v < -eps]  # amount to pay (positive)
    creditors.sort(key=lambda x: x[1], reverse=True)
    debtors.sort(key=lambda x: x[1], reverse=True)

    tx = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        dp, damt = debtors[i]
        cp, camt = creditors[j]
        send = min(damt, camt)
        if send > eps:
            tx.append((dp, cp, send))
        damt -= send
        camt -= send
        debtors[i] = (dp, damt)
        creditors[j] = (cp, camt)
        if damt <= eps:
            i += 1
        if camt <= eps:
            j += 1
    return tx

def ceil_div(a, b):
    return int(math.ceil(a / b)) if b > 0 else 0

with st.expander("🚚 Trasporti necessari per ridistribuire (calcolati dai saldi Ibridi)", expanded=True):
    st.caption(
        "Calcolo automatico dei **trasferimenti** tra membri per azzerare i saldi. "
        "Le transazioni sono calcolate separatamente per M/C/D e poi aggregate per coppia (da→a)."
    )

    cap_choice = st.selectbox(
        "Tipo trasporto per stimare le navi necessarie",
        ["Cargo. L (5.000)", "Cargo. P (25.000)"],
        index=1,
    )
    capacity = 5000 if "5.000" in cap_choice else 25000

    # Transazioni per risorsa
    tx_by_res = {}
    for r in ["M", "C", "D"]:
        amounts = {p: float(due_hybrid[p][r]) for p in players}
        tx_by_res[r] = settle_transactions(amounts)

    # Aggrega per coppia (da,a)
    agg = {}
    for r in ["M", "C", "D"]:
        for frm, to, amt in tx_by_res[r]:
            key = (frm, to)
            agg.setdefault(key, {"M": 0.0, "C": 0.0, "D": 0.0})
            agg[key][r] += amt

    # Tabella finale
    tx_rows = []
    for (frm, to), v in agg.items():
        total_payload = v["M"] + v["C"] + v["D"]
        ships = ceil_div(total_payload, capacity)
        tx_rows.append({
            "Da": frm,
            "A": to,
            "Metallo": int(round(v["M"])),
            "Cristallo": int(round(v["C"])),
            "Deuterio": int(round(v["D"])),
            "Totale carico": int(round(total_payload)),
            f"N° {cap_choice.split()[0]}": ships,
        })
    tx_df = pd.DataFrame(tx_rows).sort_values(["Da","A"]) if tx_rows else pd.DataFrame(columns=["Da","A","Metallo","Cristallo","Deuterio","Totale carico", f"N° {cap_choice.split()[0]}"])

    if tx_df.empty:
        st.info("Non risultano trasferimenti (tutti i saldi sono ~0).")
    else:
        st.dataframe(tx_df, use_container_width=True)

        # Dettaglio per risorsa (opzionale)
        with st.expander("Dettaglio transazioni per singola risorsa", expanded=False):
            for r, label in [("M","Metallo"),("C","Cristallo"),("D","Deuterio")]:
                st.markdown(f"**{label}**")
                rows_r = [{"Da": a, "A": b, label: int(round(v))} for a,b,v in tx_by_res[r]]
                st.dataframe(pd.DataFrame(rows_r) if rows_r else pd.DataFrame(columns=["Da","A",label]), use_container_width=True)

        csv_tx = tx_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Scarica trasporti (CSV)", data=csv_tx, file_name="trasporti_ridistribuzione.csv", mime="text/csv")

# Export CSV risultati
csv = out_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Scarica risultati (CSV)", data=csv, file_name="spartizione_detriti_risultati.csv", mime="text/csv")
