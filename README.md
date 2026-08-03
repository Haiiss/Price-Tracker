# Price Tracker

Paste in a product link. Get pinged the moment it's actually cheaper.

## How it works

1. `urls.txt` is your watchlist — one product link per line, nothing fancier. Paste a link in, that's it.
2. A few times a day, GitHub runs `track_prices.py` for free on their own servers (GitHub Actions) — your phone or laptop doesn't need to be open or on.
3. For each link it gets the price two possible ways:
   - If it's a **Shopify** store, it reads the store's own `/products/<handle>.json` data directly — confirmed working against `zerolifestyle.co` (genuinely Shopify).
   - Otherwise, it reads the page itself. Confirmed working against Sapphire's page, which is actually on Salesforce Commerce Cloud, not Shopify (the giveaway is `demandware` in their image URLs) — so "works for any site" isn't just a hope here, both paths are tested against real pages.
4. The first time it checks a link, it just quietly saves the current price as your **base price** — no notification, it's establishing a starting point. From then on, if the price drops below that saved price, you get notified — once per drop, not on every single check while it stays low.
5. Want a specific number instead of "any drop from today's price"? Add `| 3500` after a link and it'll compare against 3500 instead.

### A real gotcha I found and designed around

Flow Zbuds' page shows "Sale price Rs.4,499, Regular price Rs.24,999, Save 82%." That Rs. 24,999 "regular price" looks like a permanent marketing anchor, not something that actually fluctuates — so if the tool treated "marked down from the store's regular price" as the trigger, it would fire a "price drop!" alert the moment you added the link, and never really tell you anything useful again. So that store-claimed discount is only ever shown to you as *context* in the notification. What actually triggers an alert is the price crossing below **your own saved number** — one that only moves when you say so. Tested this exact scenario before shipping it (ran it through four repeat checks with the fake 82%-off badge present the whole time — zero false alerts, as it should be).

## 1. Get this code into a GitHub repo

1. Create a free account at [github.com](https://github.com) if you don't have one.
2. Create a new repository (Private is fine).
3. On the repo page: **Add file → Upload files**, then drag in this whole `price-tracker` folder. GitHub preserves the folder paths — this matters because `price-check.yml` has to stay inside `.github/workflows/` or GitHub won't recognize it as an automation at all.

## 2. Turn on notifications

Telegram is out — it's been persistently blocked by the PTA in Pakistan since 2017 and is still down on most ISPs as of 2026, so it's not a reliable choice right now. Here's what to use instead:

### ntfy.sh (recommended — free, no account, no phone number, straight to your phone)
1. Pick a topic name only you would guess — think of it like a password, e.g. `mtn-price-alerts-x7k2q`. Anyone who knows your exact topic name could read or post to it, since the public server doesn't require login, so don't use anything obvious.
2. Install the **ntfy** app (Android/iOS) or open [ntfy.sh/app](https://ntfy.sh/app) in a browser, and subscribe to that same topic name.
3. That topic name is your `NTFY_TOPIC` secret (below). Nothing else to set up.

### Email (reliable backup, works alongside or instead of ntfy)
1. Turn on 2-Step Verification on your Google account, then create an **App Password**: Google Account → Security → App passwords. Your normal Gmail password won't work here, it has to be an app password.
2. That 16-character code is your `EMAIL_APP_PASSWORD` below.

### Telegram (still supported in the code, just not recommended right now)
If you're on a VPN, or the block lifts, the same @BotFather → `/newbot` → grab the token, then message the bot and check `https://api.telegram.org/bot<TOKEN>/getUpdates` for your chat id, same as any other Telegram bot setup. Fill in `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` if you want it as a backup.

You only need to set up one of these. ntfy is the closest match to "just buzz my phone."

## 3. Add your secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret.** Add whichever of these apply:

| Secret name | Value |
|---|---|
| `NTFY_TOPIC` | your chosen topic name |
| `EMAIL_ADDRESS` | your Gmail address |
| `EMAIL_APP_PASSWORD` | the 16-character app password |
| `EMAIL_TO` | where the alert should go (can be the same address) |
| `TELEGRAM_BOT_TOKEN` | only if you're using Telegram anyway |
| `TELEGRAM_CHAT_ID` | only if you're using Telegram anyway |

## 4. Let the workflow save its results

**Settings → Actions → General → Workflow permissions** → choose **"Read and write permissions"** → Save.
(Without this, the check runs fine but can't save what it found, so it'll try to re-notify you every single run.)

## 5. Test it

**Actions tab → Price Check → Run workflow.** Open the run and check the log — it prints what it found for each product. This first run won't notify you (both products already have today's real price saved as the base price in `state.json`) — that's correct, not a bug. You'll see a notification the first time either one actually drops.

After that it checks automatically every 4 hours (edit the `cron` line in `.github/workflows/price-check.yml` to change this — cron times are in UTC; Pakistan is UTC+5).

## Adding more products

Open `urls.txt` and paste another link on its own line:

```
https://some-other-store.com/products/whatever
https://another-store.com/products/thing | 2500
```

That's genuinely the whole process — no JSON to edit by hand. The first line watches for any drop from whatever the price is when it's first checked; the second line only notifies once that specific item hits Rs. 2,500 or below.

## Testing locally first (optional)

```bash
pip install -r requirements.txt
export NTFY_TOPIC=your-topic-name
python track_prices.py
```

## Worth knowing

- This checks a handful of times a day, not instantly — plenty for catching a sale that runs for hours or days, not a flash discount measured in minutes.
- The non-Shopify fallback reads whatever price it finds on the page (schema.org data first, then a plain Rs./PKR pattern as last resort). It's tested against two real, different-platform pages; an unusual page layout could occasionally need a small tweak inside `parse_product_html()` in `track_prices.py`.
- Keep the check interval reasonable (an hour or more) if you add a lot of products — no need to hit any store harder than that.
- A browser extension was the original idea, but it can only check prices while it's open in your browser — it can't notice a sale that starts and ends overnight. That's why the actual checking runs on GitHub's servers instead; a small companion extension (a button that appends whatever page you're on to `urls.txt`) is a reasonable v2 if you want one later.
