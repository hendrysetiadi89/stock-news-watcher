#!/usr/bin/env python3
"""
stock-news-watcher
Pantau berita/keterbukaan informasi pasar modal Indonesia, deteksi yang BARU
(dedup via SQLite), lalu keluarkan sebagai JSON atau kirim ke Telegram.

Sumber & topik diatur lewat config.json di folder yang sama.

Pemakaian:
  python watch.py --list                     # lihat status sumber & topik
  python watch.py --enable-source idx_disclosure
  python watch.py --disable-topic komoditas
  python watch.py --seed                     # tandai semua berita sekarang sbg sudah dibaca
  python watch.py                            # cetak berita baru sebagai JSON
  python watch.py --telegram                 # kirim berita baru langsung ke Telegram
  python watch.py --dry-run                  # lihat hasil tanpa menandai sudah dibaca
"""
import argparse, html as htmllib, json, os, re, sqlite3, sys, time
import urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "seen.db")
CONFIG_PATH = os.path.join(BASE, "config.json")
ENV_PATH = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
WIB = timezone(timedelta(hours=7))

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
HREF_RE = re.compile(r'href="([^"]+)"', re.I)
TITLE_ATTR_RE = re.compile(r'title="([^"]*)"', re.I)
H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.I | re.S)
TIME_RE = re.compile(r"<time[^>]*>(.*?)</time>", re.I | re.S)
SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.I | re.S)
LEADING_DATE_RE = re.compile(r"^\d{1,2}\s+\w{3}\s+\d{4}\s+\d{1,2}:\d{2}\s*", re.I)
TICKER_RE = re.compile(r"\b[A-Z]{4}\b")

PASARDANA_HREF_RE = re.compile(r"^/news/\d{4}/\d{1,2}/\d{1,2}/[^\s\"#?]+$")
IDN_HREF_RE = re.compile(r"^https://www\.idnfinancials\.com/news/\d+/[^\s\"#?]+$")

IDX_PAGE = "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi"
# Endpoint yang dipakai halaman keterbukaan informasi. JANGAN tambahkan parameter
# dateFrom/dateTo/keyword/emitenType -- server membalas 503 kalau ada.
# Endpoint lama /primary/ListedCompany/GetAnnouncement TIDAK dipakai lagi: datanya
# tertinggal berjam-jam dari halaman web (pernah terukur 5,5 jam).
IDX_API = ("https://www.idx.co.id/primary/NewsAnnouncement/GetAllAnnouncement"
           "?indexFrom=1&pageSize={size}&lang=id")


# ---------------------------------------------------------------- config

DEFAULT_CONFIG = {
    "_readme": [
        "Atur apa yang dipantau di sini. Ubah 'enabled' jadi true/false.",
        "Bisa juga lewat CLI: --list, --enable-source X, --disable-source X,",
        "--enable-topic Y, --disable-topic Y.",
        "TOPIK: kalau SEMUA topik dimatikan, semua berita lolos (tanpa filter).",
        "Kalau ada minimal satu topik aktif, berita harus cocok >=1 kata kunci",
        "dari topik aktif tsb, ATAU menyebut salah satu kode di options.tickers.",
        "PER SUMBER: field 'topics' pada sebuah sumber membatasi topik mana yang",
        "berlaku untuk sumber itu saja. Kosong / tidak ada = semua topik aktif berlaku.",
        "idx_disclosure dibatasi ke aksi_korporasi + kinerja_keuangan karena IDX",
        "mengirim puluhan pengumuman rutin per hari (Pencatatan Saham, Laporan Bulanan).",
    ],
    "sources": {
        "pasardana":      {"enabled": True, "label": "Pasar Dana"},
        "idnfinancials":  {"enabled": True, "label": "IDN Financials"},
        "kontan_insight": {"enabled": True, "label": "Kontan Insight"},
        "kabarbursa":     {"enabled": True, "label": "Kabar Bursa"},
        "idx_disclosure": {"enabled": True, "label": "IDX Keterbukaan Informasi",
                           "topics": ["aksi_korporasi", "kinerja_keuangan"]},
    },
    "topics": {
        "ihsg_dan_pasar": {"enabled": True, "keywords": [
            "ihsg", "indeks", "bursa", "idx", "jci", "market", "pasar saham",
            "saham", "emiten", "perdagangan", "auto reject", "suspensi"]},
        "aksi_korporasi": {"enabled": True, "keywords": [
            "rups", "dividen", "ipo", "right issue", "hmetd", "buyback",
            "pembelian kembali", "stock split", "akuisisi", "merger",
            "penggabungan", "tender offer", "private placement", "delisting",
            "public expose", "obligasi", "sukuk"]},
        "kinerja_keuangan": {"enabled": True, "keywords": [
            "laba", "rugi", "pendapatan", "kinerja", "laporan keuangan",
            "revenue", "profit", "earnings", "margin", "ebitda"]},
        "aliran_dana_asing": {"enabled": True, "keywords": [
            "asing", "foreign", "net buy", "net sell", "inflow", "outflow",
            "top buy", "top sell"]},
        "makro_dan_moneter": {"enabled": True, "keywords": [
            "rupiah", "inflasi", "bi rate", "suku bunga", "bank indonesia",
            "the fed", "ojk", "apbn", "pdb", "gdp"]},
        "komoditas": {"enabled": False, "keywords": [
            "emas", "batu bara", "batubara", "cpo", "sawit", "minyak", "nikel",
            "timah", "tembaga", "gas"]},
        "global": {"enabled": False, "keywords": [
            "wall street", "dow jones", "nasdaq", "s&p", "hang seng", "nikkei",
            "china", "amerika"]},
    },
    "options": {
        "pasardana_days": 2,
        "idx_page_size": 100,
        "max_per_run": 15,
        "tickers": [],
        "_tickers_note": "Isi mis. [\"BBCA\",\"TLKM\"] untuk selalu meloloskan berita yang menyebut kode ini.",
    },
}


def deep_fill(target, default):
    """Tambahkan key yang hilang dari default, tanpa menimpa nilai user."""
    changed = False
    for k, v in default.items():
        if k not in target:
            target[k] = v
            changed = True
        elif isinstance(v, dict) and isinstance(target[k], dict):
            changed = deep_fill(target[k], v) or changed
    return changed


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        log(f"config.json dibuat dengan nilai default: {CONFIG_PATH}")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        log(f"config.json rusak ({e}) -> memakai default. Perbaiki atau hapus file itu.")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    if deep_fill(cfg, DEFAULT_CONFIG):
        save_config(cfg)
        log("config.json dilengkapi dengan key baru dari versi terbaru.")
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def toggle(cfg, section, key, value):
    if key not in cfg[section]:
        valid = ", ".join(sorted(cfg[section]))
        print(f"'{key}' tidak ada di {section}. Pilihan: {valid}")
        return False
    cfg[section][key]["enabled"] = value
    save_config(cfg)
    print(f"{section}.{key} -> {'ON' if value else 'OFF'}")
    return True


def show_status(cfg):
    print("SUMBER")
    for k, v in cfg["sources"].items():
        print(f"  [{'x' if v.get('enabled') else ' '}] {k:<16} {v.get('label','')}")
    print("\nTOPIK")
    active = 0
    for k, v in cfg["topics"].items():
        on = v.get("enabled")
        active += 1 if on else 0
        kws = ", ".join(v.get("keywords", [])[:6])
        more = "" if len(v.get("keywords", [])) <= 6 else f" (+{len(v['keywords'])-6})"
        print(f"  [{'x' if on else ' '}] {k:<20} {kws}{more}")
    if active == 0:
        print("\n  -> semua topik OFF = TIDAK ada filter, semua berita diloloskan.")
    tickers = cfg["options"].get("tickers") or []
    print(f"\nTICKERS prioritas: {', '.join(tickers) if tickers else '(kosong)'}")
    print(f"Maks kirim/run   : {cfg['options'].get('max_per_run')}")
    print(f"\nFile config: {CONFIG_PATH}")


# ---------------------------------------------------------------- util

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr)


# IDX membatasi laju dan sesekali membalas 403 walau permintaannya identik dengan
# yang barusan berhasil. Jeda antar percobaan, dalam detik.
RETRY_DELAYS = (3, 8)
RETRY_CODES = {403, 429, 500, 502, 503, 504}


def fetch(url, timeout=30, json_mode=False, referer=None, label=""):
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*" if json_mode
                  else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, headers=headers)

    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            if attempt:
                log(f"{label}: berhasil pada percobaan ke-{attempt + 1}")
            for enc in ("utf-8", "iso-8859-1"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_CODES:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[attempt]
            log(f"{label}: {last} -- coba lagi dalam {delay}s")
            time.sleep(delay)
    raise last


def clean(text):
    text = TAG_RE.sub(" ", text or "")
    text = htmllib.unescape(text)
    return WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------- parsers

def parse_rss(page, label):
    items = []
    try:
        root = ET.fromstring(page.strip())
    except ET.ParseError as e:
        log(f"{label}: XML parse error: {e}")
        return items
    for node in root.iter():
        if node.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        title = link = pub = ""
        for child in node:
            ctag = child.tag.split("}")[-1].lower()
            if ctag == "title" and not title:
                title = clean(child.text or "")
            elif ctag == "link" and not link:
                link = (child.text or "").strip() or child.attrib.get("href", "").strip()
            elif ctag in ("pubdate", "published", "updated") and not pub:
                pub = (child.text or "").strip()
        if title and link:
            items.append({"title": title, "url": link.replace("http://", "https://"),
                          "published": pub, "source": label, "category": "", "tickers": []})
    return items


def parse_pasardana(page, label):
    """Judul ada di <h2> di dalam anchor; teks anchor penuh ikut membawa
    nomor urut, kategori, jam, dan nama penulis - jangan dipakai."""
    items = []
    for am in ANCHOR_RE.finditer(page):
        attrs, inner = am.group(1), am.group(2)
        m = HREF_RE.search(attrs)
        if not m:
            continue
        href = htmllib.unescape(m.group(1))
        if not PASARDANA_HREF_RE.match(href):
            continue
        h2 = H2_RE.search(inner)
        title = clean(h2.group(1)) if h2 else ""
        if len(title) < 10:
            title = href.rstrip("/").split("/")[-1].replace("-", " ").strip().capitalize()
        if len(title) < 10:
            continue
        t = TIME_RE.search(inner)
        s = SPAN_RE.search(inner)
        items.append({"title": title, "url": "https://pasardana.id" + href,
                      "published": clean(t.group(1)) if t else "",
                      "category": clean(s.group(1)) if s else "",
                      "source": label, "tickers": []})
    return items


def parse_idnfinancials(page, label):
    """Tiap artikel muncul 2x: anchor gambar (judul di atribut title=) dan
    anchor teks ("04 Sep 2026 06:00\\n\\nJudul")."""
    items, by_url = [], {}
    for am in ANCHOR_RE.finditer(page):
        attrs, inner = am.group(1), am.group(2)
        m = HREF_RE.search(attrs)
        if not m:
            continue
        url = htmllib.unescape(m.group(1))
        if not IDN_HREF_RE.match(url):
            continue
        ta = TITLE_ATTR_RE.search(attrs)
        title = htmllib.unescape(ta.group(1)).strip() if ta else ""
        published, text = "", clean(inner)
        dm = LEADING_DATE_RE.match(text)
        if dm:
            published = dm.group(0).strip()
            text = text[dm.end():].strip()
        if len(title) < 10:
            title = text
        if len(title) < 10:
            continue
        if url in by_url:
            if published and not by_url[url]["published"]:
                by_url[url]["published"] = published
            continue
        item = {"title": title, "url": url, "published": published,
                "category": "", "source": label, "tickers": []}
        by_url[url] = item
        items.append(item)
    return items


def parse_idx(page, label):
    """
    GetAllAnnouncement -> {"Items":[...]}, terurut menurun berdasarkan PublishDate.
    Tiap item: Title, Code (dipad spasi), PublishDate, Attachments[], Jenis, IsHidden.
    Tidak ada permalink HTML per pengumuman, jadi URL diambil dari PDF utama
    (attachment dengan IsAttachment = 0), fallback ke anchor Id.
    """
    items = []
    data = json.loads(page)
    for rec in data.get("Items") or []:
        if rec.get("IsHidden"):
            continue
        judul = (rec.get("Title") or "").strip()
        perihal = (rec.get("Perihal") or "").strip()
        kode = (rec.get("Code") or "").strip()
        tickers = [t.strip().upper() for t in re.split(r"[;,]", kode) if t.strip()]

        atts = rec.get("Attachments") or []
        def is_lampiran(a):
            return str(a.get("IsAttachment", 0)).strip().lower() in ("1", "true")
        main = next((a for a in atts if not is_lampiran(a)), None) or (atts[0] if atts else None)
        url = (main or {}).get("FullSavePath") or f"{IDX_PAGE}#{rec.get('Id', '')}"

        # Perihal hanya dipakai kalau jelas merupakan perpanjangan judul.
        body = judul or perihal or "Pengumuman IDX"
        if judul and perihal.lower().startswith(judul.lower()) and len(perihal) > len(judul):
            body = perihal
        title = (f"[{'/'.join(tickers)}] " if tickers else "") + body

        items.append({"title": title.strip(), "url": url,
                      "published": (rec.get("PublishDate") or "").replace("T", " "),
                      "category": rec.get("Jenis") or "", "source": label,
                      "tickers": tickers})

    # Catat ketertinggalan endpoint terhadap waktu sekarang, supaya regresi kesegaran
    # langsung terlihat di log tanpa perlu menyelidiki manual.
    stamps = [i["published"] for i in items if i["published"]]
    if stamps:
        try:
            newest = max(stamps)
            dt = datetime.strptime(newest, "%Y-%m-%d %H:%M:%S").replace(tzinfo=WIB)
            lag = (datetime.now(WIB) - dt).total_seconds() / 60
            tanda = "   <-- PERIKSA: endpoint tertinggal jauh" if lag > 90 else ""
            log(f"{label}: terbaru {newest} (tertinggal {lag:.0f} menit){tanda}")
        except ValueError:
            pass
    return items


# ---------------------------------------------------------------- sources

def source_requests(cfg):
    """[(source_key, label, kind, url, referer)] untuk sumber yang enabled."""
    src, opt, out = cfg["sources"], cfg["options"], []

    def on(k):
        return src.get(k, {}).get("enabled")

    if on("kontan_insight"):
        out.append(("kontan_insight", src["kontan_insight"]["label"], "rss",
                    "https://insight.kontan.co.id/rss", None))
    if on("kabarbursa"):
        out.append(("kabarbursa", src["kabarbursa"]["label"], "rss",
                    "https://www.kabarbursa.com/feed.xml", None))
    if on("idnfinancials"):
        out.append(("idnfinancials", src["idnfinancials"]["label"], "idnfinancials",
                    "https://www.idnfinancials.com/news", None))
    if on("pasardana"):
        now = datetime.now(WIB)
        for d in range(max(1, int(opt.get("pasardana_days", 2)))):
            day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
            out.append(("pasardana", src["pasardana"]["label"], "pasardana",
                        f"https://pasardana.id/news-index?date={day}", None))
    if on("idx_disclosure"):
        out.append(("idx_disclosure", src["idx_disclosure"]["label"], "idx",
                    IDX_API.format(size=int(opt.get("idx_page_size", 50))), IDX_PAGE))
    return out


PARSERS = {"rss": parse_rss, "pasardana": parse_pasardana,
           "idnfinancials": parse_idnfinancials, "idx": parse_idx}


def collect(cfg):
    all_items, counts = [], {}
    reqs = source_requests(cfg)
    if not reqs:
        log("Tidak ada sumber yang aktif. Cek 'python watch.py --list'.")
        return []
    for key, label, kind, url, referer in reqs:
        try:
            page = fetch(url, json_mode=(kind == "idx"), referer=referer, label=label)
        except Exception as e:
            log(f"{label}: GAGAL fetch ({e})")
            counts.setdefault(label, 0)
            continue
        try:
            items = PARSERS[kind](page, label)
        except Exception as e:
            log(f"{label}: GAGAL parse ({e})")
            counts.setdefault(label, 0)
            continue
        for it in items:
            it["src_key"] = key
        counts[label] = counts.get(label, 0) + len(items)
        all_items.extend(items)
    for label, n in counts.items():
        log(f"{label}: {n} item" + ("   <-- PERIKSA: 0 item" if n == 0 else ""))
    return all_items


# ---------------------------------------------------------------- filter

def match_topics(item, cfg):
    """Kembalikan daftar nama topik yang cocok. None = tidak ada filter aktif."""
    enabled = {k: v for k, v in cfg["topics"].items() if v.get("enabled")}
    tickers = [t.strip().upper() for t in (cfg["options"].get("tickers") or []) if t.strip()]
    hay = " ".join([item["title"], item.get("category", ""), item["url"]]).lower()
    hit_ticker = [t for t in tickers if t in item.get("tickers", []) or t.lower() in hay]
    if not enabled:
        # tidak ada topik aktif sama sekali -> tanpa filter
        return None if not hit_ticker else ["ticker:" + ",".join(hit_ticker)]
    allowed = cfg["sources"].get(item.get("src_key", ""), {}).get("topics") or []
    topics = {k: v for k, v in enabled.items() if not allowed or k in allowed}
    if not topics:
        # sumber dibatasi ke topik yang semuanya OFF -> hanya lolos lewat ticker
        return ["ticker:" + ",".join(hit_ticker)] if hit_ticker else []
    hits = [name for name, t in topics.items()
            if any(kw.lower() in hay for kw in t.get("keywords", []))]
    if hit_ticker:
        hits.append("ticker:" + ",".join(hit_ticker))
    return hits


def apply_filter(items, cfg):
    kept = []
    for it in items:
        hits = match_topics(it, cfg)
        if hits is None:          # tidak ada topik aktif -> semua lolos
            it["topics"] = []
            kept.append(it)
        elif hits:
            it["topics"] = hits
            kept.append(it)
    return kept


# ---------------------------------------------------------------- storage

def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS seen ("
                "url TEXT PRIMARY KEY, title TEXT, source TEXT, first_seen TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
    con.commit()
    return con


def get_state(con, key, default=None):
    row = con.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_state(con, key, value):
    con.execute("INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    con.commit()


def filter_new(con, items):
    fresh, seen_run = [], set()
    for it in items:
        if it["url"] in seen_run:
            continue
        seen_run.add(it["url"])
        if not con.execute("SELECT 1 FROM seen WHERE url = ?", (it["url"],)).fetchone():
            fresh.append(it)
    return fresh


def mark_seen(con, items):
    now = datetime.now(timezone.utc).isoformat()
    con.executemany("INSERT OR IGNORE INTO seen (url, title, source, first_seen) VALUES (?,?,?,?)",
                    [(i["url"], i["title"], i["source"], now) for i in items])
    con.commit()


# ---------------------------------------------------------------- telegram

def read_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_HOME_CHANNEL", "TELEGRAM_ALLOWED_USERS"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


# Telegram membatasi ~20 pesan/menit per chat dan 4096 karakter per pesan,
# jadi banyak item digabung ke dalam sedikit pesan, bukan satu pesan per item.
TG_MAX_CHARS = 3800


def format_item(it):
    title = it["title"]
    if len(title) > 300:
        title = title[:297] + "..."
    meta = it["source"] + (f" · {it['published']}" if it["published"] else "")
    if it.get("topics"):
        meta += " · " + ", ".join(it["topics"])
    return (f"\U0001F4C8 <b>{htmllib.escape(title)}</b>\n"
            f"<i>{htmllib.escape(meta)}</i>\n{it['url']}")


def build_chunks(items):
    """[(teks_pesan, jumlah_item)] - tiap pesan di bawah batas karakter Telegram."""
    chunks, cur, cur_len = [], [], 0
    for it in items:
        line = format_item(it)
        if cur and cur_len + len(line) + 2 > TG_MAX_CHARS:
            chunks.append(("\n\n".join(cur), len(cur)))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 2
    if cur:
        chunks.append(("\n\n".join(cur), len(cur)))
    return chunks


def tg_creds():
    env = read_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat = (env.get("TELEGRAM_HOME_CHANNEL")
            or env.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip())
    if not token or not chat:
        log("TELEGRAM_BOT_TOKEN / chat id belum diset di ~/.hermes/.env")
        return None, None
    return token, chat


def tg_post(token, chat, text):
    data = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                       # preview dimatikan: satu pesan bisa berisi banyak tautan
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def send_telegram(items, max_send):
    token, chat = tg_creds()
    if not token:
        return 0
    chunks = build_chunks(items[:max_send])
    sent = 0
    for i, (text, n) in enumerate(chunks):
        try:
            tg_post(token, chat, text)
            sent += n
        except Exception as e:
            log(f"Gagal kirim Telegram (pesan {i+1}/{len(chunks)}): {e}")
        if i < len(chunks) - 1:
            time.sleep(1.5)
    log(f"{sent} item terkirim dalam {len(chunks)} pesan")
    if len(items) > max_send:
        log(f"{len(items) - max_send} item lain ditahan (batas {max_send}/run)")
    return sent


def send_startup_notice(con, mode, cfg, watched):
    """
    mode:
      'always'= kirim tanpa syarat. Dipakai oleh hook systemd, supaya pesan terkirim
                tepat saat gateway menyala -- bukan menunggu tick cron berikutnya.
      'once'  = sekali seumur seen.db
      'daily' = sekali tiap hari kalender
      angka   = kirim bila jeda sejak run terakhir melebihi sekian menit.
                Dalam mode --no-agent tidak ada proses job yang hidup terus (tiap tick
                adalah proses baru), jadi "job menyala lagi" dideteksi dari jeda ini:
                gateway restart, WSL reboot, laptop tidur, atau jendela cron baru dibuka.
    """
    if not mode:
        return False
    today = datetime.now(WIB).strftime("%Y-%m-%d")
    prev = get_state(con, "startup_notice")
    alasan = ""

    if mode == "always":
        alasan = "gateway menyala"
    elif mode == "once":
        if prev:
            return False
        alasan = "pemasangan pertama"
    elif mode == "daily":
        if prev == today:
            return False
        alasan = "hari baru"
    else:
        try:
            gap_min = int(mode)
        except ValueError:
            log(f"--startup-notice '{mode}' tidak valid (pakai 'once', 'daily', atau angka menit)")
            return False
        last_run = float(get_state(con, "last_run_ts", 0) or 0)
        if not last_run:
            alasan = "pertama kali dijalankan"
        else:
            jeda = (time.time() - last_run) / 60
            if jeda < gap_min:
                return False
            alasan = (f"aktif kembali setelah jeda {jeda / 60:.1f} jam"
                      if jeda >= 90 else f"aktif kembali setelah jeda {jeda:.0f} menit")

    token, chat = tg_creds()
    if not token:
        return False
    aktif = [v.get("label", k) for k, v in cfg["sources"].items() if v.get("enabled")]
    topik = [k for k, v in cfg["topics"].items() if v.get("enabled")]
    jam = datetime.now(WIB).strftime("%H:%M")
    pantau = f"{watched} item dipantau · " if watched else ""
    text = (f"\u2705 <b>Radar saham aktif</b>\n"
            f"<i>{jam} WIB · {pantau}{htmllib.escape(alasan)}</i>\n\n"
            f"<b>Sumber</b> ({len(aktif)}): {htmllib.escape(', '.join(aktif)) or '-'}\n"
            f"<b>Topik</b> ({len(topik)}): {htmllib.escape(', '.join(topik)) or 'tanpa filter'}")
    try:
        tg_post(token, chat, text)
        set_state(con, "startup_notice", today)
        set_state(con, "last_message_ts", time.time())
        log(f"notice 'radar aktif' terkirim (mode {mode})")
        return True
    except Exception as e:
        log(f"Gagal kirim notice aktif: {e}")
        return False


def send_empty_notice(con, mode, watched):
    """mode: 'always' = tiap tick; angka = hanya bila sudah sekian menit hening."""
    if not mode:
        return False
    now = time.time()
    last = float(get_state(con, "last_message_ts", 0) or 0)
    if mode != "always":
        try:
            gap_min = int(mode)
        except ValueError:
            log(f"--empty-notice '{mode}' tidak valid (pakai 'always' atau angka menit)")
            return False
        quiet_min = (now - last) / 60
        if quiet_min < gap_min:
            log(f"notice dilewati: baru {quiet_min:.0f} menit hening (ambang {gap_min})")
            return False
    token, chat = tg_creds()
    if not token:
        return False
    jam = datetime.now(WIB).strftime("%H:%M")
    text = (f"\U0001F515 <i>Tidak ada berita baru</i>\n"
            f"<i>{jam} WIB · {watched} item dipantau</i>")
    try:
        tg_post(token, chat, text)
        set_state(con, "last_message_ts", now)
        log("notice 'tidak ada berita baru' terkirim")
        return True
    except Exception as e:
        log(f"Gagal kirim notice: {e}")
        return False


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="tampilkan status sumber & topik")
    ap.add_argument("--enable-source", metavar="KEY")
    ap.add_argument("--disable-source", metavar="KEY")
    ap.add_argument("--enable-topic", metavar="KEY")
    ap.add_argument("--disable-topic", metavar="KEY")
    ap.add_argument("--seed", action="store_true", help="tandai semua berita sekarang sbg sudah dibaca")
    ap.add_argument("--telegram", action="store_true", help="kirim langsung ke Telegram")
    ap.add_argument("--dry-run", action="store_true", help="jangan tulis ke database")
    ap.add_argument("--limit", type=int, default=None, help="maks item per run (default dari config)")
    ap.add_argument("--empty-notice", metavar="MODE", default=None,
                    help="kirim 'tidak ada berita baru' saat kosong: 'always' atau jumlah menit hening")
    ap.add_argument("--announce", action="store_true",
                    help="hanya kirim pesan 'radar saham aktif' lalu keluar (dipakai hook systemd)")
    ap.add_argument("--startup-notice", metavar="MODE", default=None,
                    help="kirim 'radar saham aktif': 'once', 'daily', atau jumlah menit jeda "
                         "yang dianggap sebagai job menyala lagi (mis. 15)")
    args = ap.parse_args()

    cfg = load_config()

    did_toggle = False
    for arg, section, val in ((args.enable_source, "sources", True),
                              (args.disable_source, "sources", False),
                              (args.enable_topic, "topics", True),
                              (args.disable_topic, "topics", False)):
        if arg:
            toggle(cfg, section, arg, val)
            did_toggle = True
    if did_toggle or args.list:
        if did_toggle:
            print()
        show_status(cfg)
        return 0

    if args.announce:
        con = db()
        ok = send_startup_notice(con, "always", cfg, watched=0)
        print(json.dumps({"announced": ok}, ensure_ascii=False))
        return 0

    limit = args.limit if args.limit is not None else int(cfg["options"].get("max_per_run", 15))

    items = collect(cfg)
    if not items:
        print(json.dumps({"new_count": 0, "items": [],
                          "error": "tidak ada item terkumpul (semua sumber gagal atau nonaktif)"},
                         ensure_ascii=False))
        return 1

    con = db()
    fresh = filter_new(con, items)
    relevant = apply_filter(fresh, cfg)

    if args.seed:
        mark_seen(con, items)
        log(f"Seed selesai: {len(items)} item ditandai sudah dibaca.")
        print(json.dumps({"seeded": len(items), "new_count": 0, "items": []}, ensure_ascii=False))
        return 0

    if not args.dry_run:
        mark_seen(con, items)   # semua ditandai, termasuk yang tersaring topik

    if args.telegram:
        # Diumumkan sebelum berita, supaya urutan di chat masuk akal saat run pertama.
        send_startup_notice(con, args.startup_notice, cfg, len(items))
        if relevant:
            sent = send_telegram(relevant, limit)
            if sent:
                set_state(con, "last_message_ts", time.time())
            print(json.dumps({"new_count": len(relevant), "sent": sent}, ensure_ascii=False))
        else:
            notice = send_empty_notice(con, args.empty_notice, len(items))
            print(json.dumps({"new_count": 0, "sent": 0, "notice": notice}, ensure_ascii=False))
        # Dicatat paling akhir: dipakai run berikutnya untuk mengukur jeda.
        set_state(con, "last_run_ts", time.time())
        return 0

    print(json.dumps({"new_count": len(relevant), "items": relevant[:limit]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
