"""docs/latest.json 검증. 실패하면 이유를 출력하고 종료 코드 1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lotto_window import DATA_PATH, validate_document


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DATA_PATH
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"::error::{path}를 읽지 못했어요: {e}")
        return 1

    errors = validate_document(doc)
    if errors:
        for e in errors:
            print(f"::error::{e}")
        print(f"검증 실패: {len(errors)}건")
        return 1

    draws = doc["draws"]
    print(f"검증 통과: 제 {draws[0]['round']}회 ~ 제 {draws[-1]['round']}회 ({len(draws)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
