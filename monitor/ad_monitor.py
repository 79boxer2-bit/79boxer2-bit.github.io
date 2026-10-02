# -*- coding: utf-8 -*-
"""
하늘공인중개사 - 네이버 부동산 광고 순위 감시

사무실 PC에서 30분마다(오전 10시~저녁 6시) 실행됩니다.
감시 단지의 네이버 매물을 '랭킹순'으로 읽어서, 우리 사무소 매물과 같은 매물을
다른 부동산이 더 위에(또는 더 최신 확인일자로) 올렸으면 카카오톡으로 알립니다.
재광고는 건당 비용이 들기 때문에 자동으로 누르지 않고, 알림만 보냅니다.

사용법 (명령 프롬프트에서):
  python ad_monitor.py              감시 1회 실행 (예약 작업이 이걸 실행)
  python ad_monitor.py test         모든 단지를 읽어서 단지명·매물 수 확인 (알림 안 보냄)
  python ad_monitor.py kakao-login  카카오톡 연결 (처음 한 번)
  python ad_monitor.py kakao-test   카카오톡 테스트 메시지
  python ad_monitor.py summary      오늘 요약을 지금 바로 보내기

표준 라이브러리만 사용합니다(추가 설치 없음). Python 3.10 이상.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
COMPLEX_TXT = os.path.join(HERE, "complexes.txt")
STATE_PATH = os.path.join(HERE, "state.json")
TOKEN_PATH = os.path.join(HERE, "kakao_token.json")
LOG_PATH = os.path.join(HERE, "monitor.log")
DEBUG_DIR = os.path.join(HERE, "debug")

KST = datetime.timezone(datetime.timedelta(hours=9))
LIST_URL = "https://m.land.naver.com/complex/getComplexArticleList"
ARTICLE_URL = "https://m.land.naver.com/article/info/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}
TRADE_CODES = {"매매": "A1", "전세": "B1", "월세": "B2", "단기임대": "B3"}


def now():
    return datetime.datetime.now(KST)


def log(msg):
    line = f"[{now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("cp949", "replace").decode("cp949"))
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


DEFAULT_CONFIG = {
    "my_office_names": ["하늘공인중개사"],
    "hours": [10, 18],
    "trade_types": ["매매", "전세", "월세"],
    "max_pages": 10,
    "max_alerts_per_day": 20,
    "source": "browser",
    "browser": "msedge",
    "show_browser": False,
    "complexes": [],
    "kakao": {"rest_api_key": "", "client_secret": "", "redirect_uri": "https://localhost"},
}


def load_complexes_txt():
    """complexes.txt: 한 줄에 '단지이름 네이버부동산주소'. # 으로 시작하는 줄은 설명."""
    out = []
    try:
        with open(COMPLEX_TXT, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:  # 메모장에서 ANSI 로 저장한 경우
        with open(COMPLEX_TXT, encoding="cp949", errors="replace") as f:
            lines = f.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"https?://\S+|\b\d{3,}\b", line)
        name = (line[:m.start()] if m else line).strip(" :=,\t") or "이름없음"
        out.append({"name": name, "url": m.group(0) if m else ""})
    return out


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        user = load_json(CONFIG_PATH, {})
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        bad = CONFIG_PATH.replace(".json", ".broken.json")
        os.replace(CONFIG_PATH, bad)
        log(f"config.json 형식이 깨져 있어 {os.path.basename(bad)} 로 옮기고 기본 설정을 씁니다. ({e})")
        user = {}
    for k, v in user.items():
        if k == "kakao" and isinstance(v, dict):
            cfg["kakao"].update(v)
        else:
            cfg[k] = v
    txt = load_complexes_txt()
    if txt is not None:
        cfg["complexes"] = txt
    if not cfg["complexes"]:
        sys.exit("감시할 단지가 없습니다. complexes.txt 에 '단지이름 네이버부동산주소' 를 한 줄에 하나씩 적어 주세요.")
    return cfg


# ---------------------------------------------------------------- 네이버 매물 읽기

_LZ_KEY = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"


def _lz_decompress(text):
    """네이버페이 부동산 지도 주소의 layer= 값(LZString 압축)을 푼다."""
    try:
        vals = [_LZ_KEY.index(c) for c in text.replace(" ", "+")]
    except ValueError:
        return ""
    st = {"pos": 32, "idx": 1, "val": vals[0] if vals else 0}

    def bits(n):
        r, p = 0, 1
        for _ in range(n):
            b = st["val"] & st["pos"]
            st["pos"] >>= 1
            if st["pos"] == 0:
                st["pos"] = 32
                st["val"] = vals[st["idx"]] if st["idx"] < len(vals) else 0
                st["idx"] += 1
            r |= (1 if b else 0) * p
            p <<= 1
        return r

    d, enl, size, nb = {0: 0, 1: 1, 2: 2}, 4, 4, 3
    n = bits(2)
    if n == 2 or not vals:
        return ""
    w = chr(bits(8 if n == 0 else 16))
    d[3] = w
    out = [w]
    while st["idx"] <= len(vals) + 1:
        c = bits(nb)
        if c in (0, 1):
            d[size] = chr(bits(8 if c == 0 else 16))
            size += 1
            c = size - 1
            enl -= 1
        elif c == 2:
            break
        if enl == 0:
            enl, nb = 2 ** nb, nb + 1
        if c in d:
            e = d[c]
        elif c == size:
            e = w + w[0]
        else:
            break
        out.append(e)
        d[size] = w + e[0]
        size += 1
        enl -= 1
        w = e
        if enl == 0:
            enl, nb = 2 ** nb, nb + 1
    return "".join(out)


def _lz_compress(text):
    """LZString.compressToEncodedURIComponent 와 같은 결과를 만든다."""
    bits_per_char = 6
    d, to_create, wc, w = {}, {}, "", ""
    enl, size, nb = 2, 3, 2
    out, val, pos = [], 0, 0

    def write(value, n):
        nonlocal val, pos
        for _ in range(n):
            val = (val << 1) | (value & 1)
            if pos == bits_per_char - 1:
                pos = 0
                out.append(_LZ_KEY[val])
                val = 0
            else:
                pos += 1
            value >>= 1

    def emit_w():
        nonlocal enl, nb
        if w in to_create:
            if ord(w[0]) < 256:
                write(0, nb)
                write(ord(w[0]), 8)
            else:
                write(1, nb)
                write(ord(w[0]), 16)
            enl -= 1
            if enl == 0:
                enl, nb = 2 ** nb, nb + 1
            del to_create[w]
        else:
            write(d[w], nb)
        enl -= 1
        if enl == 0:
            enl, nb = 2 ** nb, nb + 1

    for c in text:
        if c not in d:
            d[c] = size
            size += 1
            to_create[c] = True
        wc = w + c
        if wc in d:
            w = wc
        else:
            emit_w()
            d[wc] = size
            size += 1
            w = c
    if w:
        emit_w()
    write(2, nb)
    while True:
        val <<= 1
        if pos == bits_per_char - 1:
            out.append(_LZ_KEY[val])
            break
        pos += 1
    return "".join(out)


def article_tab_url(map_url, no):
    """사장님이 복사한 지도 주소(center/zoom 포함)를 그대로 쓰되, 단지 창을 매물 탭으로 바꾼다."""
    u = urllib.parse.urlparse(map_url)
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    layer = [{"id": "complex_detail", "params": {"complexId": int(no)}, "searchParams": {}, "returnable": True}]
    if q.get("layer"):
        try:
            layer = json.loads(_lz_decompress(q["layer"][0])) or layer
        except ValueError:
            pass
    for item in layer:
        if item.get("id") == "complex_detail":
            item.setdefault("searchParams", {}).update({"tab": "article", "articleTradeTypes": "A1-B1-B2"})
    q["layer"] = [_lz_compress(json.dumps(layer, separators=(",", ":"), ensure_ascii=False))]
    query = "&".join(f"{k}={urllib.parse.quote(v[0], safe='-$.')}" for k, v in q.items())
    return urllib.parse.urlunparse(u._replace(query=query))


def complex_map_url(no):
    """단지 매물 창이 열린 네이버페이 부동산 지도 주소."""
    layer = json.dumps([{"id": "complex_detail", "params": {"complexId": int(no)},
                         "searchParams": {"tab": "article", "articleTradeTypes": "A1-B1-B2"},
                         "returnable": True}], separators=(",", ":"), ensure_ascii=False)
    return ("https://fin.land.naver.com/map?tradeTypes=A1-B1-B2&realEstateTypes=A01-A04-B01&layer="
            + urllib.parse.quote(_lz_compress(layer), safe="-$"))


def complex_no(value):
    """단지 번호 또는 네이버 부동산 단지 주소(지도 주소 포함)에서 단지 번호만 뽑는다."""
    s = str(value)
    layer = urllib.parse.parse_qs(urllib.parse.urlparse(s).query).get("layer", [""])[0]
    if layer:
        m = re.search(r'"complexId"\s*:\s*"?(\d+)', _lz_decompress(layer))
        if m:
            return m.group(1)
    m = re.search(r"complex(?:es)?/(?:info/)?(\d+)", s) or re.search(r"hscpNo=(\d+)", s) or re.fullmatch(r"\s*(\d+)\s*", s)
    return m.group(1) if m else ""


def http_json(url, referer):
    req = urllib.request.Request(url, headers={**HEADERS, "Referer": referer})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body), body


def find_list(payload):
    """응답 JSON 어디에 목록이 있어도 찾아낸다(네이버 응답 구조 변경 대비)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("list", "articleList", "result", "body", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = find_list(v)
                if inner:
                    return inner
    return []


def fetch_complex(no, trade_types, max_pages, debug=False):
    """단지 매물을 네이버 '랭킹순'(기본 정렬) 그대로 가져온다. 순서가 곧 노출 순위."""
    trad = ":".join(TRADE_CODES[t] for t in trade_types if t in TRADE_CODES)
    referer = f"https://m.land.naver.com/complex/info/{no}"
    items = []
    for page in range(1, max_pages + 1):
        q = urllib.parse.urlencode({"hscpNo": no, "tradTpCd": trad, "order": "point_", "showR0": "N", "page": page})
        payload, raw = http_json(f"{LIST_URL}?{q}", referer)
        if debug:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            with open(os.path.join(DEBUG_DIR, f"{no}_p{page}.json"), "w", encoding="utf-8") as f:
                f.write(raw)
        got = find_list(payload)
        if not got:
            break
        items.extend(got)
        more = str((payload.get("result") or {}).get("moreDataYn", payload.get("more", ""))) if isinstance(payload, dict) else ""
        if more.upper() in ("N", "FALSE"):
            break
        time.sleep(1.2)
    return items


# ---------------------------------------------------------------- 네이버페이 부동산(브라우저로 읽기)
# 예전 모바일 주소가 매물을 주지 않아, 사무실 PC의 엣지로 단지 화면을 열고
# 화면이 받아오는 매물 데이터를 그대로 읽는다. 순서가 곧 화면 노출 순서.

FIN_URL = ""  # 비워 두면 지도 주소(complex_map_url)를 씀. 시험용으로만 바꿈
TRADE_NAMES = {"A1": "매매", "B1": "전세", "B2": "월세", "B3": "단기임대"}


def flatten(obj, prefix="", out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        if obj and all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix] = obj
    else:
        out[prefix] = obj
    return out


def pick(flat, *names, exclude=()):
    """평탄화된 키 중 끝 이름이 names 와 같은 값(대소문자 무시), 없으면 이름을 포함하는 값."""
    keys = list(flat)
    for n in names:
        for k in keys:
            last = k.rsplit(".", 1)[-1].lower()
            if last == n and flat[k] not in (None, "", [], 0, "0") and not any(e in k.lower() for e in exclude):
                return flat[k]
    for n in names:
        for k in keys:
            if n in k.lower() and flat[k] not in (None, "", [], 0, "0") and not any(e in k.lower() for e in exclude):
                return flat[k]
    return ""


ARTICLE_KEYS = ("articlenumber", "articleno", "atclno", "articleid")


def looks_like_article(d):
    if not isinstance(d, dict):
        return False
    keys = {k.lower() for k in flatten(d)}
    return any(k.rsplit(".", 1)[-1] in ARTICLE_KEYS for k in keys)


def article_lists(payload):
    """JSON 어디에 있든 매물 목록(매물번호가 있는 dict 들의 리스트)을 찾는다."""
    found = []
    if isinstance(payload, list):
        if payload and sum(looks_like_article(x) for x in payload) >= max(1, len(payload) // 2):
            found.append(payload)
        else:
            for x in payload:
                found += article_lists(x)
    elif isinstance(payload, dict):
        for v in payload.values():
            found += article_lists(v)
    return found


def won(v):
    """43000 (만원) -> '4억 3,000'. 숫자가 아니면 그대로."""
    t = str(v or "").replace(",", "").strip()
    if not t.isdigit():
        return str(v or "")
    n = int(t)
    if n >= 100000:  # 원 단위로 온 경우 (네이버페이 부동산은 원 단위)
        n //= 10000
    eok, man = divmod(n, 10000)
    return (f"{eok}억 {man:,}" if man else f"{eok}억") if eok else f"{man:,}"


def to_legacy(d):
    """네이버페이 부동산 매물 dict -> 기존 비교 로직이 쓰는 형식."""
    f = flatten(d)
    trade = str(pick(f, "tradetypename", "tradtpnm", "tradetype", "tradetypecode", "dealtype"))
    trade = TRADE_NAMES.get(trade, trade)
    floor = pick(f, "floorinfo", "flrinfo")
    if not floor:
        tf, tot = pick(f, "targetfloor", "floor", "correspondingfloor"), pick(f, "totalfloor", "totalfloorcount")
        floor = f"{tf}/{tot}" if tf else ""
    date = pick(f, "articleconfirmdate", "confirmdate", "atclcfmymd", "confirmymd", "cfmymd",
                "verificationdate", "exposurestartdate", "articleconfirmymd")
    if isinstance(date, (int, float)) and date > 1e11:  # 밀리초 타임스탬프
        date = datetime.datetime.fromtimestamp(date / 1000, KST).strftime("%Y%m%d")
    return {
        "atclNo": str(pick(f, *ARTICLE_KEYS)),
        "atclNm": str(pick(f, "complexname", "atclnm", "articlename")),
        "tradTpNm": trade,
        "bildNm": str(pick(f, "dongname", "buildingname", "bildnm", "buildingdong")),
        "flrInfo": str(floor),
        "spc2": str(pick(f, "exclusivespace", "exclusivearea", "spc2", "area2", "exclusiveareasize")),
        "prcInfo": won(pick(f, "dealprice", "warrantyprice", "prcinfo", "dealorwarrantprc", "price", exclude=("rent",))
                       if trade == "매매" else
                       pick(f, "warrantyprice", "deposit", "depositprice", "dealorwarrantprc", "prcinfo", "price", exclude=("rent", "deal"))),
        "rentPrc": won(pick(f, "rentprice", "rentprc", "monthlyrent")),
        "atclCfmYmd": str(date),
        "rltrNm": str(pick(f, "brokeragename", "realtorname", "rltrnm", "brokername", "agentname", "officename")),
        "dupCount": int(pick(f, "realtorcount") or 1),
    }


SCROLL_JS = """() => {
  let moved = 0;
  for (const el of document.querySelectorAll('*')) {
    if (el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 150) {
      const st = getComputedStyle(el).overflowY;
      if (st === 'auto' || st === 'scroll') { el.scrollTop = el.scrollHeight; moved++; }
    }
  }
  window.scrollTo(0, document.body.scrollHeight);
  return moved;
}"""


# 화면에서 매물 카드처럼 보이는 가장 안쪽 요소들(거래형태 + 면적/층 글자가 함께 있는 덩어리)
CARDS_JS = """() => {
  const ok = t => t && t.length < 600 && /(매매|전세|월세|단기임대)/.test(t) && /(㎡|m²|평|층)/.test(t);
  const all = [...document.querySelectorAll('li, a, article, div, button')].filter(el => ok(el.innerText));
  const leaf = all.filter(el => !all.some(o => o !== el && el.contains(o)));
  return leaf.map(el => {
    const a = el.closest('a[href]') || el.querySelector('a[href]');
    return { text: el.innerText.trim(), href: a ? a.href : '' };
  });
}"""

CARD_RE = {
    "trade": re.compile(r"(매매|전세|월세|단기임대)\s*(\d+억(?:\s?\d{1,3}(?:,\d{3})*)?|\d{1,3}(?:,\d{3})+|\d+)(?:\s*/\s*(\d{1,3}(?:,\d{3})+|\d+))?"),
    "dong": re.compile(r"(\d{2,4})\s*동"),
    "floor": re.compile(r"([저중고]|\d{1,3})\s*/\s*(\d{1,3})\s*층"),
    "area2": re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(?:㎡|m²)"),
    "area1": re.compile(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²)"),
    "date": re.compile(r"(\d{2,4})\.(\d{1,2})\.(\d{1,2})\.?"),
    "realtor": re.compile(r"([가-힣A-Za-z0-9&]+(?:공인중개사(?:사무소)?|부동산(?:중개)?(?:사무소)?|중개법인|중개사무소))"),
    "no": re.compile(r"(\d{9,11})"),
}


def card_to_legacy(card, my_names):
    t = card.get("text", "")
    one = " ".join(t.split())
    m = CARD_RE["trade"].search(one)
    trade, price, rent = (m.group(1), m.group(2).strip(), (m.group(3) or "")) if m else ("", "", "")
    if trade not in ("월세", "단기임대"):
        rent = ""
    fl = CARD_RE["floor"].search(one)
    ar = CARD_RE["area2"].search(one)
    area = ar.group(2) if ar else (CARD_RE["area1"].search(one).group(1) if CARD_RE["area1"].search(one) else "")
    dates = CARD_RE["date"].findall(one)
    date = "".join(f"{int(y) % 100:02d}{int(mo):02d}{int(d):02d}" for y, mo, d in dates[-1:])
    realtor = next((n for n in my_names if n and n[:2] in one), "")
    if not realtor:
        r = CARD_RE["realtor"].search(one)
        realtor = r.group(1) if r else ""
    dn = CARD_RE["dong"].search(one)
    no = CARD_RE["no"].search(card.get("href", "")) or None
    return {
        "atclNo": no.group(1) if no else "h" + hashlib.md5(one.encode("utf-8")).hexdigest()[:12],
        "atclNm": "",
        "tradTpNm": trade,
        "bildNm": dn.group(1) if dn else "",
        "flrInfo": f"{fl.group(1)}/{fl.group(2)}" if fl else "",
        "spc2": area,
        "prcInfo": price,
        "rentPrc": rent,
        "atclCfmYmd": date,
        "rltrNm": realtor,
    }


# '중개사 N곳에서 등록했어요' 버튼 중, 대표 광고가 우리 것이 아닌 묶음에만 표시를 붙인다
DUP_JS = """(names) => {
  const isBtn = el => /중개사\\s*\\d+\\s*곳/.test(el.innerText || '') && (el.innerText || '').length < 40;
  const all = [...document.querySelectorAll('button, a, div, span, p')].filter(isBtn);
  const leaf = all.filter(el => !all.some(o => o !== el && el.contains(o)));
  let n = 0;
  for (const el of leaf) {
    let card = el, ok = false;
    for (let i = 0; i < 8 && card; i++) {
      card = card.parentElement;
      if (card && /(매매|전세|월세)/.test(card.innerText) && /(㎡|층)/.test(card.innerText)) { ok = true; break; }
    }
    if (!ok) continue;
    if (names.some(nm => nm && card.innerText.includes(nm))) continue;
    el.setAttribute('data-hn-dup', String(n++));
  }
  return n;
}"""


class BrowserReader:
    def __init__(self, cfg, debug=False):
        self.cfg, self.debug = cfg, debug

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("브라우저 모듈이 없습니다. setup.bat 을 다시 실행해 주세요. (pip install playwright)")
        self._pw = sync_playwright().start()
        opts = dict(user_data_dir=os.path.join(HERE, "browser_profile"),
                    headless=bool(self.cfg.get("headless", False)),
                    args=[] if self.cfg.get("show_browser") or self.debug else ["--window-position=-32000,-32000"],
                    viewport={"width": 1400, "height": 1000}, locale="ko-KR")
        last = None
        tries = [{"executable_path": self.cfg["browser_path"]}] if self.cfg.get("browser_path") else []
        tries += [{"channel": self.cfg.get("browser", "msedge")}, {"channel": "chrome"}]
        for extra in tries:
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    **extra, **opts, ignore_default_args=["--enable-automation"] + (["--no-sandbox"] if os.name == "nt" else []))
                self.ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                break
            except Exception as e:
                last = e
        else:
            self._pw.stop()
            raise RuntimeError(f"엣지/크롬 브라우저를 열 수 없습니다: {last}")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *a):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    def fetch(self, no, trade_types, page_url=""):
        caught, seq = [], [0]
        self.last_groups = None

        def on_response(resp):
            try:
                if "json" not in (resp.headers.get("content-type") or ""):
                    return
                data = resp.json()
            except Exception:
                return
            lists = article_lists(data)
            if self.debug:
                seq[0] += 1
                os.makedirs(DEBUG_DIR, exist_ok=True)
                with open(os.path.join(DEBUG_DIR, f"{no}_{seq[0]:02d}_{'list' if lists else 'etc'}.json"), "w", encoding="utf-8") as fp:
                    json.dump({"url": resp.url, "data": data}, fp, ensure_ascii=False, indent=1)
            caught.extend(lists)

        if "{no}" in FIN_URL:
            url = FIN_URL.format(no=no)
        elif "fin.land.naver.com/map" in (page_url or ""):
            url = article_tab_url(page_url, no)
        else:
            url = complex_map_url(no)
        self.page.on("response", on_response)
        cards = []
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            self.page.wait_for_timeout(5000)
            if "404" in self.page.url:
                log(f"   네이버가 '페이지 없음'으로 보냈습니다. complexes.txt 에 이 단지의 네이버 지도 주소를 통째로 넣어 주세요.")
            # 매물 탭이 닫혀 있으면 눌러 본다
            if not self.page.evaluate(CARDS_JS):
                for label in ("매물", "단지 매물"):
                    try:
                        self.page.get_by_text(label, exact=True).first.click(timeout=3000)
                        self.page.wait_for_timeout(3000)
                        break
                    except Exception:
                        pass
            last = (-1, -1)
            for _ in range(self.cfg.get("max_pages", 10)):
                cards = self.page.evaluate(CARDS_JS)
                now_cnt = (sum(len(x) for x in caught), len(cards))
                if now_cnt == last:
                    break
                last = now_cnt
                self.page.evaluate(SCROLL_JS)
                self.page.wait_for_timeout(2500)
            cards = self.page.evaluate(CARDS_JS)
            main_n = len(caught)
            self.last_groups = None
            if self.cfg.get("expand_groups", True) and "{no}" not in FIN_URL:
                self.last_groups = []
                names = [x[:4] for x in self.cfg.get("my_office_names", []) if x]
                n_dup = self.page.evaluate(DUP_JS, names)
                for i in range(n_dup):
                    before = len(caught)
                    try:
                        el = self.page.locator(f'[data-hn-dup="{i}"]').first
                        el.scroll_into_view_if_needed(timeout=3000)
                        el.click(timeout=3000)
                        self.page.wait_for_timeout(1500)
                    except Exception:
                        continue
                    got = [d for lst in caught[before:] for d in lst]
                    if got:
                        self.last_groups.append([to_legacy(d) for d in got])
                        if self.debug and len(self.last_groups) == 1:
                            os.makedirs(DEBUG_DIR, exist_ok=True)
                            with open(os.path.join(DEBUG_DIR, f"{no}_group_fields.txt"), "w", encoding="utf-8") as fp:
                                for d in got[:4]:
                                    for k, v in flatten(d).items():
                                        fp.write(f"{k} = {str(v)[:60]}\n")
                                    fp.write("\n" + "-" * 40 + "\n\n")
                log(f"   (다른 부동산이 대표인 묶음 {n_dup}개 펼침, 읽은 묶음 {len(self.last_groups)}개)")
                if n_dup and not self.last_groups:
                    self.last_groups = None  # 펼친 내용을 못 읽으면 예비 방식으로
            caught = caught[:main_n]
            if self.debug:
                os.makedirs(DEBUG_DIR, exist_ok=True)
                self.page.screenshot(path=os.path.join(DEBUG_DIR, f"{no}_screen.png"))
                with open(os.path.join(DEBUG_DIR, f"{no}_page.txt"), "w", encoding="utf-8") as fp:
                    fp.write(url + "\n\n=== 매물 카드 ===\n")
                    for c in cards:
                        fp.write(c["text"].replace("\n", " | ") + "  <" + (c.get("href") or "") + ">\n")
                    fp.write("\n=== 화면 전체 글자 ===\n" + self.page.evaluate("() => document.body.innerText")[:20000])
        finally:
            self.page.remove_listener("response", on_response)

        items, seen_no = [], set()
        for lst in caught:
            for d in lst:
                a = to_legacy(d)
                if a["atclNo"] and a["atclNo"] not in seen_no:
                    seen_no.add(a["atclNo"])
                    items.append(a)
        if self.debug and caught:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            with open(os.path.join(DEBUG_DIR, f"{no}_fields.txt"), "w", encoding="utf-8") as fp:
                fp.write("네이버 매물 데이터 항목 (앞 매물 3건)\n\n")
                for d in [x for lst in caught for x in lst][:3]:
                    for k, v in flatten(d).items():
                        fp.write(f"{k} = {str(v)[:60]}\n")
                    fp.write("\n" + "-" * 40 + "\n\n")
        source = "데이터"
        if not items and cards:  # 데이터 형식을 못 알아보면 화면 글자로 읽는다
            source = "화면글자"
            for c in cards:
                a = card_to_legacy(c, self.cfg.get("my_office_names", []))
                if a["atclNo"] not in seen_no:
                    seen_no.add(a["atclNo"])
                    items.append(a)
        log(f"   ({source}에서 {len(items)}건 읽음, 화면 카드 {len(cards)}개)")
        want = set(trade_types)
        return [a for a in items if not a["tradTpNm"] or a["tradTpNm"] in want]


# ---------------------------------------------------------------- 같은 매물 판단

def parse_date(s):
    """'26.07.18.' / '2026.07.18' / '20260718' -> date"""
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) == 6:
        d = "20" + d
    try:
        return datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    except (ValueError, IndexError):
        return None


def floor_parts(flr):
    """'5/25' -> (5, 25, '저') / '고/25' -> (None, 25, '고')"""
    a, _, b = str(flr or "").partition("/")
    total = int(b) if b.strip().isdigit() else None
    if a.strip().isdigit():
        n = int(a)
        band = None
        if total:
            band = "저" if n <= total / 3 else ("중" if n <= total * 2 / 3 else "고")
        return n, total, band
    band = a.strip()[:1] if a.strip()[:1] in ("저", "중", "고") else None
    return None, total, band


def norm(a, complex_name, rank):
    dong = re.sub(r"\D", "", str(a.get("bildNm", "")))
    fl, total, band = floor_parts(a.get("flrInfo"))
    try:
        area = float(a.get("spc2") or 0)
    except ValueError:
        area = 0.0
    price = str(a.get("prcInfo", "")).strip()
    if a.get("rentPrc"):
        price = f"{price}/{a.get('rentPrc')}"
    return {
        "no": str(a.get("atclNo", "")),
        "complex": complex_name,
        "rank": rank,
        "trade": a.get("tradTpNm", ""),
        "dong": dong,
        "floor": fl, "total": total, "band": band,
        "area": area,
        "price": price,
        "date": parse_date(a.get("atclCfmYmd") or a.get("cfmYmd")),
        "realtor": str(a.get("rltrNm") or a.get("realtorName") or ""),
        "flr_text": str(a.get("flrInfo", "")),
    }


def same_listing(me, other, strict=False):
    """같은 동·거래·전용면적이고 층이 같으면 같은 집.
    strict=True(경쟁 광고와 비교할 때): 층 숫자가 둘 다 있고 정확히 같아야 함.
    (같은 동·같은 층대·같은 호가인 다른 호수가 흔해서 저/중/고 층대만으로는 묶지 않음)"""
    if me["trade"] != other["trade"] or not me["dong"] or me["dong"] != other["dong"]:
        return False
    if abs(me["area"] - other["area"]) > 1.0:
        return False
    if me["floor"] is not None and other["floor"] is not None:
        return me["floor"] == other["floor"]
    if strict:
        return False
    return me["band"] is not None and me["band"] == other["band"] and me["price"] == other["price"]


def is_mine(a, names):
    return any(n and n in a["realtor"] for n in names)


# ---------------------------------------------------------------- 카카오톡

def kakao_post(url, data, token=None):
    headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"카카오 오류 {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


def kakao_token_request(cfg, extra):
    k = cfg["kakao"]
    data = {"client_id": k["rest_api_key"], **extra}
    if k.get("client_secret"):
        data["client_secret"] = k["client_secret"]
    return kakao_post("https://kauth.kakao.com/oauth/token", data)


def kakao_access_token(cfg):
    tok = load_json(TOKEN_PATH, None)
    if not tok:
        raise RuntimeError("카카오톡이 연결되지 않았습니다. 'python ad_monitor.py kakao-login' 을 먼저 실행하세요.")
    if time.time() < tok.get("access_expires_at", 0) - 300:
        return tok["access_token"]
    res = kakao_token_request(cfg, {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    tok["access_token"] = res["access_token"]
    tok["access_expires_at"] = time.time() + int(res.get("expires_in", 21599))
    if res.get("refresh_token"):  # 만료 1개월 이내일 때만 새로 내려옴
        tok["refresh_token"] = res["refresh_token"]
        tok["refresh_expires_at"] = time.time() + int(res.get("refresh_token_expires_in", 0))
    save_json(TOKEN_PATH, tok)
    return tok["access_token"]


def send_kakao(cfg, text, link=""):
    """카카오톡 '나에게 보내기'. 본문은 200자까지만 보이므로 잘라서 보낸다."""
    chunks = []
    while text:
        cut = text[:200]
        if len(text) > 200 and "\n" in cut:
            cut = cut[:cut.rfind("\n")]
        chunks.append(cut)
        text = text[len(cut):].lstrip("\n")
    token = kakao_access_token(cfg)
    for i, chunk in enumerate(chunks):
        url = link or "https://m.land.naver.com"
        tpl = {"object_type": "text", "text": chunk, "link": {"web_url": url, "mobile_web_url": url}}
        if link and i == 0:
            tpl["button_title"] = "매물 보기"
        kakao_post("https://kapi.kakao.com/v2/api/talk/memo/default/send", {"template_object": json.dumps(tpl, ensure_ascii=False)}, token)


def send_ntfy(cfg, text, link=""):
    """휴대폰 ntfy 앱으로 알림 (가입·키 없이 주제 이름만 맞추면 됨)."""
    title, _, body = text.partition("\n")
    payload = {"topic": cfg["ntfy_topic"], "title": title, "message": body or title, "tags": ["house"]}
    if link:
        payload["click"] = link
    req = urllib.request.Request(cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/") + "/",
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()


def notify(cfg, text, link="", dry=False):
    log("알림: " + text.replace("\n", " | "))
    if dry:
        return
    sent = False
    if cfg.get("ntfy_topic"):
        try:
            send_ntfy(cfg, text, link)
            sent = True
        except Exception as e:
            log(f"휴대폰(ntfy) 알림 실패: {e}")
    if os.path.exists(TOKEN_PATH):
        try:
            send_kakao(cfg, text, link)
            sent = True
        except Exception as e:
            log(f"카카오톡 전송 실패: {e}")
    if not sent:
        log("알림 수단이 연결되지 않아 기록만 했습니다. phone_setup.bat 을 실행해 휴대폰 알림을 연결하세요.")


def phone_setup(cfg):
    """휴대폰 알림 주제 이름을 만들고 안내한 뒤 테스트 알림을 보낸다."""
    import secrets
    try:
        user = load_json(CONFIG_PATH, {})
    except (json.JSONDecodeError, UnicodeDecodeError):
        user = {}
    topic = user.get("ntfy_topic") or "haneul-" + secrets.token_hex(5)
    user["ntfy_topic"] = cfg["ntfy_topic"] = topic
    save_json(CONFIG_PATH, user)
    print("=" * 56)
    print("  휴대폰 알림 연결")
    print("=" * 56)
    print("\n1) 휴대폰에서 앱을 설치하세요.")
    print("   - 안드로이드: Play 스토어에서 'ntfy' 검색 → 설치")
    print("   - 아이폰: App Store에서 'ntfy' 검색 → 설치")
    print("\n2) 앱을 열고 오른쪽 아래 [+] 를 누른 뒤, 주제(Topic) 칸에 아래 이름을 똑같이 입력하고 [구독/Subscribe]:")
    print("\n        " + topic + "\n")
    print("   (이 이름을 아는 사람만 알림을 볼 수 있으니 다른 사람에게 알려 주지 마세요)")
    input("\n3) 구독을 마쳤으면 Enter 를 누르세요. 테스트 알림을 보냅니다...")
    send_ntfy(cfg, "[하늘공인중개사] 광고 감시 알림 연결 완료\n오전 10시~저녁 6시에 광고가 밀리면 이 앱으로 알려 드립니다.")
    print("\n휴대폰에 알림이 왔으면 완료입니다. 안 왔으면 주제 이름 철자를 다시 확인하세요.")


def kakao_login(cfg):
    k = cfg.get("kakao") or {}
    if not k.get("rest_api_key"):
        sys.exit("config.json 의 kakao.rest_api_key 를 먼저 입력하세요. (README 3단계)")
    redirect = k.get("redirect_uri", "https://localhost")
    url = "https://kauth.kakao.com/oauth/authorize?" + urllib.parse.urlencode(
        {"client_id": k["rest_api_key"], "redirect_uri": redirect, "response_type": "code", "scope": "talk_message"})
    print("브라우저에서 카카오 로그인·동의를 진행합니다.")
    print("동의 후 '사이트에 연결할 수 없음' 화면이 나오면 정상입니다. 그때 주소창의 주소 전체를 복사해서 아래에 붙여 넣으세요.\n")
    webbrowser.open(url)
    print(url + "\n")
    back = input("주소 붙여넣기: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(back).query).get("code", [back])[0]
    res = kakao_token_request(cfg, {"grant_type": "authorization_code", "redirect_uri": redirect, "code": code})
    save_json(TOKEN_PATH, {
        "access_token": res["access_token"],
        "access_expires_at": time.time() + int(res.get("expires_in", 21599)),
        "refresh_token": res["refresh_token"],
        "refresh_expires_at": time.time() + int(res.get("refresh_token_expires_in", 0)),
    })
    print("카카오톡 연결 완료.")


def kakao_setup(cfg):
    """REST API 키 입력 → 카카오 로그인 → 테스트 메시지까지 한 번에."""
    print("=" * 50)
    print("  카카오톡 알림 연결")
    print("=" * 50)
    k = cfg.setdefault("kakao", {})
    cur = k.get("rest_api_key", "")
    key = input(f"\n1) 카카오 앱의 REST API 키를 붙여 넣고 Enter{' (그대로 쓰려면 그냥 Enter)' if cur else ''}: ").strip() or cur
    if not key:
        sys.exit("REST API 키가 필요합니다.")
    secret = input("2) 클라이언트 시크릿(Client Secret)을 켜 두셨으면 그 값을, 아니면 그냥 Enter: ").strip()
    k.update({"rest_api_key": key, "redirect_uri": k.get("redirect_uri") or "https://localhost"})
    if secret:
        k["client_secret"] = secret
    try:
        user = load_json(CONFIG_PATH, {})
    except (json.JSONDecodeError, UnicodeDecodeError):
        user = {}
    user.setdefault("kakao", {}).update({kk: v for kk, v in k.items() if v})
    save_json(CONFIG_PATH, user)
    print("\n3) 브라우저가 열리면 카카오 로그인 → '동의하고 계속하기' 를 누르세요.")
    kakao_login(cfg)
    send_kakao(cfg, "[하늘공인중개사] 광고 감시 알림이 연결됐습니다.\n오전 10시~저녁 6시에 광고가 밀리면 여기로 알려 드립니다.")
    print("\n완료! 카카오톡 '나와의 채팅'에 테스트 메시지가 왔는지 확인하세요.")


# ---------------------------------------------------------------- 감시

def in_hours(cfg, t):
    start, end = cfg.get("hours", [10, 18])
    return start <= t.hour < end or (t.hour == end and t.minute < 15)


def check(cfg, state, dry=False, only_first=False):
    names = cfg.get("my_office_names", ["하늘"])
    trades = cfg.get("trade_types", ["매매", "전세", "월세"])
    today = now().date().isoformat()
    day = state.setdefault("days", {}).setdefault(today, {"alerts": 0, "readded": [], "behind": {}})
    alerted = state.setdefault("alerted", {})
    my_dates = state.setdefault("my_dates", {})
    new_alerts = 0

    complexes = cfg["complexes"]
    reader = None
    if cfg.get("source", "browser") == "browser":
        try:
            reader = BrowserReader(cfg, debug=only_first).__enter__()
        except Exception as e:
            log(f"브라우저 시작 실패: {e}")
            return 0
    out = {"behind": [], "readded": []}
    try:
        n = _check_complexes(cfg, state, complexes, reader, names, trades, today, day, alerted, my_dates, dry, only_first, out)
    finally:
        if reader:
            reader.__exit__()
    send_digest(cfg, out, dry)
    return n


def short_realtor(name):
    """'시티프라디움공인중개사사무소' -> '시티프라디움'"""
    t = re.sub(r"(공인중개사사무소|공인중개사|중개사무소|부동산중개|사무소)$", "", str(name or "").strip())
    return t or str(name or "")


def send_digest(cfg, out, dry=False):
    """이번 점검 결과를 카톡 한 통(길면 200자씩 나눠서)으로 보낸다."""
    lines = []
    if out["behind"]:
        lines.append(f"[광고 밀림 {len(out['behind'])}건] {now():%m/%d %H:%M}")
        for i, b in enumerate(out["behind"], 1):
            lines.append(f"{i}) {b['where']}")
            lines.append(f"   {b['price']} · {b['rival']} {b['rival_date']} (우리 {b['my_date']})")
        lines.append("→ 이실장 재광고 검토")
    if out["readded"]:
        if lines:
            lines.append("")
        lines.append(f"[재광고 확인 {len(out['readded'])}건] 직방도 갱신하세요")
        for r in out["readded"]:
            lines.append(f"- {r}")
    if lines:
        notify(cfg, "\n".join(lines), "https://fin.land.naver.com", dry)


def _check_complexes(cfg, state, complexes, reader, names, trades, today, day, alerted, my_dates, dry, only_first, out):
    new_alerts = 0
    for c in complexes:
        no = complex_no(c.get("url") or c.get("no"))
        name = c.get("name", no)
        if not no:
            log(f"[{name}] 단지 번호가 없습니다. complexes.txt 에 네이버 부동산 단지 주소를 넣어 주세요.")
            continue
        try:
            raw = reader.fetch(no, trades, c.get("url", "")) if reader else fetch_complex(no, trades, cfg.get("max_pages", 10), debug=only_first)
        except Exception as e:
            log(f"[{name}] 네이버 읽기 실패: {e}")
            continue
        arts = [norm(a, name, i + 1) for i, a in enumerate(raw)]
        mine = [a for a in arts if is_mine(a, names)]
        naver_name = next((str(a.get("atclNm") or "") for a in raw if a.get("atclNm")), "")
        log(f"[{name}] 네이버 단지명: {naver_name or '확인 불가'} · 매물 {len(arts)}건, 우리 매물 {len(mine)}건")
        if only_first:
            for a in arts[:5]:
                log(f"   {a['rank']:>3}위 {a['trade']} {a['dong']}동 {a['flr_text']} {a['area']}㎡ {a['price']} {a['date']} {a['realtor']}")

        def handle(g, top):
            """g: 같은 집에 대한 우리 광고들, top: 우리보다 위에 보이는 다른 부동산 광고(없으면 None)"""
            nonlocal new_alerts
            me = g[0]
            latest = max((x["date"] for x in g if x["date"]), default=None)
            gkey = f"{name}|{me['trade']}|{me['dong']}|{me['floor'] or me['band']}|{me['area']:.0f}"
            # 재광고 감지: 같은 매물의 우리 최신 확인일자가 올라가면 직방 갱신 알림
            prev = my_dates.get(gkey)
            if latest and prev and latest.isoformat() > prev:
                day["readded"].append(gkey)
                out["readded"].append(f"{name} {me['dong']}동 {me['flr_text']} {me['trade']} {me['price']}")
            if latest:
                my_dates[gkey] = latest.isoformat()
            if top is None:
                day["behind"].pop(gkey, None)
                return
            d_me = f"{latest:%m/%d}" if latest else "?"
            d_top = f"{top['date']:%m/%d}" if top["date"] else "?"
            day["behind"][gkey] = f"{name} {me['dong']}동 {me['flr_text']} {me['trade']} {me['price']} ({short_realtor(top['realtor'])} {d_top} > 우리 {d_me})"
            # 같은 경쟁 광고·같은 확인일자로는 한 번만 알림 (비용 드는 재광고를 부추기지 않도록)
            akey = f"{gkey}>{top['no']}@{top['date']}"
            if akey in alerted or day["alerts"] >= cfg.get("max_alerts_per_day", 20):
                return
            alerted[akey] = today
            day["alerts"] += 1
            new_alerts += 1
            out["behind"].append({
                "where": f"{name} {me['dong']}동 {me['flr_text']}",
                "price": f"{me['trade']} {me['price']}",
                "rival": short_realtor(top["realtor"]), "rival_date": d_top, "my_date": d_me,
            })
            log(f"   밀림: {name} {me['dong']}동 {me['flr_text']} {me['trade']} {me['price']} - {top['realtor']} {d_top} / 우리 {d_me} (우리 광고 {len(g)}건)")

        naver_groups = getattr(reader, "last_groups", None) if reader else None
        if naver_groups is not None:
            # 네이버가 묶어 둔 '같은 집' 묶음 기준: 우리 광고가 들어 있는데 대표(맨 위)가 다른 부동산이면 밀림
            done = set()
            for gm in naver_groups:
                members = [norm(x, name, 0) for x in gm]
                ours = [x for x in members if is_mine(x, names)]
                if not ours:
                    continue
                nos = {x["no"] for x in members}
                rep = next((x for x in arts if x["no"] in nos), None)
                if rep is None:
                    others = [x for x in members if not is_mine(x, names)]
                    rep = max(others, key=lambda o: o["date"] or datetime.date.min) if others else None
                if rep is not None and is_mine(rep, names):
                    rep = None
                handle(sorted(ours, key=lambda x: x["date"] or datetime.date.min, reverse=True), rep)
                done |= {x["no"] for x in ours}
            for m in mine:  # 우리가 대표인 묶음 = 밀리지 않음 (재광고 기록만)
                if m["no"] not in done:
                    handle([m], None)
        else:
            # 예비 방식: 층·면적·가격으로 같은 집을 추정
            groups = []
            for m in sorted(mine, key=lambda x: x["rank"]):
                for g in groups:
                    if same_listing(g[0], m) or same_listing(m, g[0]):
                        g.append(m)
                        break
                else:
                    groups.append([m])
            strict = not cfg.get("loose_floor_match", False)
            for g in groups:
                latest = max((x["date"] for x in g if x["date"]), default=None)
                rivals = [o for o in arts if not is_mine(o, names) and any(same_listing(x, o, strict) for x in g)]
                newer = [o for o in rivals if o["date"] and latest and o["date"] > latest]
                handle(g, max(newer, key=lambda o: (o["date"], -o["rank"])) if newer else None)
        time.sleep(2)

    # 30일 지난 기록 정리
    cutoff = (now().date() - datetime.timedelta(days=30)).isoformat()
    state["alerted"] = {k: v for k, v in alerted.items() if v >= cutoff}
    state["days"] = {k: v for k, v in state["days"].items() if k >= cutoff}
    return new_alerts


def summary(cfg, state, dry=False):
    today = now().date().isoformat()
    day = state.get("days", {}).get(today, {"alerts": 0, "readded": [], "behind": {}})
    behind = list(day.get("behind", {}).values())
    lines = [f"[오늘 요약 {now():%m/%d}] 알림 {day.get('alerts', 0)} · 재광고 {len(day.get('readded', []))} · 아직 밀림 {len(behind)}"]
    lines += [f"- {b}" for b in behind[:10]]
    if len(behind) > 10:
        lines.append(f"외 {len(behind) - 10}건")
    if day.get("readded"):
        lines.append("※ 오늘 재광고한 매물은 직방도 갱신했는지 확인하세요")
    notify(cfg, "\n".join(lines), dry=dry)
    state.setdefault("summary_sent", {})[today] = True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    cfg = load_config()
    if cmd == "phone-setup":
        try:
            return phone_setup(cfg)
        except Exception as e:
            sys.exit(f"\n연결 실패: {e}\n화면을 캡처해서 보내 주세요.")
    if cmd == "kakao-setup":
        try:
            return kakao_setup(cfg)
        except Exception as e:
            sys.exit(f"\n연결 실패: {e}\n화면을 캡처해서 보내 주세요.")
    if cmd == "kakao-login":
        return kakao_login(cfg)
    if cmd == "kakao-test":
        send_kakao(cfg, "하늘공인중개사 광고 감시 연결 테스트입니다.")
        return print("보냈습니다. 카카오톡 '나와의 채팅'을 확인하세요.")

    state = load_json(STATE_PATH, {})
    if cmd == "test":
        log("=== 테스트: 모든 단지를 읽습니다 (알림 안 보냄, debug 폴더에 원본 저장) ===")
        check(cfg, state, dry=True, only_first=True)
        return
    if cmd == "preview":
        # 지금 밀린 매물 전체를 새 형식으로 미리 보내기 (보낸 기록은 남기지 않음)
        log("=== 지금 점검(미리보기): 오늘 보낸 알림과 상관없이 현재 밀린 매물을 모두 보냅니다 ===")
        n = check(cfg, {}, dry=False)
        if n == 0:
            notify(cfg, f"[지금 점검 {now():%m/%d %H:%M}]\n밀린 매물이 없습니다.")
        return
    if cmd == "summary":
        summary(cfg, state)
        return save_json(STATE_PATH, state)

    t = now()
    if not in_hours(cfg, t) and "--force" not in sys.argv:
        return  # 영업시간 외에는 아무것도 하지 않음
    n = check(cfg, state)
    log(f"감시 완료: 새 알림 {n}건")
    end_hour = cfg.get("hours", [10, 18])[1]
    if t.hour >= end_hour - 1 and t.minute >= 45 or t.hour >= end_hour:
        if not state.get("summary_sent", {}).get(t.date().isoformat()):
            summary(cfg, state)
    save_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
