# lotto-data

로또 6/45 **최근 20회차** 당첨번호 JSON. GitHub Pages로 제공합니다.

> **이 저장소는 동행복권과 무관한 개인 프로젝트입니다.**
> 출처: 동행복권 회차별 당첨번호 (https://www.dhlottery.co.kr/lt645/result).
> 정확한 결과는 동행복권 공식 발표를 확인해 주세요.

- 데이터: `https://rkdms99.github.io/lotto-data/latest.json`
- 전체 회차 데이터는 이 저장소에 두지 않습니다. 최근 20회차만 롤링 윈도우로 유지합니다.

## 스키마

> 아래 값은 **형식 예시이며 실제 당첨번호가 아닙니다.**

```json
{
  "schemaVersion": 1,
  "updatedAt": "2026-11-22",
  "draws": [
    { "round": 1232, "drawDate": "2026-07-11", "numbers": [1, 2, 3, 4, 5, 6], "bonus": 7,
      "firstWinners": 10, "prizes": { "1": 2500000000, "2": 50000000, "3": 1500000 } }
  ]
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `schemaVersion` | ✅ | `1` |
| `updatedAt` | | 갱신일 `YYYY-MM-DD` (한국 날짜) 또는 `null` |
| `draws` | ✅ | 회차 오름차순, 최대 20개 |
| `round` | ✅ | 회차 |
| `drawDate` | ✅ | 추첨일 `YYYY-MM-DD` |
| `numbers` | ✅ | 1~45, 중복 없는 6개, 오름차순 |
| `bonus` | ✅ | 1~45, `numbers`와 겹치지 않음 |
| `firstWinners` | | 1등 당첨 게임 수 |
| `prizes` | | 1게임당 세전 당첨금. 키 `"1"`~`"3"`. 1등 당첨자가 없으면 `"1"` 없음 |

앱(`lotto-app`)의 `assets/data/lotto_history.json`과 같은 스키마입니다.

## 검증 (`scripts/validate.py`)

검증에 실패하면 커밋하지 않고 Pages에도 배포하지 않습니다.

- 번호: 1~45 범위, 중복 없음, 6개, 오름차순
- 보너스: 1~45 범위, 당첨번호와 겹치지 않음
- 윈도우 안 회차가 빠짐없이 연속, 최대 20개
- 추첨일 7일 간격, 첫 회차 추첨일 = 2002-12-07 + 7 × (회차 − 1)

```bash
python scripts/validate.py
python -m unittest discover -s tests -v
```

## 워크플로

| 워크플로 | 시점 | 하는 일 |
|---|---|---|
| `weekly-fetch` | 매주 일요일 01:00 KST (`0 16 * * 6` UTC) | 동행복권 당첨결과 페이지가 쓰는 JSON에 **요청 1번** → 검증 → 커밋 → 배포. 대기 화면·형식 변경·값 검증 실패 시 **워크플로 실패**(데이터 변경 없음) |
| `manual-add` | 수동 (Actions → Run workflow) | 회차·번호·보너스(+1등 금액·당첨자 수)를 입력해 추가. `weekly-fetch` 실패 시 백업 |
| `pages` | main push, 위 두 워크플로 커밋 후 | 검증·테스트 통과 시에만 `docs/`를 Pages로 배포 |
| `validate` | 브랜치 push, PR | 검증·테스트 |

수집 요청에는 `User-Agent: lotto-data-bot/1.0 (… +https://github.com/rkdms99/lotto-data)`를 붙입니다.

> 참고: public 저장소의 예약 워크플로는 저장소 활동이 60일 동안 없으면 GitHub이 자동으로 끕니다.
