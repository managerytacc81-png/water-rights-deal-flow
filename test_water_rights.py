"""
Unit tests for Western Water Rights Deal-Flow Engine
"""

import os
import json
import csv
import unittest
from water_rights_pipeline import (
    WaterRight,
    ScoredWaterProspect,
    WaterRightsScorer,
    WaterLeadExporter,
    CURATED_WATER_RIGHTS,
    WATER_MARKET_BENCHMARKS
)

class TestWaterRightsScorer(unittest.TestCase):
    def test_seniority_score_pre_1865(self):
        score = WaterRightsScorer.calculate_seniority_score("1860-06-01")
        self.assertEqual(score, 100.0)

    def test_seniority_score_mid_range(self):
        score_1885 = WaterRightsScorer.calculate_seniority_score("1885-05-01")
        score_1935 = WaterRightsScorer.calculate_seniority_score("1935-01-01")
        self.assertGreater(score_1885, score_1935)

    def test_proximity_score_decay(self):
        close_score = WaterRightsScorer.calculate_proximity_score(1.5)
        mid_score = WaterRightsScorer.calculate_proximity_score(4.5)
        far_score = WaterRightsScorer.calculate_proximity_score(25.0)

        self.assertEqual(close_score, 100.0)
        self.assertEqual(mid_score, 85.0)
        self.assertEqual(far_score, 25.0)

    def test_composite_deal_score(self):
        # 100 seniority, 100 proximity, 60 AF volume -> 40 + 40 + 20 = 100
        score = WaterRightsScorer.calculate_deal_score(100.0, 100.0, 60.0)
        self.assertAlmostEqual(score, 100.0)

    def test_evaluate_right(self):
        sample = CURATED_WATER_RIGHTS[0]
        prospect = WaterRightsScorer.evaluate_right(sample)

        self.assertEqual(prospect.wdid, "0100502")
        self.assertGreaterEqual(prospect.deal_score, 80.0)
        self.assertEqual(prospect.deal_priority, "TIER_1_URGENT")
        self.assertGreater(prospect.estimated_asset_value, 1000000.0)
        self.assertAlmostEqual(prospect.finder_referral_fee_est, prospect.potential_broker_commission * 0.25)

class TestWaterLeadExporter(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/water_test"
        os.makedirs(self.test_dir, exist_ok=True)
        self.csv_path = os.path.join(self.test_dir, "test_water.csv")
        self.json_path = os.path.join(self.test_dir, "test_water.json")

    def tearDown(self):
        for f in [self.csv_path, self.json_path]:
            if os.path.exists(f):
                os.remove(f)

    def test_export_prospects_csv_and_json(self):
        prospects = [WaterRightsScorer.evaluate_right(r) for r in CURATED_WATER_RIGHTS]
        WaterLeadExporter.export_prospects_csv(prospects, self.csv_path)
        WaterLeadExporter.export_prospects_json(prospects, self.json_path)

        self.assertTrue(os.path.exists(self.csv_path))
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), len(prospects))
            self.assertIn("wdid", reader.fieldnames)
            self.assertIn("finder_referral_fee_est", reader.fieldnames)

        self.assertTrue(os.path.exists(self.json_path))
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["total_prospects"], len(prospects))

    def test_generate_broker_referral_packet(self):
        prospects = [WaterRightsScorer.evaluate_right(r) for r in CURATED_WATER_RIGHTS]
        packet = WaterLeadExporter.generate_broker_referral_packet_markdown(prospects)

        self.assertIn("Western Water Rights Off-Market Seller Deal-Flow Packet", packet)
        self.assertIn("WATER RIGHTS REFERRAL & CO-BROKERAGE AGREEMENT", packet)
        self.assertIn("C.R.S. 12-61-203.5", packet)
        self.assertIn("Robert Ketler", packet)

if __name__ == "__main__":
    unittest.main()
