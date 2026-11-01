"""Arama algoritması testleri: deterministik 'oracle' ile bütün olası limitler denenir."""
import random

import pytest

from pbo_tuner.search import CoreSearch, SearchParams, PHASE_DONE


def drive(limit: int, params: SearchParams, crash_beyond: int = 10**9):
    """Çekirdeğin gerçek limiti `limit` (a <= limit geçer, üstü kalır)."""
    cs = CoreSearch(params=params)
    tests = []
    for _ in range(500):  # sonsuz döngü koruması
        t = cs.next_test()
        if t is None:
            break
        tests.append(t)
        passed = t.a <= limit
        crashed = (not passed) and (t.a >= crash_beyond)
        cs.record(t, passed, crashed=crashed)
    else:
        pytest.fail("algoritma sonlanmadı")
    return cs, tests


@pytest.mark.parametrize("limit", range(0, 61))
def test_final_equals_limit_minus_margin(limit):
    p = SearchParams(floor=40, coarse_step=5, margin=2, confirm_backoff=2)
    cs, tests = drive(limit, p)
    assert cs.phase == PHASE_DONE
    if limit >= p.floor:
        expected = p.floor                       # sınır bulunamadı, taban doğrulandı
    else:
        expected = max(0, limit - p.margin)
    assert cs.final == expected, (limit, cs.final, expected)
    # Hiçbir zaman gerçek limitin üstüne çıkmaz
    assert cs.final <= max(limit, 0)
    # Taban aşılmaz
    assert all(t.a <= p.floor for t in tests)


@pytest.mark.parametrize("limit", range(0, 41))
def test_test_count_is_bounded(limit):
    p = SearchParams()
    _, tests = drive(limit, p)
    assert len(tests) <= 8 + 4 + 3  # iniş + ikili arama + onay


def test_never_tests_unstable_region_twice_in_descent_and_bisect():
    p = SearchParams()
    cs, tests = drive(23, p)
    coarse_fine = [t for t in tests if t.level != "confirm"]
    seen = [t.a for t in coarse_fine]
    assert len(seen) == len(set(seen))


def test_confirm_failure_backs_off_linearly():
    """İnce testi geçen ama onayı kalan çekirdek (aralıklı hata) geri çekilir."""
    p = SearchParams(floor=40, margin=2, confirm_backoff=2)
    cs = CoreSearch(params=p)
    flaky_limit_confirm = 14            # onay seviyesinde gerçek limit
    while (t := cs.next_test()) is not None:
        if t.level == "confirm":
            cs.record(t, t.a <= flaky_limit_confirm)
        else:
            cs.record(t, t.a <= 23)      # kısa testler 23'e kadar geçiyor
    assert cs.final is not None and cs.final <= flaky_limit_confirm
    assert cs.final >= flaky_limit_confirm - 2


def test_crash_limit_switches_to_conservative_value():
    p = SearchParams(floor=40, margin=2, max_crashes=2)
    cs, tests = drive(33, p, crash_beyond=34)
    assert cs.phase == PHASE_DONE
    assert cs.final <= 33
    assert cs.crashes >= 1


def test_serialization_roundtrip_midway():
    p = SearchParams()
    cs = CoreSearch(params=p)
    for _ in range(3):
        t = cs.next_test()
        cs.record(t, t.a <= 17)
    d = cs.to_dict()
    cs2 = CoreSearch.from_dict(d, p)
    assert cs2.to_dict() == d
    # İkisi de aynı yoldan aynı sonuca ulaşır
    for c in (cs, cs2):
        while (t := c.next_test()) is not None:
            c.record(t, t.a <= 17)
    assert cs.final == cs2.final == 15


def test_random_noisy_oracle_always_terminates_and_stays_below_true_limit_when_confirm_is_strict():
    rng = random.Random(1234)
    for _ in range(300):
        limit = rng.randint(0, 45)
        p = SearchParams(floor=rng.choice([30, 40, 50]), coarse_step=rng.choice([3, 5, 7]),
                         margin=rng.choice([0, 1, 2, 3]), confirm_backoff=rng.choice([1, 2, 3]))
        cs = CoreSearch(params=p)
        steps = 0
        while (t := cs.next_test()) is not None:
            steps += 1
            assert steps < 200
            # kısa testler gürültülü (limitin 3 üstüne kadar şans eseri geçebilir), onay katı
            if t.level == "confirm":
                ok = t.a <= limit
            else:
                ok = t.a <= limit or (t.a <= limit + 3 and rng.random() < 0.5)
            cs.record(t, ok)
        assert cs.final <= max(limit, 0) or cs.final == p.floor and limit >= p.floor


@pytest.mark.parametrize("limit", range(0, 61))
def test_start_jumps_first_step_and_still_converges(limit):
    p = SearchParams(floor=40, coarse_step=5, margin=2, confirm_backoff=2, start=20)
    cs, tests = drive(limit, p)
    first = tests[0]
    assert first.a == 20 and first.level == "coarse"
    expected = p.floor if limit >= p.floor else max(0, limit - p.margin)
    assert cs.final == expected, (limit, cs.final, expected)
    assert all(t.a <= p.floor for t in tests)


def test_start_zero_is_old_behavior():
    cs = CoreSearch(params=SearchParams(start=0))
    assert cs.next_test().a == 5


def test_start_failure_bisects_from_zero():
    cs = CoreSearch(params=SearchParams(start=20, margin=2))
    t = cs.next_test()
    assert t.a == 20
    cs.record(t, False)
    assert cs.phase == "bisect" and cs.next_test().a == 10
