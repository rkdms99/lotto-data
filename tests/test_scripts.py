"""validate / add_draw / fetch_latest 단위 테스트. 네트워크를 쓰지 않는다.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import add_draw  # noqa: E402
import fetch_latest  # noqa: E402
import lotto_window as lw  # noqa: E402

# 테스트용 가짜 번호 (실제 당첨번호 아님). 추첨일만 일정에 맞춘다.
FAKE = [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12], [13, 14, 15, 16, 17, 18], [19, 20, 21, 22, 23, 24]]


def draw(round_no: int, **extra) -> dict:
    return {
        "round": round_no,
        "drawDate": lw.expected_draw_date(round_no).isoformat(),
        "numbers": FAKE[round_no % 4],
        "bonus": 45,
        **extra,
    }


def window(first: int, last: int) -> dict:
    return {"schemaVersion": 1, "updatedAt": "2026-11-14", "draws": [draw(r) for r in range(first, last + 1)]}


def api_item(round_no: int, *, first_winners: int = 9) -> dict:
    nums = FAKE[round_no % 4]
    d = lw.expected_draw_date(round_no)
    return {
        "ltEpsd": round_no,
        **{f"tm{i + 1}WnNo": n for i, n in enumerate(nums)},
        "bnsWnNo": 45,
        "ltRflYmd": d.strftime("%Y%m%d"),
        "rnk1WnNope": first_winners,
        "rnk1WnAmt": 3_000_000_000,
        "rnk2WnAmt": 50_000_000,
        "rnk3WnAmt": 1_500_000,
    }


def api_body(rounds: list[int], **kw) -> bytes:
    return json.dumps({"resultCode": None, "data": {"list": [api_item(r, **kw) for r in rounds]}}).encode()


class ValidateTest(unittest.TestCase):
    def test_valid_window(self):
        self.assertEqual(lw.validate_document(window(1231, 1250)), [])

    def test_real_initial_file(self):
        self.assertEqual(lw.validate_document(lw.load()), [])

    def assertInvalid(self, doc, contains):
        errors = lw.validate_document(doc)
        self.assertTrue(any(contains in e for e in errors), f"{contains!r} not in {errors}")

    def test_number_rules(self):
        for nums, msg in [
            ([1, 2, 3, 4, 5], "6개"),
            ([0, 2, 3, 4, 5, 6], "6개"),
            ([1, 2, 3, 4, 5, 46], "6개"),
            ([1, 1, 3, 4, 5, 6], "중복"),
            ([6, 5, 4, 3, 2, 1], "오름차순"),
        ]:
            doc = window(1249, 1250)
            doc["draws"][0]["numbers"] = nums
            self.assertInvalid(doc, msg)

    def test_bonus_rules(self):
        doc = window(1249, 1250)
        doc["draws"][0]["bonus"] = doc["draws"][0]["numbers"][0]
        self.assertInvalid(doc, "겹쳐요")
        doc["draws"][0]["bonus"] = 46
        self.assertInvalid(doc, "bonus")

    def test_rounds_must_be_consecutive(self):
        doc = window(1240, 1250)
        del doc["draws"][5]
        self.assertInvalid(doc, "연속")

    def test_seven_day_gap(self):
        doc = window(1249, 1250)
        doc["draws"][1]["drawDate"] = "2026-11-15"
        self.assertInvalid(doc, "7일")

    def test_first_round_date_matches_schedule(self):
        doc = window(1249, 1250)
        for d in doc["draws"]:
            d["drawDate"] = (dt.date.fromisoformat(d["drawDate"]) + dt.timedelta(days=1)).isoformat()
        self.assertInvalid(doc, "첫 회차")

    def test_window_size(self):
        self.assertInvalid(window(1200, 1250), "최근 20회차")

    def test_optional_fields(self):
        doc = window(1249, 1250)
        doc["draws"][0]["prizes"] = {"4": 50000}
        self.assertInvalid(doc, "prizes 키")
        doc = window(1249, 1250)
        doc["draws"][0]["firstWinners"] = -1
        self.assertInvalid(doc, "firstWinners")


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "latest.json"
        self.path.write_text(lw.dumps(window(1231, 1250)), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_invalid_document_is_not_written(self):
        before = self.path.read_text(encoding="utf-8")
        bad = window(1231, 1250)
        bad["draws"][-1]["bonus"] = 99
        with self.assertRaises(lw.ValidationError):
            lw.save_validated(bad, self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(list(Path(self.dir.name).glob(".latest.*")), [], "임시 파일이 남으면 안 된다")

    def test_add_draw_appends_and_trims(self):
        code = add_draw.main(["--round", "1251", "--numbers", "45,3,22,1,30,7", "--bonus", "8",
                              "--prize1", "2000000000", "--first-winners", "12", "--path", str(self.path)])
        self.assertEqual(code, 0)
        doc = lw.load(self.path)
        self.assertEqual([d["round"] for d in doc["draws"]][:1] + [doc["draws"][-1]["round"]], [1232, 1251])
        self.assertEqual(len(doc["draws"]), 20)
        last = doc["draws"][-1]
        self.assertEqual(last["numbers"], [1, 3, 7, 22, 30, 45])
        self.assertEqual(last["drawDate"], "2026-11-21")
        self.assertEqual(last["prizes"], {"1": 2000000000})
        self.assertEqual(last["firstWinners"], 12)

    def test_add_draw_rejects_and_keeps_file(self):
        before = self.path.read_text(encoding="utf-8")
        for args in (
            ["--round", "1252", "--numbers", "1,2,3,4,5,6", "--bonus", "7"],  # 회차 건너뜀
            ["--round", "1251", "--numbers", "1,2,3,4,5", "--bonus", "7"],  # 5개
            ["--round", "1251", "--numbers", "1,2,3,4,5,6", "--bonus", "6"],  # 보너스 겹침
            ["--round", "1251", "--numbers", "1,2,3,4,5,46", "--bonus", "7"],  # 범위
            ["--round", "1251", "--numbers", "1,2,3,4,5,6", "--bonus", "7", "--prize1", "-1"],
        ):
            self.assertEqual(add_draw.main([*args, "--path", str(self.path)]), 1, args)
            self.assertEqual(self.path.read_text(encoding="utf-8"), before, args)


class FetchTest(unittest.TestCase):
    def parse(self, rounds, **kw):
        return fetch_latest.parse_response(status=200, content_type="application/json;charset=UTF-8", body=api_body(rounds, **kw))

    def test_parse_maps_fields(self):
        [d] = self.parse([1251])
        self.assertEqual(d["round"], 1251)
        self.assertEqual(d["drawDate"], "2026-11-21")
        self.assertEqual(d["numbers"], FAKE[1251 % 4])
        self.assertEqual(d["bonus"], 45)
        self.assertEqual(d["firstWinners"], 9)
        self.assertEqual(d["prizes"], {"1": 3_000_000_000, "2": 50_000_000, "3": 1_500_000})

    def test_no_first_prize_amount_when_no_winner(self):
        [d] = self.parse([1251], first_winners=0)
        self.assertNotIn("1", d["prizes"])

    def test_waiting_page_or_format_change_fails(self):
        cases = [
            dict(status=200, content_type="text/html", body=b"<html>waiting</html>"),
            dict(status=503, content_type="application/json", body=b"{}"),
            dict(status=200, content_type="application/json", body=b"not json"),
            dict(status=200, content_type="application/json", body=b'{"data": {}}'),
            dict(status=200, content_type="application/json", body=b'{"data": {"list": [{"ltEpsd": "x"}]}}'),
            dict(status=200, content_type="application/json", body=api_body([1251]), final_url="https://www.dhlottery.co.kr/"),
        ]
        for c in cases:
            with self.assertRaises(fetch_latest.FetchError, msg=c):
                fetch_latest.parse_response(**c)

    def test_value_validation_fails(self):
        item = api_item(1251)
        item["bnsWnNo"] = item["tm1WnNo"]
        body = json.dumps({"data": {"list": [item]}}).encode()
        with self.assertRaisesRegex(fetch_latest.FetchError, "겹쳐요"):
            fetch_latest.parse_response(status=200, content_type="application/json", body=body)
        item = api_item(1251)
        item["ltRflYmd"] = "20261122"
        body = json.dumps({"data": {"list": [item]}}).encode()
        with self.assertRaisesRegex(fetch_latest.FetchError, "일정"):
            fetch_latest.parse_response(status=200, content_type="application/json", body=body)

    def test_merge_adds_new_round_and_trims(self):
        doc = window(1231, 1250)
        merged = fetch_latest.merge(doc, self.parse(list(range(1251, 1241, -1))), target_round=1251, updated_at="2026-11-22")
        rounds = [d["round"] for d in merged["draws"]]
        self.assertEqual((rounds[0], rounds[-1], len(rounds)), (1232, 1251, 20))
        self.assertEqual(merged["updatedAt"], "2026-11-22")
        self.assertEqual(lw.validate_document(merged), [])
        self.assertEqual(doc, window(1231, 1250), "원본 문서는 바뀌지 않는다")

    def test_merge_fills_missing_prizes_but_keeps_existing(self):
        doc = window(1231, 1250)
        doc["draws"][-1]["prizes"] = {"1": 123}
        merged = fetch_latest.merge(doc, self.parse([1251, 1250]), target_round=1251, updated_at="2026-11-22")
        r1250 = next(d for d in merged["draws"] if d["round"] == 1250)
        self.assertEqual(r1250["prizes"], {"1": 123, "2": 50_000_000, "3": 1_500_000})

    def test_merge_fails_on_mismatch_with_existing(self):
        doc = window(1231, 1250)
        doc["draws"][-1]["numbers"] = [40, 41, 42, 43, 44, 45]
        doc["draws"][-1]["bonus"] = 1
        with self.assertRaisesRegex(fetch_latest.FetchError, "기존 데이터와 달라요"):
            fetch_latest.merge(doc, self.parse([1251, 1250]), target_round=1251, updated_at="2026-11-22")

    def test_merge_fails_when_target_missing_or_gap(self):
        doc = window(1231, 1250)
        with self.assertRaisesRegex(fetch_latest.FetchError, "응답에 없어요"):
            fetch_latest.merge(doc, self.parse([1250]), target_round=1251, updated_at="x")
        with self.assertRaisesRegex(fetch_latest.FetchError, "응답에 없는 회차"):
            fetch_latest.merge(doc, self.parse([1252]), target_round=1252, updated_at="x")

    def test_latest_drawn_round_uses_kst(self):
        kst = lw.KST
        self.assertEqual(lw.latest_drawn_round(dt.datetime(2026, 11, 14, 20, 34, tzinfo=kst)), 1249)
        self.assertEqual(lw.latest_drawn_round(dt.datetime(2026, 11, 14, 20, 35, tzinfo=kst)), 1250)
        # 워크플로 시각: 일요일 01:00 KST = 토요일 16:00 UTC
        self.assertEqual(lw.latest_drawn_round(dt.datetime(2026, 11, 21, 16, 0, tzinfo=dt.timezone.utc)), 1251)


if __name__ == "__main__":
    unittest.main()
