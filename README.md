# eBay Listing Watcher Bot

Polls eBay's official **Browse API** for new listings matching criteria you define
(keywords, price range, category, auction vs. Buy It Now), and notifies you on
**Telegram** the moment a new one appears. You can also control it from Telegram
itself with commands like `/status`, `/pause`, and `/addwatch`.

It uses eBay's real API rather than scraping the website, so it won't get blocked
and stays within eBay's terms of use.

## Project structure

```
ebay-bot/
├── ebay_bot/              # the installable package
│   ├── config.py          # typed, validated config (Watch, AppConfig, Credentials)
│   ├── ebay_client.py      # eBay Browse API client with retry/backoff
│   ├── notifier.py         # Telegram notification sender
│   ├── storage.py          # SQLite-backed dedup tracking
│   ├── commands.py         # Telegram command handling (/status, /addwatch, etc.)
│   ├── logging_config.py   # stdout logging
│   └── main.py             # polling loop, graceful shutdown
├── tests/                  # pytest suite (21 tests, all mocked - no real network needed)
├── .vscode/                # VS Code debug configs, tasks, formatter/linter settings
├── pyproject.toml          # package metadata, dependencies, tool config
├── config.yaml             # your watch criteria - edit this
├── .env.example            # credentials template - copy to .env
├── ebay-bot.service         # systemd unit (Linux background service)
```

## 1. Get eBay API credentials (free)

1. Go to https://developer.ebay.com/ and sign up for a free developer account.
2. Go to **Your Account -> Application Keys**.
3. Create a keyset (choose **Production**, not Sandbox, so you see real live listings).
4. Copy the **Client ID** and **Client Secret** — you'll need them below.

No approval wait is usually required for read-only Browse API access on the free tier.

## 2. Set up your Telegram bot

1. In Telegram, message **@BotFather** and send `/newbot`. Follow the prompts (pick a
   name and a username ending in `bot`).
2. BotFather replies with a token that looks like `123456789:AAExampleTokenHere`.
   That's your `TELEGRAM_BOT_TOKEN`.
3. Start a chat with your new bot (search its username and tap **Start**, or send it
   any message) — Telegram bots can't message you until you've messaged them first.
4. Get your **chat_id**: message **@userinfobot** and it will reply with your numeric
   ID, or visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` after messaging
   your bot and look for `"chat":{"id": ...}` in the response.
5. Put both values in `.env` as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

(Optional: if you'd rather post to a Telegram **group/channel** instead of your own
DMs, add the bot to that group and use the group's chat_id instead — group chat_ids
are negative numbers.)

## 3. Open the project in VS Code

```bash
code ebay-bot
```

VS Code will prompt to install the recommended extensions (Python, Black formatter,
Ruff) — accept that. Then open a terminal inside VS Code and set up the environment:

```bash
python3 -m venv venv
```

Select the interpreter: **Ctrl+Shift+P → "Python: Select Interpreter"** → choose the
`venv` one VS Code just created. Then install the project in editable mode with dev
dependencies:

```bash
# Windows
venv\Scripts\pip install -e ".[dev]"

# macOS/Linux
venv/bin/pip install -e ".[dev]"
```

Installing with `-e` (editable mode) means changes to the code under `ebay_bot/`
take effect immediately — no reinstalling needed.

```bash
cp .env.example .env
# then edit .env and fill in your real credentials
```

## 4. Configure your watches

Edit `config.yaml` to define what you're watching for. You can add multiple watches,
each with its own keywords, price range, category, listing type, and eBay marketplace
(EBAY_US, EBAY_GB, EBAY_DE, etc). Regardless of marketplace, the bot only returns
listings whose item location is explicitly the United States:

```yaml
poll_interval_seconds: 120

watches:
  - name: "Mini PC brands"
    keywords: ""            # empty = rely entirely on the brands list to match
    category_id: "179"     # PC Desktops & All-In-Ones - scopes brand matches to
                            # actual mini PCs (without it, "Beelink" could match
                            # unrelated listings anywhere on eBay with that word in them)
    brands:                 # optional - OR-matched against listing titles/descriptions
      - "Beelink"
      - "GMKtec"
      - "Minisforum"
    exclude_keywords:       # optional - matching listing titles never trigger alerts
      - "refurbished"
      - "for parts"
    min_price: 50
    max_price: 300
    currency: "USD"
    listing_type: "BOTH"   # AUCTION | FIXED_PRICE | BOTH
    site: "EBAY_US"
```

  The bot only returns listings located in the US and uses the US as the shipping
  destination. Set the shipping destination ZIP privately in Telegram with `/zipcode`;
  eBay uses it to calculate location-based shipping estimates.

`brands` searches for any of the listed brand names appearing in the listing's actual
title/description text (using eBay's `q=(Beelink,GMKtec,Minisforum)` OR-group syntax),
combined with `keywords` via AND if both are set. This is deliberately **not** eBay's
structured "Brand" aspect_filter — that only matches the dropdown value a seller
picked when creating the listing, and misses any listing where the seller typed the
brand manually, left it blank, or used a value eBay's catalog doesn't recognize.
Searching the title text directly catches those too, at the cost of being slightly
less precise (in the rare case a brand name shows up in unrelated context).

`category_id` isn't required by eBay's API for `brands` to work, but in practice
it's doing important work: it's what keeps brand matches scoped to actual mini PCs.
Without it, a brand match is just "this word appears somewhere in a listing on all of
eBay" — no category boundary at all, so you'd risk pulling in accessories, unrelated
electronics, or anything else that happens to mention the brand name. Set it for any
watch that uses `brands` unless you deliberately want an unscoped, eBay-wide search.

`keywords` can be left empty (`""`) if you only want to filter by brand/category —
useful for catching listings that don't include an obvious keyword like "mini pc" in
their title at all (e.g. a listing just titled "Beelink SER5 Ryzen 7"). eBay's API
requires *at least one* of `keywords`, `category_id`, or `brands` to be set — the bot
validates this on load and will error clearly if all three are left blank.

Values are validated on load — e.g. an invalid `listing_type` or `min_price` greater
than `max_price` will raise a clear error immediately instead of failing silently
later.

`exclude_keywords` are checked against listing titles outside of eBay search, without
changing the results returned by the API. Matching is case-insensitive and suppresses
both new-listing and price-drop alerts for that watch; excluded items are still tracked.


## 5. Run it

From VS Code, press **F5** (uses the "Run eBay Bot" debug config in `.vscode/launch.json`),
or from a terminal in the project root:

```bash
python main.py
```

This works whether or not you installed the package with `pip install -e .` — it's a
plain script, no special setup needed beyond having the dependencies installed.
(`python -m ebay_bot` also works if you did install it in editable mode.)

On the very first run, the bot records every currently-live listing as a baseline
(no notifications sent) so you don't get flooded with hundreds of "new" items that
were already there. From the second poll onward, only genuinely new listings trigger
a notification. It will also message you on Telegram once it's started up.

Press **Ctrl+C** to stop it — this triggers a graceful shutdown (closes the database
connection cleanly, logs a shutdown message) rather than an abrupt kill.

## Running the tests

```bash
pytest -v
```

Or from VS Code: open the **Testing** sidebar (flask icon) — tests are auto-discovered,
or use **Ctrl+Shift+P → "Tasks: Run Task" → "Run tests"**. All 21 tests use mocked
HTTP calls, so they run in well under a second with no real network access or
credentials required — safe to run anytime, including in CI.

Also available as VS Code tasks (**Ctrl+Shift+P → "Tasks: Run Task"**):
- **Format (black)** — auto-formats the code
- **Lint (ruff)** — checks for style/correctness issues

## Bot commands

Message your bot on Telegram anytime:

| Command | What it does |
|---|---|
| `/help` | shows this list |
| `/status` | running/paused, uptime, watch count, last poll time |
| `/interval [seconds]` | shows the current polling interval or changes it, e.g. `/interval 120` |
| `/zipcode [US ZIP]` | sets or reports the private shipping ZIP; `/zipcode clear` removes it |
| `/pause` | stops polling eBay (bot itself stays running and responsive) |
| `/resume` | resumes polling |
| `/listwatches` | shows all active watches |
| `/addwatch name \| keywords \| min \| max \| type \| site \| category_id \| brands` | adds a new watch on the fly; existing matches are recorded silently on its first successful poll. Example: `/addwatch MiniPCs \| \| 50 \| 300 \| BOTH \| EBAY_US \| 179 \| Beelink,GMKtec,Minisforum` (site and category_id are optional per eBay's API, but set category_id when using brands or matches won't be scoped to the right category) |
| `/exkeyword watch name \| keyword` | excludes titles containing the keyword from alerts for that watch; matching is case-insensitive. Example: `/exkeyword MiniPCs \| refurbished` |
| `/removewatch name` | removes a watch by name |

Only messages from the `TELEGRAM_CHAT_ID` in your `.env` are accepted — anyone else
messaging your bot gets ignored. Watches added/removed via commands are validated
the same way as `config.yaml` entries, and saved back into `config.yaml` so they
survive restarts.

Running `python main.py` in a terminal is enough to use it — the section below is
optional, only if you later want it running unattended without keeping a terminal
open. (Docker support isn't included right now — can be added back later if useful.)

### Hosting on Railway

Railway runs this as a background worker; it does not need a public domain or HTTP
port. Create a Railway project from this repository and attach a persistent volume
mounted at `/data`. The included `railway.json` sets the install and start commands.

Add these service variables in Railway:

| Variable | Value |
|---|---|
| `EBAY_CLIENT_ID` | Your eBay production application client ID |
| `EBAY_CLIENT_SECRET` | Your eBay production application client secret |
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `CONFIG_PATH` | `/data/config.yaml` |
| `SEEN_DB_PATH` | `/data/seen_items.db` |

On first start, the bot copies the repository's `config.yaml` into the volume. The
volume then preserves watches changed with Telegram commands and the seen-listing
database across deploys and restarts. Railway captures application logs from stdout;
check them in the service's deployment logs. No `.env` file is needed in Railway.

### Running unattended: systemd (Linux server/Raspberry Pi)

1. Do the venv install from step 3 above first (so `venv/bin/python` exists).
2. Edit `ebay-bot.service` and replace every `YOUR_USER` and the paths with your
   actual username and the real path to this folder.
3. Install and start it:

```bash
sudo cp ebay-bot.service /etc/systemd/system/ebay-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now ebay-bot
```

Useful commands:

```bash
sudo systemctl status ebay-bot     # check it's running
journalctl -u ebay-bot -f          # watch live logs
sudo systemctl restart ebay-bot    # after editing config.yaml or code
```

It will now start automatically on boot and restart itself if it ever crashes.

## Securing your .env file

`.env` holds your eBay and Telegram credentials, so it deserves a bit of care:

- It's already listed in `.gitignore` — never commit it to version control.
- **Linux/macOS**: restrict it to your own user account:
  ```bash
  chmod 600 .env
  ```
- **Windows**: right-click `.env` → **Properties** → **Security** tab and remove
  access for other accounts, or from a terminal:
  ```
  icacls .env /inheritance:r /grant:r "%USERNAME%":F
  ```
- The bot automatically checks this on startup (Linux/macOS only) and logs a warning
  if `.env` is readable by other users on the machine, suggesting the `chmod` command
  above. This is informational only — it won't block the bot from starting.

## Notes

- A local SQLite file (`seen_items.db`) tracks which listings you've already been
  notified about, so restarts won't cause duplicate alerts.
- All activity (polls, errors, commands, new listings) is logged to `bot.log`
  (rotated at 2 MB, keeping 3 backups) as well as the console.
- Telegram messages use **HTML** parse mode, not Markdown. eBay titles and
  user-typed watch names/keywords often contain characters like `*`, `_`, `[`, `]`
  that break Telegram's Markdown parser and get the whole message rejected with a
  `400 Bad Request` — HTML mode sidesteps this since only `&`, `<`, `>` need
  escaping (handled automatically via Python's `html.escape()`).
- eBay API calls automatically retry up to 3 times with exponential backoff on
  transient failures (5xx errors, rate limiting) before giving up on that watch for
  the current poll — a single flaky request won't take the whole bot down.
- Respect eBay's rate limits — the free tier allows a generous number of calls/day,
  but don't set `poll_interval_seconds` too aggressively low across many watches.
- To find a specific eBay `category_id` (e.g. to narrow "mini pc" searches to just
  the Mini PC/Desktop category), browse to that category on ebay.com and check the
  `_sacat=` number in the URL. Note that some parent categories split into
  near-duplicate sub-categories — e.g. "Desktops & All-In-Ones" splits into
  **"PC Desktops & All-In-Ones"** (`179`) and **"Apple Desktops & All-In-Ones"**
  (separate ID) — so pick the specific sub-category you actually want.
#   e b a y y a g e n t 
 
 