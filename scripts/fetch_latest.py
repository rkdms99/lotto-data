"""동행복권 당첨결과 페이지가 쓰는 JSON에서 최신 회차를 가져와 latest.json에 반영한다.

- 실행 1번에 HTTP 요청은 정확히 1번 (재시도 없음).
- 대기 화면(HTML)·응답 형식 변경·값 검증 실패 → 종료 코드 1, 데이터 변경 없음.
- 이미 윈도우에 있는 회차는 번호·보너스·추첨일이 응답과 같은지 확인하고,
  빠진 당첨금 정보(2·3등 등)만 채운다.

사용:
  python scripts/fetch_latest.py                # 최신 회차 수집 → 검증 → 저장
  python scripts/fetch_latest.py --dry-run --round 1250   # 요청·파싱 결과만 출력 (저장 안 함)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from lotto_window import (
    DATA_PATH,
    KST,
    ValidationError,
    append_and_trim,
    expected_draw_date,
    latest_drawn_round,
    load,
    save_validated,
    today_kst,
    validate_draw,
)

ENDPOINT = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
REFERER = "https://www.dhlottery.co.kr/lt645/result"
USER_AGENT = "lotto-data-bot/1.0 (personal lotto app data; weekly, 1 request; +https://github.com/rkdms99/lotto-data)"
TIMEOUT_SECONDS = 20


class FetchError(Exception):
    pass


def request_rounds(round_no: int) -> list[dict]:
    """round_no를 중심으로 한 회차 목록(보통 최근 10개)을 받는다. 요청 1번."""
    query = urllib.parse.urlencode({"srchDir": "center", "srchLtEpsd": str(round_no)})
    req = urllib.request.Request(
        f"{ENDPOINT}?{query}",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": REFERER,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            status = res.status
            ctype = res.headers.get("Content-Type", "")
            body = res.read()
            final_url = res.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} 응답") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise FetchError(f"연결 실패: {e}") from e

    return parse_response(status=status, content_type=ctype, body=body, final_url=final_url)


def parse_response(*, status: int, content_type: str, body: bytes, final_url: str = ENDPOINT) -> list[dict]:
    if status != 200:
        raise FetchError(f"HTTP {status} 응답")
    if not final_url.startswith(ENDPOINT):
        raise FetchError(f"다른 주소로 이동됐어요 (대기 화면 또는 주소 변경): {final_url}")
    if "json" not in content_type.lower():
        snippet = body[:120].decode("utf-8", "replace").replace("\n", " ")
        raise FetchError(f"JSON이 아닌 응답이에요 (대기 화면 또는 형식 변경). Content-Type={content_type!r}, 앞부분={snippet!r}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise FetchError(f"JSON 해석 실패: {e}") from e

    rounds = (payload.get("data") or {}).get("list") if isinstance(payload, dict) else None
    if not isinstance(rounds, list) or not rounds:
        raise FetchError(f"응답 형식이 바뀌었어요: data.list가 없어요 (키: {list(payload)[:10] if isinstance(payload, dict) else type(payload).__name__})")
    return [to_draw(item) for item in rounds]


def to_draw(item: object) -> dict:
    """응답 한 항목 → latest.json 회차 형식. 필드가 없거나 타입이 다르면 FetchError."""
    if not isinstance(item, dict):
        raise FetchError("응답 항목이 객체가 아니에요")

    def need_int(key: str) -> int:
        v = item.get(key)
        if isinstance(v, bool) or not isinstance(v, int):
            raise FetchError(f"응답 형식이 바뀌었어요: {key}={v!r}")
        return v

    round_no = need_int("ltEpsd")
    ymd = item.get("ltRflYmd")
    try:
        draw_date = dt.datetime.strptime(str(ymd), "%Y%m%d").date()
    except ValueError as e:
        raise FetchError(f"제 {round_no}회 추첨일 형식이 바뀌었어요: {ymd!r}") from e

    draw = {
        "round": round_no,
        "drawDate": draw_date.isoformat(),
        "numbers": sorted(need_int(f"tm{i}WnNo") for i in range(1, 7)),
        "bonus": need_int("bnsWnNo"),
        "firstWinners": need_int("rnk1WnNope"),
        # 1등 당첨자가 없으면 1인당 금액은 의미가 없어 넣지 않는다.
        "prizes": {
            k: v
            for k, v in (("1", need_int("rnk1WnAmt")), ("2", need_int("rnk2WnAmt")), ("3", need_int("rnk3WnAmt")))
            if not (k == "1" and need_int("rnk1WnNope") == 0)
        },
    }
    errors = validate_draw(draw, f"제 {round_no}회")
    if errors:
        raise FetchError("값 검증 실패: " + "; ".join(errors))
    if draw_date != expected_draw_date(round_no):
        raise FetchError(f"제 {round_no}회 추첨일 {draw_date}이 일정상 {expected_draw_date(round_no)}과 달라요")
    return draw


def merge(doc: dict, fetched: list[dict], *, target_round: int, updated_at: str) -> dict:
    """응답을 윈도우에 반영한 새 문서. 기존 회차와 값이 다르면 FetchError."""
    by_round = {d["round"]: d for d in fetched}
    if target_round not in by_round:
        raise FetchError(f"최신 회차(제 {target_round}회)가 응답에 없어요. 받은 회차: {sorted(by_round)}")

    current = [dict(d) for d in doc["draws"]]
    for d in current:
        f = by_round.get(d["round"])
        if f is None:
            continue
        for key in ("drawDate", "numbers", "bonus"):
            if d[key] != f[key]:
                raise FetchError(f"제 {d['round']}회 {key}가 기존 데이터와 달라요: 기존 {d[key]!r}, 응답 {f[key]!r}")
        # 빠진 당첨금 정보만 채운다 (기존 값은 바꾸지 않음).
        d.setdefault("firstWinners", f["firstWinners"])
        prizes = {**f["prizes"], **d.get("prizes", {})}
        if prizes:
            d["prizes"] = prizes

    last = current[-1]["round"]
    new = [by_round[r] for r in range(last + 1, target_round + 1) if r in by_round]
    if len(new) != target_round - last:
        missing = [r for r in range(last + 1, target_round + 1) if r not in by_round]
        raise FetchError(f"새 회차 중 응답에 없는 회차가 있어요: {missing} (윈도우가 끊기지 않게 수동 추가가 필요해요)")
    return append_and_trim({**doc, "draws": current}, new, updated_at=updated_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--round", type=int, help="조회할 회차 (기본: 현재 시각 기준 최신 회차)")
    parser.add_argument("--dry-run", action="store_true", help="요청·파싱 결과만 출력하고 저장하지 않음")
    args = parser.parse_args(argv)

    now = dt.datetime.now(KST)
    target = args.round or latest_drawn_round(now)
    try:
        fetched = request_rounds(target)
        if args.dry_run:
            print(json.dumps(fetched, ensure_ascii=False, indent=2))
            return 0
        doc = load()
        updated = merge(doc, fetched, target_round=target, updated_at=today_kst(now))
        if updated["draws"] == doc["draws"]:
            print(f"변경 없음: 이미 제 {target}회까지 최신이에요")
            return 0
        save_validated(updated, DATA_PATH)
    except (FetchError, ValidationError) as e:
        for line in str(e).splitlines():
            print(f"::error::{line}")
        print("수집 실패. 기존 데이터는 그대로예요.")
        return 1

    draws = updated["draws"]
    print(f"저장: 제 {draws[0]['round']}회 ~ 제 {draws[-1]['round']}회 (최신 {draws[-1]['numbers']} + {draws[-1]['bonus']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
