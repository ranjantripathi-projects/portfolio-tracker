# After-sale P&L — phone app + alert bot

Two parts, both free, and neither needs your laptop once set up:

1. **The app** (Streamlit Community Cloud). Open it on your phone like any app: see the notional P&L
   of stocks you sold, upload new Excel lists, change trigger rules, start a price check.
2. **The alert bot** (GitHub Actions). Checks prices 3 times every trading day and emails
   pgp24.ranjan@spjimr.org when a trigger is newly hit.

| Market | Opening check | Mid-day check | Closing check |
|---|---|---|---|
| India (NSE/BSE) | 9:30 AM IST | 12:30 PM IST | 3:00 PM IST |
| US | 9:45 AM New York | 12:45 PM New York | 3:30 PM New York |

US times follow New York, so in IST they shift by an hour when US clocks change
(roughly 7:15 PM / 10:15 PM / 1:00 AM IST in summer, 8:15 PM / 11:15 PM / 2:00 AM IST in winter).
GitHub sometimes starts scheduled runs 5–20 minutes late.

## How the numbers work

- **Notional P&L** = (Sell price − Current price) × Quantity. Green means the stock fell after you sold.
- **BUY trigger**: price ≤ your Threshold / Expected Buy Price, or Sell price − 10% if blank.
- **MISS trigger**: price ≥ your Expected Miss Price, or Sell price + 5% if blank.
- Each trigger emails once. If the price goes back inside the range and crosses again, you get a new email.
- India and US are shown separately (₹ and $ are never added together).

## One-time setup (about 20 minutes, easiest on a laptop, possible on a phone)

### 1. Gmail sender
Alerts are sent from a Gmail account. In that account turn on 2-Step Verification, then create an
app password at https://myaccount.google.com/apppasswords. Keep the Gmail address and the
16-character password handy.

### 2. GitHub repo (stores your lists, runs the bot)
1. Sign up at https://github.com and create a **private** repository, e.g. `after-sale-pnl`.
2. Click **Add file → Upload files** and upload everything from this folder *except* the
   `.github` and `.streamlit` folders (keep the `portfolio/us` and `portfolio/india` folders).
3. Click **Add file → Create new file**, type the name `.github/workflows/price-alerts.yml`,
   paste in the contents of that file from this folder, and commit.
4. **Settings → Secrets and variables → Actions → New repository secret**: add `SMTP_USER`
   (the Gmail address) and `SMTP_PASSWORD` (the app password).
5. **Actions** tab → "Price trigger alerts" → **Run workflow** → choose `test-email`.
   You should get an email within a minute or two.

### 3. A token so the app can save files and start the bot
https://github.com/settings/personal-access-tokens/new → Fine-grained token →
Repository access: only `after-sale-pnl` → Permissions: **Contents: Read and write**,
**Actions: Read and write** → Generate. Copy the token (starts with `github_pat_`).
Set an expiry you're comfortable with; when it expires, make a new one and update step 4.

### 4. The app
1. Go to https://share.streamlit.io, sign in with GitHub, **Create app** → pick the repo,
   branch `main`, file `app.py` → Deploy.
2. App menu → **Settings → Secrets**, paste:
   ```
   GITHUB_REPO = "your-github-username/after-sale-pnl"
   GITHUB_TOKEN = "github_pat_..."
   ```
3. Open the app URL on your phone. Chrome: ⋮ → **Add to Home screen**. Safari: Share → **Add to Home Screen**.

## Using it from your phone

- **Dashboard**: switch between India and US. Prices refresh every 2 minutes while open.
- **Lists & alerts**:
  - Upload an Excel, choose India or US, then **Save and track**. The bot uses it from its next check.
  - Upload a file with the same name to replace a list, or tap **Remove** to stop tracking one.
  - Change the trigger percentages or the alert email address.
  - **Check prices now** runs the bot immediately; **Send test email** checks email still works.
  - Recent bot runs are listed with a ✅ or ❌.

The free app goes to sleep when unused; the first open can take ~30 seconds. Alerts are unaffected.

## Watchlist (stocks you want to buy)

Upload a watchlist the same way as a sold list (Lists & alerts → choose India or US → Save and track).
The app recognises it from the columns, so no extra setting is needed.

| Column | Needed? | What it does |
|---|---|---|
| Symbol (or Ticker) | Required | Stock to watch |
| Target Buy Price | Required | Email when the price falls to or below this |
| Alert Above Price | Optional | Email if the price rises to or above this |
| Notes | Optional | Shown on the dashboard and in the email |
| Exchange | Optional | NSE, BSE or US; blank = market chosen at upload |

Watchlist stocks appear in their own **Watchlist** tab, have no P&L, and are never added to your
P&L totals. `watchlist_template.xlsx` is an example. Keep Indian and US stocks in separate files.

## Excel format

Column names are flexible. These all work:

| Needed | Accepted names |
|---|---|
| Stock | Symbol, Ticker, Stock, Tradingsymbol |
| Quantity | Quantity, Qty, Shares (fractional is fine) |
| Sell price | Sell Price, Sell_Price, Selling Price, Exit Price |
| Sell date (optional) | Sell Date, Trade Date, Trade_Date |
| Buy trigger (optional) | Threshold Price, Threshold_Price, Expected Buy Price |
| Miss trigger (optional) | Expected Miss Price, Miss Price |
| Exchange (optional) | NSE, BSE or US. Blank = the market chosen at upload |

Indian stocks use NSE symbols as on Zerodha/Groww (HDFCBANK). US stocks use their ticker (NVDA, BRK.B).
`sold_stocks_template.xlsx` is a blank-ready example.

## Files

| File | Purpose |
|---|---|
| `app.py` | The phone app (Streamlit) |
| `alert_runner.py` | The bot: works out which check is due, fetches prices, emails |
| `core.py` | Excel reading, prices, P&L maths, schedule, email |
| `gh.py` | Lets the app save files to GitHub and start the bot |
| `.github/workflows/price-alerts.yml` | The bot's schedule |
| `settings.json` | Trigger % and alert email (editable in the app) |
| `alerts_state.json` | Which alerts were already sent (updated by the bot) |
| `portfolio/us/`, `portfolio/india/` | Your tracked lists |

## Good to know

- Prices come from Yahoo Finance (free, no broker login) and can be ~15 minutes delayed.
- The bot also runs on market holidays; prices don't move, so no repeat emails.
- If a stock shows "No price", its ticker changed (merger, demerger, rename). Fix the symbol in your Excel.
- Free GitHub allowance (2,000 min/month on private repos) covers this easily; the bot uses about 200.
- Personal tracking tool, not investment advice.
