# -*- coding: utf-8 -*-
"""
하늘공인중개사 - 네이버 부동산 매물 자동 수집
m.land.naver.com 의 중개사무소 매물 목록을 읽어 listings.json 으로 저장합니다.
"""
import json
import re
import sys
import time
import datetime
import urllib.request

REALTOR_ID = "gksmfqnehdtk"          # 하늘공인중개사사무소 네이버 ID
PAGE_URL = "https://m.land.naver.com/agency/info/" + REALTOR_ID
LIST_URL = "https://m.land.naver.com/agency/info/list"
IMG_HOST = "https://landthumb-phinf.pstatic.net"
IMG_TYPE = "f320_240"
MAX_PAGES = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
}


def http_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def fmt_price(v):
    """'43000' (만원) -> '4억 3,000' / '3000/150' -> ('3,000','150')"""
    v = str(v or "").strip().replace(",", "")
    if not v:
        return ""
    if "/" in v:  # 보증금/월세가 한 필드로 오는 경우
        return "/".join(fmt_price(p) for p in v.split("/"))
    if not v.isdigit():
        return str(v)
    n = int(v)
    eok, man = divmod(n, 10000)
    if eok and man:
        return f"{eok}억 {man:,}"
    if eok:
        return f"{eok}억"
    return f"{man:,}"


def map_item(a):
    trade = a.get("tradTpNm", "")
    prc = fmt_price(a.get("prcInfo", ""))
    rent = fmt_price(a.get("rentPrc", "")) if a.get("rentPrc") else ""
    if not rent and trade in ("월세", "단기임대") and "/" in prc:
        prc, rent = prc.split("/", 1)
    img = a.get("repImgUrl", "") or ""
    if img and not img.startswith("http"):
        img = IMG_HOST + img + "?type=" + IMG_TYPE
    title = a.get("atclNm", "")
    bild = a.get("bildNm", "")
    if bild and bild not in title:
        title = f"{title} {bild}"
    return {
        "id": a.get("atclNo", ""),
        "trade": trade,
        "type": a.get("atclRletTpNm", ""),
        "title": title,
        "price": prc,
        "rentPrice": rent,
        "area1": a.get("spc1", ""),
        "area2": a.get("spc2", ""),
        "floor": a.get("flrInfo", ""),
        "direction": a.get("direction", ""),
        "desc": a.get("atclFetrDesc", ""),
        "tags": a.get("tagList", []) or [],
        "img": img,
        "confirmedAt": a.get("atclCfmYmd", ""),
        "verified": a.get("vrfcTpCd", ""),
        "link": "https://m.land.naver.com/article/info/" + str(a.get("atclNo", "")),
    }


def extract_items(payload):
    """응답 JSON 어디에 목록이 있어도 찾아낸다."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("list", "articleList", "result", "body", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = extract_items(v)
                if inner:
                    return inner
    return []


def main():
    all_items = []

    # 1) 첫 페이지: HTML 안의 firstData JSON
    html = http_get(PAGE_URL)
    m = re.search(r"firstData\s*:\s*\$\.parseJSON\('(.+)", html)
    if m:
        raw = m.group(1).replace("\\'", "'")
        try:
            items, _end = json.JSONDecoder().raw_decode(raw)
            all_items.extend(items)
        except Exception as e:
            print("firstData parse fail:", e)

    tot = 0
    mt = re.search(r"totCnt\s*:\s*'?(\d+)", html)
    if mt:
        tot = int(mt.group(1))
    print(f"first page items: {len(all_items)}, total on naver: {tot}")

    # 2) 2페이지부터 AJAX 목록
    page = 2
    while page <= MAX_PAGES:
        url = f"{LIST_URL}?rltrMbrId={REALTOR_ID}&tradTpCd=&atclRletTpCd=&tradeTypeChange=0&page={page}"
        try:
            body = http_get(url)
            items = extract_items(json.loads(body))
        except Exception as e:
            print(f"page {page} fail: {e}")
            break
        if not items:
            break
        all_items.extend(items)
        print(f"page {page}: +{len(items)}")
        if tot and len(all_items) >= tot:
            break
        page += 1
        time.sleep(0.7)

    # 3) 중복 제거 + 거래완료 제외 + 매핑
    seen, mapped = set(), []
    for a in all_items:
        no = a.get("atclNo")
        if not no or no in seen:
            continue
        seen.add(no)
        if a.get("tradCmplYn") == "Y":
            continue
        mapped.append(map_item(a))

    kst = datetime.timezone(datetime.timedelta(hours=9))
    out = {
        "updatedAt": datetime.datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "office": "하늘공인중개사사무소",
        "totalOnNaver": tot,
        "items": mapped,
    }
    with open("listings.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"saved listings.json: {len(mapped)} items")

    if len(mapped) == 0:
        sys.exit(1)  # 0건이면 실패 처리(기존 파일 유지)


if __name__ == "__main__":
    main()
