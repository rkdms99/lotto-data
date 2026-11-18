"""latest.json(최근 20회차 롤링 윈도우) 스키마와 검증 규칙.

validate.py · add_draw.py · fetch_latest.py가 함께 쓴다. 표준 라이브러리만 사용한다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1
WINDOW_SIZE = 20
FIRST_DRAW_DATE = dt.date(2002, 12, 7)
DRAW_TIME_KST = dt.time(20, 35)
KST = dt.timezone(dt.timedelta(hours=9))

DATA_PATH = Path(__file__).resolve().parent.parent / "docs" / "latest.json"

_REQUIRED = ("round", "drawDate", "numbers", "bonus")
_OPTIONAL_AMOUNTS = ("firstWinners", "firstPrizeTotal", "totalSales")


class ValidationError(Exception):
    """검증 실패. errors에 모든 문제를 담는다."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def expected_draw_date(round_no: int) -> dt.date:
    """공식 일정상 추첨일: 1회 2002-12-07부터 매주 토요일."""
    return FIRST_DRAW_DATE + dt.timedelta(days=7 * (round_no - 1))


def latest_drawn_round(now: dt.datetime) -> int:
    """now 시점(한국 시각 기준)에 추첨이 끝난 가장 최근 회차."""
    now_kst = now.astimezone(KST)
    first = dt.datetime.combine(FIRST_DRAW_DATE, DRAW_TIME_KST, tzinfo=KST)
    if now_kst < first:
        return 0
    return 1 + (now_kst - first).days // 7


def today_kst(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now(KST)).astimezone(KST).date().isoformat()


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_draw(d: object, where: str) -> list[str]:
    """회차 하나의 형식·번호 규칙."""
    if not isinstance(d, dict):
        return [f"{where}: 객체여야 해요"]
    errors: list[str] = []
    for key in _REQUIRED:
        if key not in d:
            errors.append(f"{where}: {key}가 없어요")
    if errors:
        return errors

    r = d["round"]
    if not _is_int(r) or r < 1:
        errors.append(f"{where}: round는 1 이상 정수여야 해요 ({r!r})")
    where = f"제 {r}회" if _is_int(r) else where

    try:
        date = dt.date.fromisoformat(d["drawDate"]) if isinstance(d["drawDate"], str) else None
    except ValueError:
        date = None
    if date is None or d["drawDate"] != date.isoformat():
        errors.append(f"{where}: drawDate는 YYYY-MM-DD 형식이어야 해요 ({d['drawDate']!r})")

    nums = d["numbers"]
    if not (isinstance(nums, list) and len(nums) == 6 and all(_is_int(n) and 1 <= n <= 45 for n in nums)):
        errors.append(f"{where}: numbers는 1~45 정수 6개여야 해요 ({nums!r})")
    elif len(set(nums)) != 6:
        errors.append(f"{where}: numbers에 중복이 있어요 ({nums})")
    elif nums != sorted(nums):
        errors.append(f"{where}: numbers는 오름차순이어야 해요 ({nums})")

    bonus = d["bonus"]
    if not (_is_int(bonus) and 1 <= bonus <= 45):
        errors.append(f"{where}: bonus는 1~45 정수여야 해요 ({bonus!r})")
    elif isinstance(nums, list) and bonus in nums:
        errors.append(f"{where}: bonus {bonus}가 당첨번호와 겹쳐요")

    prizes = d.get("prizes")
    if prizes is not None:
        if not isinstance(prizes, dict):
            errors.append(f"{where}: prizes는 객체여야 해요")
        else:
            for k, v in prizes.items():
                if k not in ("1", "2", "3"):
                    errors.append(f"{where}: prizes 키는 \"1\"~\"3\"이어야 해요 ({k!r})")
                if not (_is_int(v) and v >= 0):
                    errors.append(f"{where}: prizes[{k!r}]는 0 이상 정수여야 해요 ({v!r})")
    for key in _OPTIONAL_AMOUNTS:
        if key in d and not (_is_int(d[key]) and d[key] >= 0):
            errors.append(f"{where}: {key}는 0 이상 정수여야 해요 ({d[key]!r})")
    return errors


def validate_document(doc: object) -> list[str]:
    """latest.json 전체 검증. 문제가 없으면 빈 목록."""
    if not isinstance(doc, dict):
        return ["최상위 값은 객체여야 해요"]
    errors: list[str] = []
    if doc.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion은 {SCHEMA_VERSION}이어야 해요 ({doc.get('schemaVersion')!r})")
    updated = doc.get("updatedAt")
    if updated is not None:
        try:
            dt.date.fromisoformat(updated)
        except (TypeError, ValueError):
            errors.append(f"updatedAt은 YYYY-MM-DD 또는 null이어야 해요 ({updated!r})")

    draws = doc.get("draws")
    if not isinstance(draws, list) or not draws:
        return errors + ["draws는 비어 있지 않은 배열이어야 해요"]
    if len(draws) > WINDOW_SIZE:
        errors.append(f"draws는 최근 {WINDOW_SIZE}회차까지만 담아요 (현재 {len(draws)}개)")

    for i, d in enumerate(draws):
        errors += validate_draw(d, f"draws[{i}]")
    if errors:
        return errors

    # 윈도우 규칙: 회차 연속(오름차순), 7일 간격, 첫 회차 추첨일 = 2002-12-07 + 7*(회차-1)
    first = draws[0]
    expected_first = expected_draw_date(first["round"])
    if first["drawDate"] != expected_first.isoformat():
        errors.append(
            f"제 {first['round']}회: 첫 회차 추첨일 {first['drawDate']}이 일정상 {expected_first}과 달라요"
        )
    for prev, cur in zip(draws, draws[1:]):
        if cur["round"] != prev["round"] + 1:
            errors.append(f"회차가 연속이 아니에요: {prev['round']} 다음에 {cur['round']}")
        gap = (dt.date.fromisoformat(cur["drawDate"]) - dt.date.fromisoformat(prev["drawDate"])).days
        if gap != 7:
            errors.append(f"제 {cur['round']}회: 직전 회차와 추첨일 간격이 {gap}일이에요 (7일이어야 해요)")
    return errors


def load(path: Path = DATA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dumps(doc: dict) -> str:
    """회차 하나를 한 줄로 쓰는 읽기 쉬운 형식."""
    head = {k: v for k, v in doc.items() if k != "draws"}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},")
    lines.append('  "draws": [')
    rows = [f"    {json.dumps(d, ensure_ascii=False, separators=(', ', ': '))}" for d in doc["draws"]]
    lines.append(",\n".join(rows))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def save_validated(doc: dict, path: Path = DATA_PATH) -> None:
    """검증을 통과할 때만 원자적으로 저장한다. 실패하면 기존 파일은 그대로."""
    errors = validate_document(doc)
    if errors:
        raise ValidationError(errors)
    text = dumps(doc)
    if json.loads(text) != doc:  # 직렬화 왕복 확인
        raise ValidationError(["저장 형식 변환 중 값이 달라졌어요"])
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".latest.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def append_and_trim(doc: dict, new_draws: list[dict], *, updated_at: str) -> dict:
    """새 회차를 뒤에 붙이고 가장 오래된 회차부터 잘라 WINDOW_SIZE를 유지한 새 문서."""
    draws = list(doc["draws"]) + list(new_draws)
    return {**doc, "updatedAt": updated_at, "draws": draws[-WINDOW_SIZE:]}
