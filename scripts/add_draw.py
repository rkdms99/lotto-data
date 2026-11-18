"""회차 하나를 수동으로 추가한다 (manual-add 워크플로용).

추첨일은 직전 회차 + 7일로 정한다. 검증을 통과할 때만 파일을 바꾸고,
윈도우가 20회차를 넘으면 가장 오래된 회차를 뺀다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from lotto_window import DATA_PATH, ValidationError, append_and_trim, load, save_validated, today_kst


def _parse_numbers(text: str) -> list[int]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 6 or not all(p.isdigit() for p in parts):
        raise ValueError(f"numbers는 쉼표로 구분한 숫자 6개여야 해요: {text!r}")
    return sorted(int(p) for p in parts)


def _parse_optional_int(text: str | None, name: str) -> int | None:
    if text is None or text.strip() == "":
        return None
    if not text.strip().isdigit():
        raise ValueError(f"{name}는 0 이상 정수여야 해요: {text!r}")
    return int(text.strip())


def build_draw(doc: dict, *, round_no: int, numbers: str, bonus: int, prize1: str | None, first_winners: str | None) -> dict:
    last = doc["draws"][-1]
    if round_no != last["round"] + 1:
        raise ValueError(f"다음 회차는 {last['round'] + 1}회여야 해요 (입력: {round_no}회)")
    draw: dict = {
        "round": round_no,
        "drawDate": (dt.date.fromisoformat(last["drawDate"]) + dt.timedelta(days=7)).isoformat(),
        "numbers": _parse_numbers(numbers),
        "bonus": bonus,
    }
    winners = _parse_optional_int(first_winners, "firstWinners")
    if winners is not None:
        draw["firstWinners"] = winners
    p1 = _parse_optional_int(prize1, "prize1")
    if p1 is not None:
        draw["prizes"] = {"1": p1}
    return draw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--numbers", required=True, help="쉼표로 구분한 6개, 예: 1,5,18,23,27,28")
    parser.add_argument("--bonus", type=int, required=True)
    parser.add_argument("--prize1", default=None, help="1등 1게임당 당첨금 (선택)")
    parser.add_argument("--first-winners", default=None, help="1등 당첨 게임 수 (선택)")
    parser.add_argument("--path", default=str(DATA_PATH))
    args = parser.parse_args(argv)

    from pathlib import Path

    path = Path(args.path)
    try:
        doc = load(path)
        draw = build_draw(
            doc,
            round_no=args.round,
            numbers=args.numbers,
            bonus=args.bonus,
            prize1=args.prize1,
            first_winners=args.first_winners,
        )
        save_validated(append_and_trim(doc, [draw], updated_at=today_kst()), path)
    except (ValueError, ValidationError) as e:
        for line in str(e).splitlines():
            print(f"::error::{line}")
        print("추가하지 않았어요. 기존 데이터는 그대로예요.")
        return 1
    print(f"제 {draw['round']}회 추가: {draw['numbers']} + {draw['bonus']} ({draw['drawDate']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
