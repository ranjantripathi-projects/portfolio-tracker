"""Shared logic for the dashboard and the scheduled alert bot.

Notional P&L on a sold position = (Sell price - Current price) x Quantity
  positive -> the stock fell after you sold (selling saved you money)
  negative -> the stock rose after you sold (you missed that upside)
"""
from __future__ import annotations

import io
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
PORTFOLIO_DIR = HERE / "portfolio"
SETTINGS_FILE = HERE / "settings.json"
STATE_FILE = HERE / "alerts_state.json"

DEFAULT_SETTINGS = {
    "miss_pct": 5.0,    # price rises this % above sell price -> MISS
    "buy_pct": 10.0,    # price falls this % below sell price -> BUY (if no own price in the file)
    "alert_to": "pgp24.ranjan@spjimr.org",
}

# Three checks per trading day, in each market's local time.
MARKETS = {
    "IN": {"name": "India", "tz": "Asia/Kolkata", "cur": "₹",
           "slots": [("open", "Opening check", "09:30"),
                     ("mid", "Mid-day check", "12:30"),
                     ("close", "Closing check", "15:00")]},
    "US": {"name": "US", "tz": "America/New_York", "cur": "$",
           "slots": [("open", "Opening check", "09:45"),
                     ("mid", "Mid-day check", "12:45"),
                     ("close", "Closing check", "15:30")]},
}
SLOT_WINDOW = timedelta(minutes=100)   # a scheduled run counts for a slot within this window

US_EXCHANGES = {"US", "USA", "NASDAQ", "NYSE", "AMEX", "NYSEARCA", "ARCA", "BATS", "NYSE ARCA"}

COLUMN_ALIASES = {
    "symbol": ["symbol", "stock", "stock symbol", "ticker", "scrip", "tradingsymbol",
               "trading symbol", "instrument", "stock name", "name"],
    "exchange": ["exchange", "exch", "market"],
    "quantity": ["quantity", "qty", "shares", "units", "quantity sold", "qty sold"],
    "sell_price": ["sell price", "selling price", "avg sell price", "average sell price",
                   "sold at", "exit price", "sale price"],
    "sell_date": ["sell date", "sold on", "date sold", "trade date", "exit date", "date"],
    "buy_trigger": ["expected buy price", "buy trigger price", "buy trigger", "buy target",
                    "target buy price", "re entry price", "reentry price", "threshold price",
                    "threshold", "buy threshold", "trigger price"],
    "miss_trigger": ["expected miss price", "miss trigger price", "miss trigger", "miss price",
                     "miss threshold"],
}
REQUIRED = ["symbol", "quantity", "sell_price"]


# ---------------- settings ----------------

def load_settings(text: str | None = None) -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(text if text is not None else SETTINGS_FILE.read_text()))
    except Exception:
        pass
    return s


# ---------------- reading the Excel ----------------

def _norm(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text).lower())).strip()


def _map_columns(columns) -> dict:
    lookup = {_norm(a): key for key, aliases in COLUMN_ALIASES.items() for a in aliases}
    mapping = {}
    for col in columns:
        key = lookup.get(_norm(col))
        if key and key not in mapping.values():
            mapping[col] = key
    return mapping


def load_portfolio(source, default_market: str = "IN", name: str | None = None) -> pd.DataFrame:
    """Read an Excel/CSV (path, bytes or file-like) into a clean DataFrame of sold lots."""
    name = (name or getattr(source, "name", str(source))).lower()
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    sheets = {"csv": pd.read_csv(source)} if name.endswith(".csv") else pd.read_excel(source, sheet_name=None)

    for raw in sheets.values():
        for skip in range(min(6, len(raw) + 1)):   # tolerate a few title rows above the header
            if skip == 0:
                frame = raw
            else:
                frame = raw.iloc[skip:].reset_index(drop=True)
                frame.columns = raw.iloc[skip - 1].tolist()
            mapping = _map_columns(frame.columns)
            if all(r in mapping.values() for r in REQUIRED):
                df = frame.rename(columns=mapping)[list(mapping.values())].copy()
                df = _clean(df, default_market)
                df["source"] = Path(name).name
                return df
    raise ValueError(f"{Path(name).name}: couldn't find Symbol/Ticker, Quantity and Sell Price columns.")


def _clean(df: pd.DataFrame, default_market: str) -> pd.DataFrame:
    for col in ["exchange", "sell_date", "buy_trigger", "miss_trigger"]:
        if col not in df.columns:
            df[col] = pd.NA
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df = df[~df["symbol"].isin(["", "NAN", "NONE"])]
    for col in ["quantity", "sell_price", "buy_trigger", "miss_trigger"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r"[₹$,\s]", "", regex=True),
                                errors="coerce")
    df = df.dropna(subset=["quantity", "sell_price"])
    df = df[(df["quantity"] > 0) & (df["sell_price"] > 0)].copy()
    ex = [str(e).strip().upper() if pd.notna(e) else "" for e in df["exchange"]]
    ex = ["" if e in ("NAN", "<NA>", "NONE") else e for e in ex]
    df["market"] = [("US" if e in US_EXCHANGES else "IN") if e else default_market for e in ex]
    df["exchange"] = [e or ("US" if m == "US" else "NSE") for e, m in zip(ex, df["market"])]
    df["sell_date"] = [_parse_date(d) for d in df["sell_date"]]
    df["yahoo"] = [yahoo_symbol(s, e, m) for s, e, m in zip(df["symbol"], df["exchange"], df["market"])]
    return df.reset_index(drop=True)


def _parse_date(d):
    if d is None or (not isinstance(d, str) and pd.isna(d)):
        return pd.NaT
    if isinstance(d, (datetime, pd.Timestamp)):
        return pd.Timestamp(d)
    d = str(d).strip()
    iso = re.match(r"^\d{4}-\d{2}-\d{2}", d) is not None
    return pd.to_datetime(d, errors="coerce", dayfirst=not iso)


def yahoo_symbol(symbol: str, exchange: str, market: str) -> str:
    symbol = symbol.strip().upper()
    if market == "US":
        return symbol.replace(".", "-")          # BRK.B -> BRK-B
    if "." in symbol or symbol.startswith("^"):
        return symbol
    return f"{symbol}.BO" if exchange in ("BSE", "BOM") else f"{symbol}.NS"


def load_portfolio_dir(base: Path = PORTFOLIO_DIR) -> tuple[pd.DataFrame, list[str]]:
    """Read every file in portfolio/india and portfolio/us. Returns (lots, errors)."""
    frames, errors = [], []
    for market, folder in (("IN", "india"), ("US", "us")):
        for f in sorted((base / folder).glob("*")):
            if f.suffix.lower() in (".xlsx", ".xls", ".csv") and not f.name.startswith("~$"):
                try:
                    frames.append(load_portfolio(f, market))
                except Exception as e:
                    errors.append(str(e))
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), errors


# ---------------- prices ----------------

def fetch_prices(yahoo_symbols) -> dict:
    """{yahoo_symbol: {"ltp", "prev_close"}} from Yahoo Finance (may be ~15 min delayed)."""
    out = {}
    for sym in sorted(set(yahoo_symbols)):
        ltp = prev = None
        try:
            t = yf.Ticker(sym)
            try:
                ltp = float(t.fast_info["last_price"])
                prev = float(t.fast_info["previous_close"])
            except Exception:
                pass
            if not ltp or ltp != ltp:
                hist = t.history(period="5d", interval="1d")["Close"].dropna()
                if len(hist):
                    ltp = float(hist.iloc[-1])
                    prev = float(hist.iloc[-2]) if len(hist) > 1 else ltp
        except Exception:
            pass
        if ltp and ltp == ltp:
            out[sym] = {"ltp": ltp, "prev_close": prev if prev and prev == prev else ltp}
    return out


def compute(df: pd.DataFrame, prices: dict, miss_pct: float, buy_pct: float) -> pd.DataFrame:
    r = df.copy()
    r["ltp"] = r["yahoo"].map(lambda s: prices.get(s, {}).get("ltp")).astype(float)
    r["prev_close"] = r["yahoo"].map(lambda s: prices.get(s, {}).get("prev_close")).astype(float)
    r["sold_value"] = r["sell_price"] * r["quantity"]
    r["current_value"] = r["ltp"] * r["quantity"]
    r["notional_pnl"] = (r["sell_price"] - r["ltp"]) * r["quantity"]
    r["notional_pnl_pct"] = (r["sell_price"] - r["ltp"]) / r["sell_price"] * 100
    r["move_since_sell_pct"] = (r["ltp"] - r["sell_price"]) / r["sell_price"] * 100
    r["day_change_pct"] = (r["ltp"] - r["prev_close"]) / r["prev_close"] * 100
    r["day_notional_pnl"] = (r["prev_close"] - r["ltp"]) * r["quantity"]
    r["miss_level"] = r["miss_trigger"].where(r["miss_trigger"].notna(), r["sell_price"] * (1 + miss_pct / 100))
    r["buy_level"] = r["buy_trigger"].where(r["buy_trigger"].notna(), r["sell_price"] * (1 - buy_pct / 100))

    def status(row):
        if pd.isna(row["ltp"]):
            return "NO PRICE"
        if row["ltp"] <= row["buy_level"]:
            return "BUY"
        if row["ltp"] >= row["miss_level"]:
            return "MISS"
        return "WATCH"

    r["status"] = r.apply(status, axis=1) if len(r) else pd.Series(dtype=str)
    r["to_buy_pct"] = (r["ltp"] - r["buy_level"]) / r["ltp"] * 100
    r["to_miss_pct"] = (r["miss_level"] - r["ltp"]) / r["ltp"] * 100
    return r


# ---------------- schedule ----------------

def due_slots(state: dict, now_utc: datetime | None = None) -> list[tuple[str, str, str]]:
    """Which (market, slot_id, slot_label) are due now and haven't run yet today."""
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    done = state.get("_last_slot", {})
    due = []
    for mkt, cfg in MARKETS.items():
        local = now_utc.astimezone(ZoneInfo(cfg["tz"]))
        if local.weekday() >= 5:
            continue
        for slot_id, label, hhmm in cfg["slots"]:
            h, m = map(int, hhmm.split(":"))
            start = local.replace(hour=h, minute=m, second=0, microsecond=0)
            tag = f"{local:%Y-%m-%d}|{slot_id}"
            if start <= local < start + SLOT_WINDOW and done.get(mkt) != tag:
                due.append((mkt, slot_id, label))
    return due


def mark_slot_done(state: dict, market: str, slot_id: str, now_utc: datetime | None = None) -> None:
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    local = now_utc.astimezone(ZoneInfo(MARKETS[market]["tz"]))
    state.setdefault("_last_slot", {})[market] = f"{local:%Y-%m-%d}|{slot_id}"
    state.setdefault("_last_check", {})[market] = local.isoformat(timespec="minutes")


# ---------------- alert state ----------------

def lot_key(row) -> str:
    d = row["sell_date"].strftime("%Y-%m-%d") if pd.notna(row["sell_date"]) else "na"
    return f"{row['market']}|{row['yahoo']}|{d}|{row['sell_price']:.4f}|{row['quantity']:g}"


def load_state(path=STATE_FILE) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def save_state(state: dict, path=STATE_FILE) -> None:
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True))


def pending_alerts(result: pd.DataFrame, state: dict):
    """Rows to email + updated state. A lot emails once on entering BUY/MISS and re-arms
    when the price moves back inside the band."""
    new_state = dict(state)
    to_send = []
    for _, row in result.iterrows():
        key = lot_key(row)
        if row["status"] in ("BUY", "MISS"):
            if state.get(key, {}).get("status") != row["status"]:
                to_send.append(row)
                new_state[key] = {"status": row["status"], "price": round(float(row["ltp"]), 4),
                                  "at": datetime.now(ZoneInfo("UTC")).isoformat(timespec="minutes")}
        elif row["status"] == "WATCH":
            new_state.pop(key, None)
    return to_send, new_state


# ---------------- email ----------------

def smtp_settings(settings: dict | None = None) -> dict:
    settings = settings or load_settings()
    return {"host": os.getenv("SMTP_HOST") or "smtp.gmail.com",
            "port": int(os.getenv("SMTP_PORT") or 587),
            "user": os.getenv("SMTP_USER", ""),
            "password": os.getenv("SMTP_PASSWORD", ""),
            "to": os.getenv("ALERT_TO") or settings["alert_to"]}


def money(x, cur="₹", decimals=2) -> str:
    if x is None or pd.isna(x):
        return "–"
    sign = "-" if x < 0 else ""
    return f"{sign}{cur}{abs(float(x)):,.{decimals}f}"


def build_alert_email(rows, market: str, slot_label: str) -> tuple[str, str]:
    cfg = MARKETS[market]
    cur = cfg["cur"]
    buys = [r for r in rows if r["status"] == "BUY"]
    misses = [r for r in rows if r["status"] == "MISS"]
    parts = []
    if buys:
        parts.append("BUY " + ", ".join(r["symbol"] for r in buys))
    if misses:
        parts.append("MISS " + ", ".join(r["symbol"] for r in misses))
    subject = f"[{cfg['name']}] Trigger alert: " + " | ".join(parts)

    td = "padding:6px 10px;text-align:right"
    def table(items, title, colour, note):
        if not items:
            return ""
        trs = "".join(
            f"<tr><td style='padding:6px 10px'><b>{r['symbol']}</b></td>"
            f"<td style='{td}'>{money(r['sell_price'], cur)}</td>"
            f"<td style='{td}'><b>{money(r['ltp'], cur)}</b></td>"
            f"<td style='{td}'>{r['move_since_sell_pct']:+.2f}%</td>"
            f"<td style='{td}'>{money(r['buy_level'] if r['status'] == 'BUY' else r['miss_level'], cur)}</td>"
            f"<td style='{td}'>{r['quantity']:g}</td>"
            f"<td style='{td}'>{money(r['notional_pnl'], cur)}</td></tr>" for r in items)
        head = "".join(f"<th style='padding:6px 10px'>{h}</th>" for h in
                       ["Stock", "Sold at", "Now", "Move", "Trigger", "Qty", "Notional P&amp;L"])
        return (f"<h3 style='color:{colour};margin:18px 0 4px'>{title}</h3>"
                f"<p style='margin:0 0 8px;color:#555'>{note}</p>"
                "<table style='border-collapse:collapse;font-size:14px' border='1' bordercolor='#ddd'>"
                f"<tr style='background:#f4f6f8'>{head}</tr>{trs}</table>")

    now = datetime.now(ZoneInfo(cfg["tz"])).strftime("%d %b %Y, %I:%M %p %Z")
    html = ("<div style='font-family:Arial,sans-serif;color:#1d2433'>"
            f"<p>{cfg['name']} market · {slot_label} · {now}</p>"
            + table(buys, "Buy trigger hit", "#0b8a5f", "Fallen to or below your buy price since you sold.")
            + table(misses, "Miss trigger hit", "#c2410c", "Risen to or above your miss level since you sold.")
            + "<p style='color:#888;font-size:12px;margin-top:18px'>Prices from Yahoo Finance, may be "
              "delayed ~15 min. Notional P&amp;L = (sell price − current price) × qty. "
              "Not investment advice.</p></div>")
    return subject, html


def send_email(subject: str, html: str, settings: dict | None = None) -> str:
    s = smtp_settings(settings)
    if not (s["user"] and s["password"]):
        raise RuntimeError("SMTP_USER and SMTP_PASSWORD are not set.")
    recipients = [a.strip() for a in s["to"].split(",") if a.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, s["user"], ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(s["host"], s["port"], timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(s["user"], s["password"])
        server.sendmail(s["user"], recipients, msg.as_string())
    return ", ".join(recipients)
