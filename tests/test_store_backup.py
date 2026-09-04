# -*- coding: utf-8 -*-
"""Backup durable store: gzip round-trip, merge, prune, publish/pull, cache.

Latar belakang: ``holder_status.json`` (snapshot dashboard) dirampingkan — peta
wallet alert/kohort/kronologi tidak ikut lagi (terukur 94% dari 2,22 MB untuk 36
token). State penuh itu sekarang dibackup terpisah sebagai
``holder_history.json.gz`` di ref ``holder-live`` dan dipulihkan cron/UI, jadi
lingkungan ephemeral (runner Actions, Streamlit Cloud) tidak lagi kehilangan
baseline scan FULL, kohort beku, state dedup alert, dan kronologi.
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from unittest import mock

import holder_history as hh
import holder_status as hs

MINT = "FnLox4hs8zB3YefUyBdwFtTmZm7cMaNSHr5utV4Yswrm"
ADDR = "WalletAddr111111111111111111111111111111111"


def _slot(ts=100, **over):
    slot = {
        "symbol": "TST",
        "points": [{"ts": ts, "dust_count": 10, "dust_pct_mc": 1.1,
                    "buckets": {">$0-$10": 10}}],
        "baseline": {"ts": 50, "dust_count": 8},
        "latest_detail": {"ts": ts, "dust_count": 10},
        "cohort": {"frozen_at": ts - 10, "balances": {ADDR: 2.0}},
        "chronology": {
            "baseline_wallets": {"ts": 50, "wallets": {ADDR: {"balance": 1.0}}},
            "latest_wallets": {"ts": ts, "wallets": {ADDR: {"balance": 2.0}}},
            "intervals": [{"from_ts": 50, "to_ts": ts,
                           "movements": [{"address": ADDR}]}],
        },
        "alert_state": {
            "baseline": {"ts": 50, "balances": {ADDR: 1.0}, "dust": [ADDR]},
            "rolling": {"ts": ts, "balances": {ADDR: 2.0}, "dust": []},
            "sent_event_ids": ["e1"],
            "last_sent": {"dump": ts},
            "rejected_signals": [{"reason": "x"}],
        },
    }
    slot.update(over)
    return slot


def _store(ts=100, **over):
    return {"updated_at": ts, "tokens": {MINT: _slot(ts, **over)}}


class BackupBytesTest(unittest.TestCase):
    def test_round_trip_gzip(self):
        store = _store()
        payload = hh.store_backup_bytes(store)
        self.assertEqual(payload[:2], b"\x1f\x8b")  # magic gzip
        self.assertEqual(hh.parse_store_backup(payload), store)

    def test_gzip_lebih_kecil_dari_json(self):
        store = {"updated_at": 1, "tokens": {
            "T%02d" % i: _slot(balances_marker=i) for i in range(30)}}
        payload = hh.store_backup_bytes(store)
        plain = len(json.dumps(store, separators=(",", ":")))
        self.assertLess(len(payload), plain)

    def test_payload_hanya_updated_at_dan_tokens(self):
        parsed = hh.parse_store_backup(
            hh.store_backup_bytes({"updated_at": 7, "tokens": {},
                                   "sampah": [1, 2, 3]}))
        self.assertEqual(parsed, {"updated_at": 7, "tokens": {}})

    def test_tokens_bukan_dict_jadi_kosong(self):
        parsed = hh.parse_store_backup(
            hh.store_backup_bytes({"updated_at": 1, "tokens": "rusak"}))
        self.assertEqual(parsed, {"updated_at": 1, "tokens": {}})

    def test_parse_toleran_json_polos(self):
        plain = json.dumps(_store()).encode("utf-8")
        self.assertEqual(hh.parse_store_backup(plain), _store())

    def test_parse_menolak_payload_rusak(self):
        for bad in (None, b"", b"bukan-gzip-atau-json", b"\x1f\x8b\x00\x01",
                    "string", 42, gzip.compress(b"not json")):
            self.assertIsNone(hh.parse_store_backup(bad), bad)

    def test_store_kosong_tetap_bisa_dibackup(self):
        payload = hh.store_backup_bytes(None)
        self.assertEqual(hh.parse_store_backup(payload),
                         {"updated_at": None, "tokens": {}})


class MergeStoresTest(unittest.TestCase):
    def test_points_union_dan_urut(self):
        local = _store(ts=100)
        remote = _store(ts=90)
        merged = hh.merge_stores(local, remote)["tokens"][MINT]
        self.assertEqual([p["ts"] for p in merged["points"]], [90, 100])

    def test_points_sama_tidak_dobel(self):
        merged = hh.merge_stores(_store(ts=100), _store(ts=100))
        self.assertEqual(len(merged["tokens"][MINT]["points"]), 1)

    def test_points_dibatasi_max_points(self):
        banyak = {"updated_at": 1, "tokens": {MINT: {
            "symbol": "TST",
            "points": [{"ts": t, "dust_count": t} for t in range(1, 200)]}}}
        merged = hh.merge_stores(banyak, _store(ts=1000))
        self.assertLessEqual(len(merged["tokens"][MINT]["points"]),
                             hh.MAX_POINTS)
        self.assertEqual(merged["tokens"][MINT]["points"][-1]["ts"], 1000)

    def test_baseline_paling_tua_menang(self):
        local = _store(ts=100)
        local["tokens"][MINT]["baseline"] = {"ts": 80, "dust_count": 9}
        remote = _store(ts=90)
        remote["tokens"][MINT]["baseline"] = {"ts": 50, "dust_count": 8}
        self.assertEqual(
            hh.merge_stores(local, remote)["tokens"][MINT]["baseline"]["ts"], 50)
        self.assertEqual(
            hh.merge_stores(remote, local)["tokens"][MINT]["baseline"]["ts"], 50)

    def test_latest_detail_paling_baru_menang(self):
        local = _store(ts=100)
        remote = _store(ts=90)
        merged = hh.merge_stores(remote, local)["tokens"][MINT]
        self.assertEqual(merged["latest_detail"]["ts"], 100)

    def test_cohort_dengan_balance_menang_lalu_frozen_at(self):
        kosong = _store(ts=100)
        kosong["tokens"][MINT]["cohort"] = {"frozen_at": 999, "balances": {}}
        berisi = _store(ts=90)
        merged = hh.merge_stores(kosong, berisi)["tokens"][MINT]
        self.assertEqual(merged["cohort"]["frozen_at"], 80)
        self.assertIn(ADDR, merged["cohort"]["balances"])

    def test_cohort_frozen_at_terbaru_menang_bila_dua_dua_isi(self):
        lama = _store(ts=100)
        lama["tokens"][MINT]["cohort"] = {"frozen_at": 10, "balances": {"A": 1}}
        baru = _store(ts=100)
        baru["tokens"][MINT]["cohort"] = {"frozen_at": 20, "balances": {"B": 2}}
        self.assertEqual(hh.merge_stores(lama, baru)["tokens"][MINT]
                         ["cohort"]["frozen_at"], 20)

    def test_alert_state_event_ids_union(self):
        local = _store(ts=100)
        local["tokens"][MINT]["alert_state"]["sent_event_ids"] = ["e1", "e2"]
        remote = _store(ts=90)
        remote["tokens"][MINT]["alert_state"]["sent_event_ids"] = ["e0", "e1"]
        state = hh.merge_stores(local, remote)["tokens"][MINT]["alert_state"]
        # union tanpa duplikat; urutan = insertion order (yang baru di belakang)
        self.assertEqual(sorted(state["sent_event_ids"]), ["e0", "e1", "e2"])
        self.assertEqual(state["sent_event_ids"], ["e1", "e2", "e0"])

    def test_alert_state_last_sent_max_per_kunci(self):
        local = _store(ts=100)
        local["tokens"][MINT]["alert_state"]["last_sent"] = {"dump": 100}
        remote = _store(ts=90)
        remote["tokens"][MINT]["alert_state"]["last_sent"] = {"dump": 50,
                                                              "acc": 70}
        state = hh.merge_stores(local, remote)["tokens"][MINT]["alert_state"]
        self.assertEqual(state["last_sent"]["dump"], 100)
        self.assertEqual(state["last_sent"]["acc"], 70)

    def test_alert_state_snapshot_terbaru_menang(self):
        local = _store(ts=100)
        remote = _store(ts=90)
        state = hh.merge_stores(remote, local)["tokens"][MINT]["alert_state"]
        self.assertEqual(state["rolling"]["ts"], 100)
        self.assertEqual(state["baseline"]["ts"], 50)

    def test_alert_state_dibatasi_max_sent_event_ids(self):
        from telegram_alerts import MAX_SENT_EVENT_IDS
        local = _store(ts=100)
        local["tokens"][MINT]["alert_state"]["sent_event_ids"] = [
            "L%03d" % i for i in range(MAX_SENT_EVENT_IDS)]
        remote = _store(ts=90)
        remote["tokens"][MINT]["alert_state"]["sent_event_ids"] = [
            "R%03d" % i for i in range(MAX_SENT_EVENT_IDS)]
        state = hh.merge_stores(local, remote)["tokens"][MINT]["alert_state"]
        self.assertEqual(len(state["sent_event_ids"]), MAX_SENT_EVENT_IDS)

    def test_chronology_interval_union_dan_movements_terlengkap(self):
        local = _store(ts=100)
        local["tokens"][MINT]["chronology"]["intervals"] = [
            {"from_ts": 50, "to_ts": 100, "movements": []},
            {"from_ts": 100, "to_ts": 150, "movements": [{"address": "B"}]},
        ]
        remote = _store(ts=90)
        remote["tokens"][MINT]["chronology"]["intervals"] = [
            {"from_ts": 50, "to_ts": 100, "movements": [{"address": "A"}]},
            {"from_ts": 10, "to_ts": 40, "movements": []},
        ]
        chrono = hh.merge_stores(local, remote)["tokens"][MINT]["chronology"]
        keys = [(i["from_ts"], i["to_ts"]) for i in chrono["intervals"]]
        self.assertEqual(keys, [(10, 40), (50, 100), (100, 150)])
        self.assertEqual(len(chrono["intervals"][1]["movements"]), 1)

    def test_chronology_snapshot_dengan_peta_wallet_menang(self):
        tanpa = _store(ts=100)
        tanpa["tokens"][MINT]["chronology"]["latest_wallets"] = {
            "ts": 999, "wallets": {}}
        dengan = _store(ts=90)
        merged = hh.merge_stores(tanpa, dengan)["tokens"][MINT]["chronology"]
        self.assertIn(ADDR, merged["latest_wallets"]["wallets"])

    def test_chronology_interval_dibatasi(self):
        local = _store(ts=100)
        local["tokens"][MINT]["chronology"]["intervals"] = [
            {"from_ts": i, "to_ts": i + 1} for i in range(40)]
        merged = hh.merge_stores(local, _store(ts=90))["tokens"][MINT]
        self.assertLessEqual(len(merged["chronology"]["intervals"]),
                             hh.MAX_CHRONOLOGY_INTERVALS)

    def test_token_baru_dari_backup_ikut_terbawa(self):
        local = _store(ts=100)
        remote = {"updated_at": 90, "tokens": {"OLD": _slot(90)}}
        merged = hh.merge_stores(local, remote)
        self.assertEqual(sorted(merged["tokens"]), sorted([MINT, "OLD"]))

    def test_updated_at_max(self):
        self.assertEqual(hh.merge_stores(_store(ts=100),
                                         _store(ts=250))["updated_at"], 250)
        self.assertIsNone(hh.merge_stores({"tokens": {}},
                                          {"tokens": {}})["updated_at"])

    def test_argumen_belakang_menang_saat_seri(self):
        a = _store(ts=100)
        a["tokens"][MINT]["latest_detail"] = {"ts": 100, "dust_count": 1}
        b = _store(ts=100)
        b["tokens"][MINT]["latest_detail"] = {"ts": 100, "dust_count": 2}
        self.assertEqual(hh.merge_stores(a, b)["tokens"][MINT]
                         ["latest_detail"]["dust_count"], 2)
        self.assertEqual(hh.merge_stores(b, a)["tokens"][MINT]
                         ["latest_detail"]["dust_count"], 1)

    def test_input_tidak_dimutasi(self):
        local, remote = _store(ts=100), _store(ts=90)
        before_local, before_remote = repr(local), repr(remote)
        hh.merge_stores(local, remote)
        self.assertEqual(repr(local), before_local)
        self.assertEqual(repr(remote), before_remote)

    def test_input_rusak_ditoleransi(self):
        for bad in (None, {}, "x", 7, {"tokens": None},
                    {"tokens": {MINT: "bukan-dict"}}, {"tokens": {"": {}}}):
            merged = hh.merge_stores(bad, _store(ts=100))
            self.assertIsInstance(merged.get("tokens"), dict)
        self.assertEqual(hh.merge_stores()["tokens"], {})


class PruneStoreTest(unittest.TestCase):
    def _big_store(self):
        return {"updated_at": 1, "tokens": {"B%02d" % i: {
            "symbol": "B%02d" % i,
            "points": [{"ts": t, "dust_count": t,
                        "buckets": {">$0-$10": t, "$10-$100": t}}
                       for t in range(84)],
            "baseline": {"ts": 1, "depth": {"buckets": [{"label": "x"}] * 7}},
            "latest_detail": {"ts": 2, "depth": {"buckets": [{"label": "y"}] * 7}},
            "chronology": {
                "baseline_wallets": {"ts": 1, "wallets": {
                    "W%03d%s" % (w, ADDR): {"balance": w} for w in range(200)}},
                "latest_wallets": {"ts": 2, "wallets": {
                    "W%03d%s" % (w, ADDR): {"balance": w} for w in range(200)}},
                "intervals": [{"from_ts": k, "to_ts": k + 1, "movements": [
                    {"address": "W%03d%s" % (m, ADDR), "kind": "dust_grew_out"}
                    for m in range(20)]} for k in range(12)]},
        } for i in range(12)}}

    def test_di_bawah_budget_tidak_dipangkas(self):
        store = _store()
        pruned, dropped = hh.prune_store_for_backup(store, 10 ** 7)
        self.assertEqual(dropped, [])
        self.assertIs(pruned, store)

    def test_pangkas_sampai_budget(self):
        store = self._big_store()
        full = len(hh.store_backup_bytes(store))
        pruned, dropped = hh.prune_store_for_backup(store, full // 3)
        self.assertLessEqual(len(hh.store_backup_bytes(pruned)), full // 3)
        self.assertTrue(dropped)
        # baseline scan FULL dipertahankan sampai langkah terakhir
        self.assertTrue(all(slot.get("baseline")
                            for slot in pruned["tokens"].values()))

    def test_urutan_pembuangan(self):
        store = self._big_store()
        pruned, dropped = hh.prune_store_for_backup(store, 1)
        self.assertEqual(dropped[:2], ["chronology.movements interval lama",
                                       "chronology.intervals di luar 6 terbaru"])
        self.assertEqual(dropped[-1], "latest_detail")
        self.assertEqual(len(pruned["tokens"]["B00"]["chronology"]
                             ["intervals"]), 6)
        self.assertEqual(pruned["tokens"]["B00"]["chronology"]
                         ["baseline_wallets"]["wallets"], {})
        self.assertEqual(len(pruned["tokens"]["B00"]["points"]), 42)
        self.assertNotIn("buckets", pruned["tokens"]["B00"]["points"][0])

    defInput = None

    def test_store_rusak(self):
        pruned, dropped = hh.prune_store_for_backup(None, 1)
        self.assertEqual(pruned, {"updated_at": None, "tokens": {}})
        self.assertEqual(dropped, [])


@mock.patch.dict(os.environ, {"HOLDER_STORE_BACKUP": "1"})
class PublishHolderHistoryTest(unittest.TestCase):
    def setUp(self):
        hh.reset_durable_cache()

    def test_push_false_tidak_menyentuh_transport(self):
        with mock.patch("holder_status.push_store_backup") as push:
            result = hh.publish_holder_history(_store(), push=False)
        push.assert_not_called()
        self.assertIsNone(result["ok"])
        self.assertFalse(result["pushed"])
        self.assertFalse(result["saved_local"])

    def test_push_true_mengirim_gzip(self):
        with mock.patch("holder_status.push_store_backup",
                        return_value=True) as push:
            result = hh.publish_holder_history(_store(), push=True)
        self.assertTrue(result["pushed"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["pruned"], [])
        payload, message = push.call_args.args
        self.assertEqual(hh.parse_store_backup(payload), _store())
        self.assertIn("holder-history: backup", message)
        self.assertIn("[skip ci]", message)
        self.assertGreater(result["bytes"], 0)

    def test_message_bisa_disesuaikan(self):
        with mock.patch("holder_status.push_store_backup",
                        return_value=True) as push:
            hh.publish_holder_history(_store(), message="custom msg")
        self.assertEqual(push.call_args.args[1], "custom msg")

    def test_kelebihan_budget_memangkas_dan_menandai(self):
        big = {"updated_at": 1, "tokens": {"B%02d" % i: {
            "symbol": "B", "points": [{"ts": t, "buckets": {"a": t}}
                                      for t in range(84)],
            "baseline": {"ts": 1}, "latest_detail": {"ts": 2},
            "chronology": {"intervals": [{"from_ts": k, "to_ts": k + 1,
                                          "movements": [{"address": ADDR}]}
                                         for k in range(12)]},
        } for i in range(8)}}
        full = len(hh.store_backup_bytes(big))
        lantai = len(hh.store_backup_bytes(
            hh.prune_store_for_backup(big, 1)[0]))
        budget = max(lantai, full // 3)
        with mock.patch("holder_status.push_store_backup",
                        return_value=True) as push, \
                mock.patch.object(hh, "MAX_BACKUP_BYTES", budget):
            result = hh.publish_holder_history(big, push=True)
        self.assertTrue(result["pruned"])
        self.assertLessEqual(len(push.call_args.args[0]), budget)
        self.assertLess(result["bytes"], full)
        self.assertFalse(result["over_budget"])

    def test_bila_tetap_lebih_budget_ditandai(self):
        with mock.patch("holder_status.push_store_backup",
                        return_value=True) as push, \
                mock.patch.object(hh, "MAX_BACKUP_BYTES", 1):
            result = hh.publish_holder_history(_store(), push=True)
        self.assertTrue(result["over_budget"])
        self.assertTrue(push.called)  # tetap dibackup walau melebihi budget

    def test_transport_gagal_tidak_melempar(self):
        with mock.patch("holder_status.push_store_backup", return_value=False):
            result = hh.publish_holder_history(_store(), push=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "github push failed")

    def test_transport_melempar_tetap_aman(self):
        with mock.patch("holder_status.push_store_backup",
                        side_effect=RuntimeError("boom")):
            result = hh.publish_holder_history(_store(), push=True)
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])

    def test_kill_switch_env(self):
        with mock.patch.dict(os.environ, {"HOLDER_STORE_BACKUP": "0"}), \
                mock.patch("holder_status.push_store_backup") as push:
            result = hh.publish_holder_history(_store(), push=True)
        push.assert_not_called()
        self.assertIn("disabled", result["error"])

    def test_save_local_menulis_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "holder_history.json")
            result = hh.publish_holder_history(_store(), push=False,
                                               save_local=True, path=path)
            self.assertTrue(result["saved_local"])
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), _store())

    def test_default_tidak_menulis_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "holder_history.json")
            hh.publish_holder_history(_store(), push=False, path=path)
            self.assertFalse(os.path.exists(path))


@mock.patch.dict(os.environ, {"HOLDER_STORE_BACKUP": "1"})
class PullHolderHistoryTest(unittest.TestCase):
    def setUp(self):
        hh.reset_durable_cache()

    def test_pull_mengembalikan_store(self):
        with mock.patch("holder_status.pull_store_backup",
                        return_value=hh.store_backup_bytes(_store())):
            self.assertEqual(hh.pull_holder_history(), _store())

    def test_pull_tidak_ada_backup(self):
        with mock.patch("holder_status.pull_store_backup", return_value=None):
            self.assertIsNone(hh.pull_holder_history())

    def test_pull_payload_rusak(self):
        with mock.patch("holder_status.pull_store_backup",
                        return_value=b"rusak"):
            self.assertIsNone(hh.pull_holder_history())

    def test_pull_melempar_tetap_aman(self):
        with mock.patch("holder_status.pull_store_backup",
                        side_effect=RuntimeError("network")):
            self.assertIsNone(hh.pull_holder_history())

    def test_pull_dimatikan_kill_switch(self):
        with mock.patch.dict(os.environ, {"HOLDER_STORE_BACKUP": "off"}), \
                mock.patch("holder_status.pull_store_backup") as pull:
            self.assertIsNone(hh.pull_holder_history())
        pull.assert_not_called()


class DurableLoaderTest(unittest.TestCase):
    def setUp(self):
        hh.reset_durable_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "holder_history.json")

    def tearDown(self):
        hh.reset_durable_cache()
        self.tmp.cleanup()

    def _local(self, store):
        return mock.patch.object(hh, "load_holder_history",
                                 return_value=store)

    def test_remote_dan_lokal_digabung_lokal_menang(self):
        remote = _store(ts=90)
        local = _store(ts=100)
        local["tokens"][MINT]["latest_detail"] = {"ts": 100, "dust_count": 99}
        with self._local(local), \
                mock.patch.object(hh, "pull_holder_history",
                                  return_value=remote):
            merged = hh.load_durable_holder_history()
        self.assertEqual(merged["tokens"][MINT]["latest_detail"]
                         ["dust_count"], 99)
        self.assertEqual([p["ts"] for p in merged["tokens"][MINT]["points"]],
                         [90, 100])

    def test_cache_ttl_mencegah_pull_berulang(self):
        with self._local(_store()), \
                mock.patch.object(hh, "pull_holder_history",
                                  return_value=_store(ts=90)) as pull:
            hh.load_durable_holder_history()
            hh.load_durable_holder_history()
            self.assertEqual(pull.call_count, 1)
            hh.load_durable_holder_history(force=True)
            self.assertEqual(pull.call_count, 2)

    def test_ttl_habis_pull_lagi(self):
        with self._local(_store()), \
                mock.patch.object(hh, "pull_holder_history",
                                  return_value=_store(ts=90)) as pull:
            hh.load_durable_holder_history(ttl=60)
            hh._DURABLE_CACHE["ts"] -= 61
            hh.load_durable_holder_history(ttl=60)
            self.assertEqual(pull.call_count, 2)

    def test_pull_gagal_pakai_cache_lama(self):
        with self._local(_store()), \
                mock.patch.object(hh, "pull_holder_history",
                                  return_value=_store(ts=90)):
            first = hh.load_durable_holder_history()
        with self._local(_store()), \
                mock.patch.object(hh, "pull_holder_history", return_value=None):
            second = hh.load_durable_holder_history(force=True)
        self.assertEqual(first, second)

    def test_tanpa_backup_hanya_lokal(self):
        local = _store()
        with self._local(local), \
                mock.patch.object(hh, "pull_holder_history", return_value=None):
            self.assertEqual(hh.load_durable_holder_history(), local)

    def test_kill_switch_memakai_lokal_saja(self):
        with mock.patch.dict(os.environ, {"HOLDER_STORE_BACKUP": "0"}), \
                self._local(_store()), \
                mock.patch("holder_status.pull_store_backup") as pull:
            merged = hh.load_durable_holder_history()
        pull.assert_not_called()
        self.assertEqual(merged, _store())


class SeedFromSlimStatusTest(unittest.TestCase):
    """seed_from_status harus mengenali snapshot ramping vs format lama."""

    def test_alert_state_ringkas_tidak_menimpa_store(self):
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "alert_state": {"summary": True,
                            "baseline": {"ts": 1, "balances": 3, "dust": 1},
                            "rolling": {"ts": 2, "balances": 3, "dust": 0},
                            "sent_event_ids": 2, "last_sent": {"dump": 2}},
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        self.assertNotIn("alert_state", store["tokens"][MINT])

    def test_alert_state_format_lama_tetap_dipulihkan(self):
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "alert_state": {"rolling": {"ts": 5, "balances": {ADDR: 1.0}},
                            "sent_event_ids": ["e1"]},
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        state = store["tokens"][MINT]["alert_state"]
        self.assertIn(ADDR, state["rolling"]["balances"])
        self.assertEqual(state["sent_event_ids"], ["e1"])

    def test_alert_state_ringkasan_tanpa_flag_tetap_dilewati(self):
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "alert_state": {"baseline": {"ts": 1, "balances": 3, "dust": 1},
                            "rolling": {"ts": 2, "balances": 3, "dust": 0},
                            "sent_event_ids": 2},
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        self.assertNotIn("alert_state", store["tokens"][MINT])

    def test_alert_state_lama_tanpa_baseline_tetap_dipulihkan(self):
        # id dedup alert harus selamat meski peta balance baseline belum ada
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "alert_state": {"rolling": {"ts": 5, "balances": {}},
                            "sent_event_ids": ["e9"],
                            "last_sent": {"dump": 5}},
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        state = store["tokens"][MINT]["alert_state"]
        self.assertEqual(state["sent_event_ids"], ["e9"])
        self.assertEqual(state["last_sent"]["dump"], 5)

    def test_cohort_ringkas_tidak_menimpa_store(self):
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "cohort": {"summary": True, "frozen_at": 5, "wallets": 2},
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        self.assertEqual(store["tokens"][MINT].get("cohort") or {}, {})

    def test_chronology_ringkas_tidak_membocorkan_jumlah_ke_peta(self):
        remote = {"tokens": {MINT: {
            "symbol": "TST",
            "chronology": {
                "baseline_wallets": {"ts": 1, "wallets": 0, "holder_count": 5},
                "latest_wallets": {"ts": 2, "wallets": 0, "holder_count": 6},
                "intervals": [{"from_ts": 1, "to_ts": 2, "movements": []}],
            },
        }}}
        store = hh.seed_from_status(hh.empty_store(), remote)
        chrono = store["tokens"][MINT]["chronology"]
        for key in ("baseline_wallets", "latest_wallets"):
            wallets = (chrono.get(key) or {}).get("wallets")
            self.assertIsInstance(wallets, dict)
        self.assertEqual(len(chrono.get("intervals") or []), 1)


class SlimSnapshotTest(unittest.TestCase):
    def test_snapshot_tidak_membawa_peta_wallet(self):
        store = _store()
        analyses = {MINT: {"symbol": "TST", "marketcap": 100_000.0,
                           "price": 0.01, "analyzed_at": 100,
                           "holders": {"dust_count": 10, "dust_pct_mc": 1.1,
                                       "real_count": 5,
                                       "mid": {"count": 3, "pct_mc": 40.0,
                                               "balances": {ADDR: 1.0}}}}}
        status = hs.snapshot_status(analyses, {MINT: {"symbol": "TST"}},
                                    history_store=store)
        token = status["tokens"][MINT]
        # peta wallet alert & kohort TIDAK ikut snapshot (pindah ke backup .gz)
        self.assertTrue(token["alert_state"]["summary"])
        self.assertEqual(token["alert_state"]["baseline"]["balances"], 1)
        self.assertEqual(token["alert_state"]["rolling"]["balances"], 1)
        self.assertEqual(token["alert_state"]["sent_event_ids"], 1)
        self.assertEqual(token["cohort"]["wallets"], 1)
        self.assertNotIn(ADDR, json.dumps(token["alert_state"]))
        self.assertNotIn(ADDR, json.dumps(token["cohort"]))
        chrono = token["chronology"]
        self.assertEqual(chrono["baseline_wallets"]["wallets"], 1)
        self.assertEqual(chrono["latest_wallets"]["wallets"], 1)
        self.assertNotIn(ADDR, json.dumps(chrono["baseline_wallets"]))
        self.assertNotIn(ADDR, json.dumps(chrono["latest_wallets"]))
        # movements tetap ada sebagai sampel terbatas (dipakai halaman Holder)
        self.assertLessEqual(len(chrono["intervals"]), 12)
        for interval in chrono["intervals"]:
            self.assertLessEqual(len(interval.get("movements") or []), 20)
        # angka ringkas tetap benar
        self.assertEqual(token["holders"]["dust_pct_mc"], 1.1)
        self.assertEqual(len(token["history"]), 1)

    def test_snapshot_ramping_jauh_lebih_kecil(self):
        store = _store()
        analyses = {MINT: {"symbol": "TST", "marketcap": 100_000.0,
                           "price": 0.01, "analyzed_at": 100,
                           "holders": {"dust_count": 10, "dust_pct_mc": 1.1}}}
        slim = hs.snapshot_status(analyses, {}, history_store=store)
        # versi "gemuk" = payload yang sama dengan peta wallet disertakan
        fat = json.loads(json.dumps(slim))
        fat["tokens"][MINT]["alert_state"] = store["tokens"][MINT]["alert_state"]
        fat["tokens"][MINT]["cohort"] = store["tokens"][MINT]["cohort"]
        self.assertLess(len(json.dumps(slim)), len(json.dumps(fat)))


if __name__ == "__main__":
    unittest.main()
