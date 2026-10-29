"""After-sale P&L: phone-friendly dashboard for stocks you've sold (India + US).

Run locally:  streamlit run app.py
Hosted:       Streamlit Community Cloud, with GITHUB_TOKEN and GITHUB_REPO in Secrets.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

import core
import gh

st.set_page_config(page_title="After-sale P&L", page_icon="📉", layout="wide",
                   initial_sidebar_state="collapsed")

try:
    for k in ["GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_BRANCH"]:
        if k in st.secrets and not os.getenv(k):
            os.environ[k] = str(st.secrets[k])
except Exception:
    pass

GREEN, RED, INK, MUTED, LINE = "#0b8a5f", "#c2410c", "#1d2433", "#6b7280", "#e5e7eb"
CONNECTED = gh.configured()

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input {{ font-family:'Manrope','Segoe UI',Arial,sans-serif !important; }}
.block-container {{ padding-top:1.4rem; padding-left:1rem; padding-right:1rem; max-width:1100px; }}
.num {{ font-variant-numeric: tabular-nums; }}
.hero {{ display:flex; flex-wrap:wrap; gap:1.2rem 2.2rem; align-items:flex-end;
         padding:0.6rem 0 1.1rem; border-bottom:1px solid {LINE}; margin-bottom:0.9rem; }}
.hero .main-figure {{ font-size:2.4rem; font-weight:800; line-height:1.05; letter-spacing:-0.02em; }}
.hero .label {{ color:{MUTED}; font-size:0.8rem; margin-bottom:0.2rem; }}
.hero .sub {{ font-size:1.05rem; font-weight:700; color:{INK}; }}
.hero .pct {{ font-size:0.95rem; font-weight:600; margin-left:0.35rem; }}
.hero .first {{ flex-basis:100%; }}
.pill {{ display:inline-block; padding:0.12rem 0.55rem; border-radius:999px; font-size:0.76rem; font-weight:700; }}
.pill.buy {{ background:#e3f4ec; color:{GREEN}; }}
.pill.miss {{ background:#fbe9e1; color:{RED}; }}
.alert-row {{ padding:0.65rem 0.9rem; border-radius:10px; margin-bottom:0.45rem; font-size:0.92rem; }}
.alert-row.buy {{ background:#e3f4ec; border-left:4px solid {GREEN}; }}
.alert-row.miss {{ background:#fbe9e1; border-left:4px solid {RED}; }}
.band {{ display:grid; grid-template-columns:8.5rem 1fr 7.5rem; gap:0.9rem; align-items:center;
         padding:0.8rem 0; border-bottom:1px solid {LINE}; }}
.band .sym {{ font-weight:800; }}
.band .meta {{ color:{MUTED}; font-size:0.76rem; }}
.track {{ position:relative; height:34px; }}
.track .rail {{ position:absolute; top:15px; left:0; right:0; height:4px; border-radius:2px;
  background:linear-gradient(90deg,{GREEN} 0%,#d1d5db 30%,#d1d5db 70%,{RED} 100%); }}
.track .tick {{ position:absolute; top:9px; width:2px; height:16px; background:{INK}; }}
.track .dot {{ position:absolute; top:9px; width:16px; height:16px; margin-left:-8px; border-radius:50%;
  border:3px solid #fff; box-shadow:0 0 0 1.5px {INK}; }}
.track .end {{ position:absolute; top:-3px; font-size:0.68rem; color:{MUTED}; }}
.band .right {{ text-align:right; font-weight:700; font-size:0.92rem; }}
@media (max-width:640px) {{
  .band {{ grid-template-columns:1fr auto; gap:0.25rem 0.8rem; }}
  .band .track {{ grid-column:1 / -1; grid-row:2; }}
  .hero .main-figure {{ font-size:2rem; }}
}}
</style>
""", unsafe_allow_html=True)


# ---------------- data loading (GitHub repo when connected, local files otherwise) ----------------

@st.cache_data(ttl=60, show_spinner=False)
def load_repo_lists() -> tuple[pd.DataFrame, list[str], list[dict]]:
    frames, errors, files = [], [], []
    for market, folder in (("IN", "india"), ("US", "us")):
        if CONNECTED:
            entries = [e for e in gh.list_dir(f"portfolio/{folder}")
                       if e["name"].lower().endswith((".xlsx", ".xls", ".csv"))]
            for e in entries:
                data, _ = gh.get_file(e["path"])
                kind = "?"
                try:
                    df = core.load_portfolio(data, market, e["name"])
                    kind = df["kind"].iloc[0] if len(df) else "?"
                    frames.append(df)
                except Exception as ex:
                    errors.append(str(ex))
                files.append({"market": market, "name": e["name"], "path": e["path"], "kind": kind})
        else:
            for f in sorted((core.PORTFOLIO_DIR / folder).glob("*")):
                if f.suffix.lower() in (".xlsx", ".xls", ".csv"):
                    kind = "?"
                    try:
                        df = core.load_portfolio(f, market)
                        kind = df["kind"].iloc[0] if len(df) else "?"
                        frames.append(df)
                    except Exception as ex:
                        errors.append(str(ex))
                    files.append({"market": market, "name": f.name, "path": str(f), "kind": kind})
    lots = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return lots, errors, files


@st.cache_data(ttl=60, show_spinner=False)
def load_repo_json(name: str) -> dict:
    if CONNECTED:
        data, _ = gh.get_file(name)
        try:
            return json.loads(data) if data else {}
        except Exception:
            return {}
    try:
        return json.loads((core.HERE / name).read_text())
    except Exception:
        return {}


@st.cache_data(ttl=25, show_spinner=False)
def get_prices(symbols: tuple) -> dict:
    return core.fetch_prices(symbols)


def refresh_data():
    load_repo_lists.clear()
    load_repo_json.clear()


try:
    lots, load_errors, files = load_repo_lists()
except Exception as e:
    lots, load_errors, files = pd.DataFrame(), [str(e)], []
settings = core.load_settings(json.dumps(load_repo_json("settings.json")))
state = load_repo_json("alerts_state.json")

# An uploaded file can be previewed before saving.
preview = st.session_state.get("preview")
if preview is not None:
    lots = pd.concat([lots, preview], ignore_index=True) if not lots.empty else preview


# ---------------- header ----------------
st.markdown("## After-sale P&L")
st.caption("What the stocks you sold would be worth today, and when to buy back or buy in.")

page_dash, page_manage = st.tabs(["Dashboard", "Lists & alerts"])

# ---------------- manage page ----------------
with page_manage:
    if not CONNECTED:
        st.info("Not connected to GitHub, so changes here can't be saved. Add GITHUB_TOKEN and "
                "GITHUB_REPO in the app's Secrets (see README).")

    st.markdown("#### Your stock lists")
    if files:
        for f in files:
            c1, c2 = st.columns([5, 1.4])
            kind = {"sold": "Sold", "watch": "Watchlist"}.get(f.get("kind"), "Unreadable")
            c1.markdown(f"**{core.MARKETS[f['market']]['name']} · {kind}** · {f['name']}")
            if CONNECTED and c2.button("Remove", key=f"rm_{f['path']}"):
                try:
                    gh.delete_file(f["path"], f"Remove {f['name']}")
                    refresh_data()
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    else:
        st.caption("No lists saved yet.")

    st.markdown("#### Add or replace a list")
    up = st.file_uploader("Excel or CSV: stocks you sold, or a watchlist", type=["xlsx", "xls", "csv"])
    st.caption("Sold list: Symbol, Quantity, Sell Price (+ optional Threshold Price). "
               "Watchlist: Symbol, Target Buy Price (+ optional Alert Above Price, Notes). "
               "The app works out which one it is from the columns.")
    mkt_label = st.radio("These stocks trade in", ["India (NSE/BSE)", "US"], horizontal=True)
    mkt = "US" if mkt_label == "US" else "IN"
    if up is not None:
        try:
            df_up = core.load_portfolio(up.getvalue(), mkt, up.name)
            what = "watchlist stocks" if (df_up["kind"] == "watch").any() else "sold stocks"
            st.success(f"Read {len(df_up)} {what} from {up.name}.")
            b1, b2 = st.columns(2)
            if b1.button("Preview on dashboard"):
                st.session_state["preview"] = df_up
                st.rerun()
            if CONNECTED and b2.button("Save and track", type="primary"):
                folder = "us" if mkt == "US" else "india"
                try:
                    gh.put_file(f"portfolio/{folder}/{up.name}", up.getvalue(), f"Update {up.name}")
                    st.session_state.pop("preview", None)
                    refresh_data()
                    st.success("Saved. The alert bot will use it from its next check.")
                except Exception as e:
                    st.error(str(e))
        except Exception as e:
            st.error(str(e))
    if preview is not None and st.button("Clear preview"):
        st.session_state.pop("preview", None)
        st.rerun()
    st.caption("Saving a file with the same name replaces the old one.")

    st.markdown("#### Trigger rules")
    with st.form("rules"):
        miss_pct = st.number_input("Miss: price rises above sell price by (%)", 0.5, 100.0,
                                   float(settings["miss_pct"]), 0.5)
        buy_pct = st.number_input("Buy: price falls below sell price by (%)", 0.5, 100.0,
                                  float(settings["buy_pct"]), 0.5)
        alert_to = st.text_input("Send alerts to", settings["alert_to"])
        st.caption("These % apply to sold stocks only. A Threshold / Expected Buy Price in your file "
                   "overrides the buy %; an Expected Miss Price overrides the miss %. "
                   "Watchlist stocks use only the prices in the watchlist file.")
        if st.form_submit_button("Save rules", disabled=not CONNECTED):
            new = {"miss_pct": miss_pct, "buy_pct": buy_pct, "alert_to": alert_to.strip()}
            try:
                gh.put_file("settings.json", (json.dumps(new, indent=2) + "\n").encode(),
                            "Update trigger rules")
                refresh_data()
                st.success("Rules saved.")
            except Exception as e:
                st.error(str(e))

    st.markdown("#### Alert bot")
    st.caption("Checks prices at open, mid-day and close: India 9:30 AM, 12:30 PM, 3:00 PM IST; "
               "US 9:45 AM, 12:45 PM, 3:30 PM New York time. Emails only when a trigger is newly hit.")
    c1, c2 = st.columns(2)
    if c1.button("Check prices now", disabled=not CONNECTED):
        try:
            gh.run_workflow("check-now")
            st.success("Started. Any triggers will be emailed in about a minute.")
        except Exception as e:
            st.error(str(e))
    if c2.button("Send test email", disabled=not CONNECTED):
        try:
            gh.run_workflow("test-email")
            st.success("Started. Check your inbox in about a minute.")
        except Exception as e:
            st.error(str(e))
    if CONNECTED:
        try:
            runs = gh.recent_runs(5)
            if runs:
                st.markdown("Recent bot runs")
                for r in runs:
                    when = datetime.fromisoformat(r["when"].replace("Z", "+00:00")).astimezone(
                        ZoneInfo("Asia/Kolkata")).strftime("%d %b, %I:%M %p IST")
                    icon = {"success": "✅", "failure": "❌"}.get(r["result"], "⏳")
                    kind = "scheduled" if r["event"] == "schedule" else "manual"
                    st.markdown(f"{icon} {when} · {kind} · [details]({r['url']})")
        except Exception as e:
            st.caption(f"Couldn't load bot runs: {e}")


# ---------------- dashboard ----------------
def signed(x) -> str:
    return GREEN if (x or 0) >= 0 else RED


with page_dash:
    for e in load_errors:
        st.warning(e)
    if lots.empty:
        st.info("No stock lists yet. Open the Lists & alerts tab to upload your Excel.")
    else:
        present = [m for m in core.MARKETS if (lots["market"] == m).any()]
        names = {core.MARKETS[m]["name"]: m for m in present}
        choice = (st.segmented_control("Market", list(names), default=list(names)[0],
                                       label_visibility="collapsed") if len(names) > 1
                  else list(names)[0])
        market = names.get(choice or list(names)[0])
        cfg = core.MARKETS[market]
        cur = cfg["cur"]
        refresh_s = 120

        @st.fragment(run_every=refresh_s)
        def dashboard(market: str):
            mlots = lots[lots["market"] == market]
            with st.spinner("Fetching prices…"):
                prices = get_prices(tuple(sorted(mlots["yahoo"].unique())))
            res = core.compute(mlots, prices, settings["miss_pct"], settings["buy_pct"])
            sold = res[res["kind"] == "sold"]
            watch = res[res["kind"] == "watch"]
            priced = sold.dropna(subset=["ltp"])
            wpriced = watch.dropna(subset=["ltp"])

            missing = res.loc[res["ltp"].isna(), "symbol"].unique().tolist()
            if missing:
                st.warning("No price found for " + ", ".join(missing) + ". Check the symbol.")

            if not sold.empty:
                total = priced["notional_pnl"].sum()
                sold_val = priced["sold_value"].sum()
                pct = total / sold_val * 100 if sold_val else 0
                day = priced["day_notional_pnl"].sum()
                n_buy = int((sold["status"] == "BUY").sum())
                n_miss = int((sold["status"] == "MISS").sum())
                w_hit = int(watch["status"].isin(["BUY", "MISS"]).sum())
                w_pill = f" <span class='pill buy'>{w_hit} watchlist</span>" if w_hit else ""
                st.markdown(f"""
                <div class="hero num">
                  <div class="first"><div class="label">Notional P&amp;L from selling</div>
                    <div class="main-figure" style="color:{signed(total)}">{core.money(total, cur, 0)}
                    <span class="pct">{pct:+.2f}%</span></div></div>
                  <div><div class="label">Sold for</div><div class="sub">{core.money(sold_val, cur, 0)}</div></div>
                  <div><div class="label">Worth today</div>
                    <div class="sub">{core.money(priced['current_value'].sum(), cur, 0)}</div></div>
                  <div><div class="label">Today</div>
                    <div class="sub" style="color:{signed(day)}">{core.money(day, cur, 0)}</div></div>
                  <div><div class="label">Triggers</div><div class="sub">
                    <span class="pill buy">{n_buy} buy</span> <span class="pill miss">{n_miss} miss</span>{w_pill}</div></div>
                </div>""", unsafe_allow_html=True)

            last = state.get("_last_check", {}).get(market)
            last_txt = ""
            if last:
                last_txt = " · Last bot check " + datetime.fromisoformat(last).strftime("%d %b, %I:%M %p")
            now = datetime.now(ZoneInfo(cfg["tz"])).strftime("%I:%M %p %Z")
            st.caption(f"Prices at {now}, refreshing every 2 min{last_txt}."
                       + (" Green P&L means the stock fell after you sold." if not sold.empty else ""))

            for _, r in res[res["status"].isin(["BUY", "MISS"])].iterrows():
                p_now = core.money(r["ltp"], cur)
                if r["kind"] == "watch":
                    if r["status"] == "BUY":
                        msg = (f"Watchlist · <b>{r['symbol']}</b> at {p_now} has reached your target buy "
                               f"price {core.money(r['buy_level'], cur)}.")
                    else:
                        msg = (f"Watchlist · <b>{r['symbol']}</b> at {p_now} is above your alert price "
                               f"{core.money(r['miss_level'], cur)}.")
                elif r["status"] == "BUY":
                    msg = (f"<b>{r['symbol']}</b> at {p_now} is at or below your buy price "
                           f"{core.money(r['buy_level'], cur)} ({r['move_since_sell_pct']:+.1f}% since sold).")
                else:
                    msg = (f"<b>{r['symbol']}</b> at {p_now} is past your miss level "
                           f"{core.money(r['miss_level'], cur)} ({r['move_since_sell_pct']:+.1f}% since sold).")
                st.markdown(f"<div class='alert-row {r['status'].lower()} num'>{msg}</div>",
                            unsafe_allow_html=True)

            tab_names = (["Sold stocks", "Table", "P&L chart"] if not sold.empty else []) + \
                        ([f"Watchlist ({len(watch)})"] if not watch.empty else [])
            tabs = dict(zip(tab_names, st.tabs(tab_names)))

            if not sold.empty:
                with tabs["Sold stocks"]:
                    st.caption("Line runs from your buy price (left) to your miss level (right). "
                               "Black tick = where you sold, dot = price now. Closest to buying first.")
                    html = []
                    for _, r in priced.sort_values("to_buy_pct").iterrows():
                        lo, hi = r["buy_level"], r["miss_level"]
                        span = hi - lo if hi > lo else 1
                        pos = lambda v: max(0.0, min(100.0, (v - lo) / span * 100))
                        dot = GREEN if r["status"] == "BUY" else RED if r["status"] == "MISS" else INK
                        if r["status"] == "BUY":
                            right = "<span class='pill buy'>Buy zone</span>"
                        elif r["status"] == "MISS":
                            right = "<span class='pill miss'>Missed</span>"
                        else:
                            right = f"<span style='color:{GREEN}'>{r['to_buy_pct']:.1f}% to buy</span>"
                        html.append(f"""
                        <div class="band num">
                          <div><div class="sym">{r['symbol']}</div>
                            <div class="meta">{core.money(r['ltp'], cur)} · sold {core.money(r['sell_price'], cur)}</div></div>
                          <div class="track"><div class="rail"></div>
                            <div class="end" style="left:0">{core.money(lo, cur, 0)}</div>
                            <div class="end" style="right:0">{core.money(hi, cur, 0)}</div>
                            <div class="tick" style="left:{pos(r['sell_price']):.1f}%"></div>
                            <div class="dot" style="left:{pos(r['ltp']):.1f}%;background:{dot}"></div></div>
                          <div class="right">{right}<br>
                            <span style="color:{signed(r['notional_pnl'])};font-size:0.8rem">
                            {core.money(r['notional_pnl'], cur)}</span></div>
                        </div>""")
                    st.markdown("".join(html), unsafe_allow_html=True)

                with tabs["Table"]:
                    view = sold.assign(
                        sell_date=sold["sell_date"].dt.strftime("%d %b %Y"),
                        status=sold["status"].map({"BUY": "🟢 Buy", "MISS": "🟠 Miss",
                                                   "WATCH": "Watching", "NO PRICE": "No price"}),
                    )[["symbol", "ltp", "notional_pnl", "move_since_sell_pct", "status", "quantity",
                       "sell_price", "sell_date", "day_change_pct", "buy_level", "miss_level"]]
                    colour = lambda v: "" if pd.isna(v) else f"color:{GREEN if v >= 0 else RED};font-weight:600"
                    styled = view.style.map(colour, subset=["notional_pnl"])
                    fmt = f"{cur}%.2f"
                    st.dataframe(styled, hide_index=True, width="stretch", column_config={
                        "symbol": st.column_config.TextColumn("Stock", pinned=True),
                        "ltp": st.column_config.NumberColumn("Price", format=fmt),
                        "notional_pnl": st.column_config.NumberColumn("Notional P&L", format=fmt),
                        "move_since_sell_pct": st.column_config.NumberColumn("Since sold", format="%+.2f%%"),
                        "status": "Status",
                        "quantity": st.column_config.NumberColumn("Qty", format="%.4g"),
                        "sell_price": st.column_config.NumberColumn("Sold at", format=fmt),
                        "sell_date": "Sold on",
                        "day_change_pct": st.column_config.NumberColumn("Day", format="%+.2f%%"),
                        "buy_level": st.column_config.NumberColumn("Buy at ≤", format=fmt),
                        "miss_level": st.column_config.NumberColumn("Miss at ≥", format=fmt),
                    })
                    st.download_button("Download CSV",
                                       sold.drop(columns=["yahoo"]).to_csv(index=False).encode(),
                                       file_name=f"notional_pnl_{market.lower()}.csv")

                with tabs["P&L chart"]:
                    agg = priced.groupby("symbol", as_index=False)["notional_pnl"].sum().sort_values("notional_pnl")
                    chart = (alt.Chart(agg).mark_bar(cornerRadiusEnd=3).encode(
                        y=alt.Y("symbol:N", sort=None, title=None),
                        x=alt.X("notional_pnl:Q", title=f"Notional P&L ({cur})"),
                        color=alt.condition(alt.datum.notional_pnl >= 0, alt.value(GREEN), alt.value(RED)),
                        tooltip=[alt.Tooltip("symbol:N", title="Stock"),
                                 alt.Tooltip("notional_pnl:Q", title="P&L", format=",.2f")])
                        .properties(height=max(220, 26 * len(agg))))
                    st.altair_chart(chart, width="stretch")

            if not watch.empty:
                with tabs[f"Watchlist ({len(watch)})"]:
                    st.caption("Stocks you're waiting to buy. Sorted by how close each is to your "
                               "target buy price. No P&L here, since you don't own them.")
                    html = []
                    for _, r in wpriced.sort_values("to_buy_pct").iterrows():
                        if r["status"] == "BUY":
                            right = "<span class='pill buy'>At target</span>"
                        elif r["status"] == "MISS":
                            right = "<span class='pill miss'>Above alert</span>"
                        else:
                            right = f"<span style='color:{GREEN}'>{r['to_buy_pct']:.1f}% to target</span>"
                        upper = (f" · alert above {core.money(r['miss_level'], cur)}"
                                 if pd.notna(r["miss_level"]) else "")
                        note = f"<div class='meta'>{r['notes']}</div>" if r.get("notes") else ""
                        day_c = r["day_change_pct"]
                        html.append(f"""
                        <div class="band num" style="grid-template-columns:1fr auto">
                          <div><div class="sym">{r['symbol']}
                              <span style="font-weight:600">{core.money(r['ltp'], cur)}</span>
                              <span style="color:{signed(day_c)};font-size:0.8rem;font-weight:600">
                              {day_c:+.2f}%</span></div>
                            <div class="meta">Target {core.money(r['buy_level'], cur)}{upper}</div>{note}</div>
                          <div class="right">{right}</div>
                        </div>""")
                    st.markdown("".join(html), unsafe_allow_html=True)

        dashboard(market)

st.caption("Prices from Yahoo Finance, may be delayed ~15 min. Personal tracking tool, not investment advice.")
