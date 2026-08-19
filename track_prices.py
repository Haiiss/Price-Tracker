"""
Personal price tracker.

Paste product links into urls.txt (one per line). Every time this runs it
checks the current price of each one and sends a notification (ntfy, email,
and/or Telegram) the moment the price drops below what it was when you
first added that link - or below a target you set yourself.

Run manually:       python track_prices.py
Run on a schedule:   see .github/workflows/price-check.yml
"""

import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(__file__)
WATCHLIST_FILE = os.path.join(HERE, "urls.txt")
STATE_FILE = os.path.join(HERE, "state.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; personal-price-tracker/1.0)"}
CURRENCY_RE = re.compile(r'(?:Rs\.?|PKR|₨)\s?([\d,]+(?:\.\d+)?)')


# ---------- reading what to track ----------

def load_watchlist():
    """urls.txt: one product link per line. Add "| 3500" after a link to set
    your own target price instead of just watching for any drop below
    today's price. Lines starting with # are ignored."""
    entries = []
    if not os.path.exists(WATCHLIST_FILE):
        return entries
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                url, target = line.split("|", 1)
                url, target = url.strip(), target.strip()
                target_price = float(target) if target else None
            else:
                url, target_price = line, None
            entries.append((url, target_price))
    return entries


# ---------- state ----------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def new_entry():
    return {
        "name": None,
        "base_price": None,
        "last_price": None,
        "last_compare_at": None,
        "was_below_base": False,
        "last_checked_utc": None,
    }


# ---------- getting price + name out of a product page ----------

def to_shopify_json_url(product_url):
    """Most Shopify stores expose the exact same product data at
    /products/<handle>.json - no scraping needed. Returns None for
    URLs that clearly aren't a Shopify-style product page."""
    parsed = urlparse(product_url.split("?")[0])
    if "/products/" not in parsed.path:
        return None
    handle = parsed.path.split("/products/")[-1].rstrip("/")
    for suffix in (".html", ".json"):
        if handle.endswith(suffix):
            handle = handle[: -len(suffix)]
    return f"{parsed.scheme}://{parsed.netloc}/products/{handle}.json"


def parse_product_html(html):
    """Works on (almost) any storefront, Shopify or not. For price, tries in order:
      1) schema.org JSON-LD (the same data Google Shopping reads)
      2) itemprop="price" microdata
      3) the first Rs./PKR amount on the page (excluding struck-through text)
    Also grabs a product name (JSON-LD -> og:title -> <title>) and makes a
    best-effort attempt to find a struck-through "was" price, kept for
    context only (see fetch_product_info for why it isn't used to trigger).
    """
    soup = BeautifulSoup(html, "html.parser")
    price = None
    name = None

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if name is None and item.get("name"):
                name = item["name"]
            offers = item.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if price is None and isinstance(offers, dict) and "price" in offers:
                try:
                    price = float(offers["price"])
                except (TypeError, ValueError):
                    pass

    if price is None:
        tag = soup.find(attrs={"itemprop": "price"})
        if tag:
            digits = re.sub(r"[^\d.]", "", tag.get("content") or tag.get_text())
            if digits:
                price = float(digits)

    if name is None:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            name = og["content"].strip()
        elif soup.title and soup.title.string:
            name = soup.title.string.strip()

    was_price = None
    for tag in soup.find_all(["del", "s"]):
        match = CURRENCY_RE.search(tag.get_text(" "))
        if match:
            was_price = float(match.group(1).replace(",", ""))
            break

    if price is None:
        for tag in soup.find_all(["del", "s"]):
            tag.decompose()
        match = CURRENCY_RE.search(soup.get_text(" "))
        if match:
            price = float(match.group(1).replace(",", ""))

    return price, was_price, name


def fetch_product_info(product_url):
    """Returns {"price", "compare_at", "name"}.

    compare_at is the store's own struck-through / "regular" price, shown to
    you as context in the notification - but it is NOT what triggers a
    notification. Some stores (Zerolifestyle's earbuds are a real example)
    permanently show something like "82% off Rs.24,999" even when that
    24,999 figure never actually changes. Treating that as a live signal
    would fire a false "price drop!" the moment you added the link. What
    actually triggers a notification is the price crossing below YOUR own
    saved base_price - a number that only moves when you tell it to.
    """
    json_url = to_shopify_json_url(product_url)
    if json_url:
        try:
            r = requests.get(json_url, headers=HEADERS, timeout=15)
            if r.ok and "json" in r.headers.get("Content-Type", ""):
                data = r.json()["product"]
                variants = data["variants"]
                cheapest = min(variants, key=lambda v: float(v["price"]))
                price = float(cheapest["price"])
                compare_at = cheapest.get("compare_at_price")
                return {
                    "price": price,
                    "compare_at": float(compare_at) if compare_at else None,
                    "name": data.get("title"),
                }
        except Exception as e:
            print(f"  Shopify JSON endpoint not usable ({e}) - scraping the page instead")

    try:
        r = requests.get(product_url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        price, compare_at, name = parse_product_html(r.text)
        return {"price": price, "compare_at": compare_at, "name": name}
    except Exception as e:
        print(f"  Could not load the page: {e}")
        return {"price": None, "compare_at": None, "name": None}


# ---------- notifications ----------
# Each of these silently does nothing if its secrets aren't set, so you can
# configure any mix of the three - the script doesn't care which.

def send_ntfy(message, title=None):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    server = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
    try:
        headers = {"Title": title} if title else {}
        requests.post(f"{server}/{topic}", data=message.encode("utf-8"), headers=headers, timeout=15)
    except Exception as e:
        print(f"  ntfy send failed: {e}")


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=15,
        )
    except Exception as e:
        print(f"  Telegram send failed: {e}")


def send_email(subject, message):
    address = os.environ.get("EMAIL_ADDRESS")
    app_password = os.environ.get("EMAIL_APP_PASSWORD")
    to_addr = os.environ.get("EMAIL_TO") or address
    if not address or not app_password:
        return
    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to_addr
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(address, app_password)
            server.sendmail(address, [to_addr], msg.as_string())
    except Exception as e:
        print(f"  Email send failed: {e}")


def notify_price_drop(name, url, price, base_price, compare_at):
    lines = [
        f"Price drop: {name}",
        f"Now: Rs.{price:,.0f} (your saved price: Rs.{base_price:,.0f})",
    ]
    if compare_at and compare_at > price:
        pct = (1 - price / compare_at) * 100
        lines.append(f"Store also lists it as {pct:.0f}% off their Rs.{compare_at:,.0f} regular price")
    lines.append(url)
    message = "\n".join(lines)
    print("  " + message.replace("\n", " | "))
    send_ntfy(message, title=f"Price drop: {name}")
    send_telegram(message)
    send_email(f"Price drop: {name}", message)


# ---------- core logic ----------

def check_and_notify(url, entry, target_price):
    info = fetch_product_info(url)
    price = info["price"]

    if price is None:
        print(f"  Could not read a price for {entry.get('name') or url} this run")
        return entry

    if entry.get("name") is None and info.get("name"):
        entry["name"] = info["name"]

    is_first_check = entry.get("base_price") is None
    if target_price is not None:
        entry["base_price"] = target_price
        if is_first_check:
            print(f"  First check - tracking against your target of Rs.{target_price:,.0f}")
    elif is_first_check:
        entry["base_price"] = price
        print(f"  First check - saved base price as Rs.{price:,.0f}")

    base_price = entry["base_price"]
    compare_at = info["compare_at"]

    is_below = price < base_price
    was_below = bool(entry.get("was_below_base", False))

    if is_below and not was_below:
        notify_price_drop(entry.get("name") or url, url, price, base_price, compare_at)

    entry["last_price"] = price
    entry["last_compare_at"] = compare_at
    entry["was_below_base"] = is_below
    entry["last_checked_utc"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    return entry


def main():
    watchlist = load_watchlist()
    if not watchlist:
        print("urls.txt is empty - paste a product link on its own line to start tracking.")
        return

    state = load_state()

    for url, target_price in watchlist:
        entry = state.get(url) or new_entry()
        print(f"Checking {entry.get('name') or url} ...")
        try:
            entry = check_and_notify(url, entry, target_price)
        except Exception as e:
            print(f"  Unexpected error: {e}")
        state[url] = entry

    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
