"""The alert bot. GitHub Actions runs this on a schedule; it checks each market
3 times a trading day (open, mid-day, close) and emails new BUY / MISS triggers.

  python alert_runner.py            # scheduled mode: only runs the slot that's due now
  python alert_runner.py --force    # check both markets right now
  python alert_runner.py --test     # send a test email
  python alert_runner.py --dry-run  # show what would be emailed, send nothing
"""
import argparse
import sys

import core


def check_market(lots, market, label, settings, state, dry_run):
    lots = lots[lots["market"] == market]
    if lots.empty:
        print(f"[{market}] no stocks listed, skipping")
        return state
    prices = core.fetch_prices(lots["yahoo"].unique())
    res = core.compute(lots, prices, settings["miss_pct"], settings["buy_pct"])
    cur = core.MARKETS[market]["cur"]
    print(f"\n[{market}] {label}")
    for _, r in res.iterrows():
        print(f"  {r['symbol']:<12} sold {core.money(r['sell_price'], cur):>12}  now "
              f"{core.money(r['ltp'], cur):>12}  buy<= {core.money(r['buy_level'], cur):>12}  "
              f"miss>= {core.money(r['miss_level'], cur):>12}  {r['status']}")
    rows, new_state = core.pending_alerts(res, state)
    if not rows:
        print(f"[{market}] no new triggers")
        return new_state
    subject, html = core.build_alert_email(rows, market, label)
    print(f"[{market}] {subject}")
    if dry_run:
        return state
    to = core.send_email(subject, html, settings)
    print(f"[{market}] emailed {to}")
    return new_state


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--test", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    settings = core.load_settings()

    if a.test:
        to = core.send_email("Test: your stock trigger alerts are working",
                             "<p>Your alert bot can send email. You'll get messages like this "
                             "when a BUY or MISS trigger hits.</p>", settings)
        print("Test email sent to", to)
        return 0

    state = core.load_state()
    due = ([(m, "manual", "Manual check") for m in core.MARKETS] if a.force
           else core.due_slots(state))
    if not due:
        print("No check is due right now (outside the open / mid-day / close windows).")
        return 0

    lots, errors = core.load_portfolio_dir()
    for e in errors:
        print("WARNING:", e)
    if lots.empty:
        print("No stock files found in portfolio/india or portfolio/us.")
        return 0

    for market, slot_id, label in due:
        state = check_market(lots, market, label, settings, state, a.dry_run)
        if slot_id != "manual":
            core.mark_slot_done(state, market, slot_id)
        else:
            core.mark_slot_done(state, market, "manual")
    if not a.dry_run:
        core.save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
