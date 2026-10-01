# -*- coding: utf-8 -*-
"""
하늘공인중개사 - 네이버 부동산 광고 순위 감시

사무실 PC에서 30분마다(오전 10시~저녁 6시) 실행됩니다.
감시 단지의 네이버 매물을 '랭킹순'으로 읽어서, 우리 사무소 매물과 같은 매물을
다른 부동산이 더 위에(또는 더 최신 확인일자로) 올렸으면 카카오톡으로 알립니다.
재광고는 건당 비용이 들기 때문에 자동으로 누르지 않고, 알림만 보냅니다.

사용법 (명령 프롬프트에서):
  python ad_monitor.py              감시 1회 실행 (예약 작업이 이걸 실행)
  python ad_monitor.py test         첫 단지 하나만 읽어서 결과 확인 (알림 안 보냄)
  python ad_monitor.py kakao-login  카카오톡 연결 (처음 한 번)
  python ad_monitor.py kakao-test   카카오톡 테스트 메시지
  python ad_monitor.py summary      오늘 요약을 지금 바로 보내기

표준 라이브러리만 사용합니다(추가 설치 없음). Python 3.10 이상.
"""
import datetime
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

def complex_no(value):
    """단지 번호 또는 네이버 부동산 단지 주소에서 단지 번호만 뽑는다."""
    s = str(value)
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


def same_listing(me, other):
    """같은 동·거래·전용면적이고, 층이 같거나(층 숫자 없으면 저/중/고 + 가격 일치)."""
    if me["trade"] != other["trade"] or not me["dong"] or me["dong"] != other["dong"]:
        return False
    if abs(me["area"] - other["area"]) > 1.0:
        return False
    if me["floor"] is not None and other["floor"] is not None:
        return me["floor"] == other["floor"]
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


def notify(cfg, text, link="", dry=False):
    log("알림: " + text.replace("\n", " | "))
    if dry:
        return
    try:
        send_kakao(cfg, text, link)
    except Exception as e:
        log(f"카카오톡 전송 실패: {e}")


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
    print("카카오톡 연결 완료. 'python ad_monitor.py kakao-test' 로 확인하세요.")


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

    complexes = cfg["complexes"][:1] if only_first else cfg["complexes"]
    for c in complexes:
        no = complex_no(c.get("url") or c.get("no"))
        name = c.get("name", no)
        if not no:
            log(f"[{name}] 단지 번호가 없습니다. complexes.txt 에 네이버 부동산 단지 주소를 넣어 주세요.")
            continue
        try:
            raw = fetch_complex(no, trades, cfg.get("max_pages", 10), debug=only_first)
        except Exception as e:
            log(f"[{name}] 네이버 읽기 실패: {e}")
            continue
        arts = [norm(a, name, i + 1) for i, a in enumerate(raw)]
        mine = [a for a in arts if is_mine(a, names)]
        log(f"[{name}] 매물 {len(arts)}건, 우리 매물 {len(mine)}건")
        if only_first:
            for a in arts[:15]:
                log(f"   {a['rank']:>3}위 {a['trade']} {a['dong']}동 {a['flr_text']} {a['area']}㎡ {a['price']} {a['date']} {a['realtor']}")

        for me in mine:
            gkey = f"{name}|{me['trade']}|{me['dong']}|{me['floor'] or me['band']}|{me['area']:.0f}"
            # 재광고 감지: 같은 매물의 우리 확인일자가 올라가면 직방 갱신 알림
            prev = my_dates.get(gkey)
            if me["date"] and prev and me["date"].isoformat() > prev:
                day["readded"].append(gkey)
                notify(cfg, f"[재광고 확인] {name} {me['dong']}동 {me['flr_text']}\n{me['trade']} {me['price']}\n네이버 {me['date']:%m/%d} 갱신됨\n→ 직방 광고도 같은 가격으로 갱신하세요", ARTICLE_URL + me["no"], dry)
            if me["date"]:
                my_dates[gkey] = me["date"].isoformat()

            rivals = [o for o in arts if not is_mine(o, names) and same_listing(me, o)]
            above = [o for o in rivals if o["rank"] < me["rank"] or (o["date"] and me["date"] and o["date"] > me["date"])]
            if not above:
                day["behind"].pop(gkey, None)
                continue
            top = min(above, key=lambda o: o["rank"])
            day["behind"][gkey] = f"{name} {me['dong']}동 {me['flr_text']} {me['trade']} {me['price']} (내 {me['rank']}위, {top['realtor']} {top['rank']}위)"

            # 같은 경쟁 광고·같은 확인일자로는 한 번만 알림 (비용 드는 재광고를 부추기지 않도록)
            akey = f"{me['no']}>{top['no']}@{top['date']}"
            if akey in alerted:
                continue
            if day["alerts"] >= cfg.get("max_alerts_per_day", 20):
                continue
            alerted[akey] = today
            day["alerts"] += 1
            new_alerts += 1
            price_note = "" if top["price"] == me["price"] else f"\n(상대 가격 {top['price']} — 다른 호수일 수 있음)"
            d_me = f"{me['date']:%m/%d}" if me["date"] else "?"
            d_top = f"{top['date']:%m/%d}" if top["date"] else "?"
            notify(cfg,
                   f"[광고 밀림] {name} {me['dong']}동 {me['flr_text']}\n"
                   f"{me['trade']} {me['price']} · 전용 {me['area']:.0f}㎡\n"
                   f"{top['realtor']} {top['rank']}위({d_top})\n"
                   f"우리 {me['rank']}위({d_me})"
                   f"{price_note}\n→ 이실장에서 재광고 검토",
                   ARTICLE_URL + top["no"], dry)
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
    lines = [f"[오늘 광고 요약 {now():%m/%d}]",
             f"밀림 알림 {day.get('alerts', 0)}건 · 재광고 {len(day.get('readded', []))}건",
             f"아직 밀린 매물 {len(behind)}건"]
    lines += ["- " + b for b in behind[:8]]
    if len(behind) > 8:
        lines.append(f"외 {len(behind) - 8}건 (monitor.log 참고)")
    if day.get("readded"):
        lines.append("※ 오늘 재광고한 매물은 직방도 갱신했는지 확인하세요")
    notify(cfg, "\n".join(lines), dry=dry)
    state.setdefault("summary_sent", {})[today] = True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    cfg = load_config()
    if cmd == "kakao-login":
        return kakao_login(cfg)
    if cmd == "kakao-test":
        send_kakao(cfg, "하늘공인중개사 광고 감시 연결 테스트입니다.")
        return print("보냈습니다. 카카오톡 '나와의 채팅'을 확인하세요.")

    state = load_json(STATE_PATH, {})
    if cmd == "test":
        log("=== 테스트: 첫 단지만 읽습니다 (알림 안 보냄, debug 폴더에 원본 저장) ===")
        check(cfg, state, dry=True, only_first=True)
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
