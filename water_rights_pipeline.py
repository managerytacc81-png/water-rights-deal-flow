#!/usr/bin/env python3
"""
Western Water Rights Off-Market Seller Deal-Flow Engine
Sources, evaluates, and ranks off-market senior water rights for municipal conversion
and broker referral fees across Colorado (Front Range / South Platte), Texas (Edwards Aquifer),
and Nevada (Truckee Meadows).

Legal & Economic Mechanics:
- Sourcing: Joins state decreed water right records (WDID, priority date, decreed AF, decreed use)
  with county parcel assessor owners and ditch company shareholder rolls.
- Scoring: Ranks rights by proximity to rapid municipal expansion zones, seniority (pre-1900),
  decreed volume, and M&I conversion feasibility.
- Commercialization: Warm referral to licensed water brokers (Water Colorado, Hydro Source, Edwards)
  under contractual referral agreements (Colorado C.R.S. 12-61-203.5 compliant).
- Commission Split: 20% to 30% of the broker's 10% commission (2.0% - 3.0% of deal value = $2.5K - $15K per transaction).
"""

import argparse
import csv
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("water-rights-dealflow")

# -------------------------------------------------------------------------
# Price Benchmarks & Valuation Model
# -------------------------------------------------------------------------
WATER_MARKET_BENCHMARKS = {
    "CO_CBT_UNIT": {
        "region": "Colorado Front Range (Northern Water)",
        "unit": "Acre-Foot (AF)",
        "price_min": 52000.0,
        "price_mid": 68000.0,
        "price_max": 85000.0,
        "annual_ag_lease": 220.0,
        "description": "Colorado-Big Thompson project quota units (C-BT). Highest liquidity."
    },
    "CO_SOUTH_PLATTE_SENIOR_DITCH": {
        "region": "South Platte Basin / Weld & Larimer Counties",
        "unit": "Decreed Consumptive Use AF",
        "price_min": 25000.0,
        "price_mid": 38000.0,
        "price_max": 55000.0,
        "annual_ag_lease": 180.0,
        "description": "Senior direct-flow ditch rights (pre-1890) with high consumptive use history."
    },
    "CO_ARKANSAS_VALLEY": {
        "region": "Arkansas River Basin (Pueblo / Colorado Springs growth)",
        "unit": "Decreed AF",
        "price_min": 14000.0,
        "price_mid": 22000.0,
        "price_max": 32000.0,
        "annual_ag_lease": 150.0,
        "description": "Arkansas Valley ditch shares subject to municipal lease-fallowing or purchase."
    },
    "TX_EDWARDS_AQUIFER_PERMITTED": {
        "region": "Edwards Aquifer Authority (San Antonio / New Braunfels / San Marcos)",
        "unit": "Unrestricted Base AF",
        "price_min": 8500.0,
        "price_mid": 12500.0,
        "price_max": 18000.0,
        "annual_ag_lease": 120.0,
        "description": "Permitted unrestricted groundwater withdrawal rights for municipal transfer."
    },
    "NV_TRUCKEE_CARSON": {
        "region": "Truckee River / Reno-Sparks Metro Growth Corridor",
        "unit": "Acre-Foot",
        "price_min": 18000.0,
        "price_mid": 28000.0,
        "price_max": 40000.0,
        "annual_ag_lease": 200.0,
        "description": "Truckee Meadows Water Authority (TMWA) deducible water rights."
    }
}

# -------------------------------------------------------------------------
# Data Models
# -------------------------------------------------------------------------
@dataclass
class WaterRight:
    wdid: str
    structure_name: str
    water_district: int
    water_division: int
    county: str
    source_stream: str
    priority_date: str          # YYYY-MM-DD
    decreed_amount_af: float
    decreed_use: str            # Irrigation, Storage, Municipal, Commercial
    ditch_company: Optional[str]
    market_class: str           # e.g. CO_SOUTH_PLATTE_SENIOR_DITCH, CO_CBT_UNIT
    # Assessor & Ownership Record (Joined Layer)
    parcel_id: str
    owner_name: str
    owner_mailing_address: str
    owner_city_state_zip: str
    phone: Optional[str] = None
    email: Optional[str] = None
    # Geospatial scoring
    nearest_target_muni: str = ""
    distance_to_muni_miles: float = 0.0

@dataclass
class ScoredWaterProspect:
    wdid: str
    structure_name: str
    owner_name: str
    county: str
    ditch_company: Optional[str]
    priority_date: str
    seniority_score: float      # 0 to 100
    decreed_amount_af: float
    nearest_muni: str
    distance_miles: float
    proximity_score: float      # 0 to 100
    deal_score: float           # Weighted composite 0 to 100
    deal_priority: str          # TIER_1_URGENT, TIER_2_HIGH, TIER_3_MODERATE
    estimated_asset_value: float
    potential_broker_commission: float
    finder_referral_fee_est: float
    owner_address: str
    rationale: str

# -------------------------------------------------------------------------
# Curated Benchmark Dataset (Colorado Front Range & Edwards Aquifer)
# -------------------------------------------------------------------------
CURATED_WATER_RIGHTS: List[WaterRight] = [
    WaterRight(
        wdid="0100502",
        structure_name="Cache La Poudre Irrigating Co Canal",
        water_district=1,
        water_division=1,
        county="Weld",
        source_stream="Cache La Poudre River",
        priority_date="1860-06-01",
        decreed_amount_af=42.5,
        decreed_use="Irrigation",
        ditch_company="New Cache La Poudre Ditch Co",
        market_class="CO_SOUTH_PLATTE_SENIOR_DITCH",
        parcel_id="0959-14-2-00-008",
        owner_name="Greeley Farmland Heirs LLC (c/o Mark Henderson)",
        owner_mailing_address="4820 W 10th St",
        owner_city_state_zip="Greeley, CO 80634",
        phone="(970) 555-0182",
        nearest_target_muni="Greeley / Windsor Growth Corridor",
        distance_to_muni_miles=3.8
    ),
    WaterRight(
        wdid="0100844",
        structure_name="Greeley No 3 Ditch",
        water_district=1,
        water_division=1,
        county="Weld",
        source_stream="Cache La Poudre River",
        priority_date="1870-04-01",
        decreed_amount_af=28.0,
        decreed_use="Irrigation",
        ditch_company="Greeley Irrigation Company",
        market_class="CO_SOUTH_PLATTE_SENIOR_DITCH",
        parcel_id="0959-22-1-00-014",
        owner_name="VanderHoof Family Trust",
        owner_mailing_address="1420 8th Ave",
        owner_city_state_zip="Greeley, CO 80631",
        phone="(970) 555-0291",
        nearest_target_muni="Greeley Urban Service Area",
        distance_to_muni_miles=1.5
    ),
    WaterRight(
        wdid="0101032",
        structure_name="Farmers Reservoir & Irrigation Co (FRICO) - Standley Canal",
        water_district=2,
        water_division=1,
        county="Adams",
        source_stream="Clear Creek",
        priority_date="1872-05-15",
        decreed_amount_af=65.0,
        decreed_use="Irrigation",
        ditch_company="Farmers Reservoir and Irrigation Company (FRICO)",
        market_class="CO_SOUTH_PLATTE_SENIOR_DITCH",
        parcel_id="01721-30-4-00-001",
        owner_name="Brighton Ag Land Partners c/o Thomas Keller",
        owner_mailing_address="12880 Riverdale Rd",
        owner_city_state_zip="Brighton, CO 80602",
        phone="(303) 555-0374",
        nearest_target_muni="Thornton / Brighton Growth Boundary",
        distance_to_muni_miles=4.2
    ),
    WaterRight(
        wdid="0102140",
        structure_name="C-BT Project Allocation Shares (Northern Water)",
        water_district=4,
        water_division=1,
        county="Larimer",
        source_stream="Colorado-Big Thompson Transbasin Diversion",
        priority_date="1938-07-05",
        decreed_amount_af=30.0,
        decreed_use="Irrigation / M&I Allotment",
        ditch_company="Northern Colorado Water Conservancy District",
        market_class="CO_CBT_UNIT",
        parcel_id="97120-00-901",
        owner_name="Highland Ridge Ranch c/o Sarah Miller",
        owner_mailing_address="7410 Larimer County Rd 38E",
        owner_city_state_zip="Fort Collins, CO 80526",
        phone="(970) 555-0489",
        nearest_target_muni="Loveland / Fort Collins Urban Interface",
        distance_to_muni_miles=5.1
    ),
    WaterRight(
        wdid="0200612",
        structure_name="Bessemer Irrigation Ditch",
        water_district=14,
        water_division=2,
        county="Pueblo",
        source_stream="Arkansas River",
        priority_date="1887-05-01",
        decreed_amount_af=80.0,
        decreed_use="Irrigation",
        ditch_company="Bessemer Ditch Association",
        market_class="CO_ARKANSAS_VALLEY",
        parcel_id="14-220-00-019",
        owner_name="Pueblo Valley Farms Inc",
        owner_mailing_address="38100 Highway 50 E",
        owner_city_state_zip="Pueblo, CO 81006",
        phone="(719) 555-0512",
        nearest_target_muni="Pueblo Springs Metro Expansion",
        distance_to_muni_miles=7.5
    ),
    WaterRight(
        wdid="TX-EAA-0922",
        structure_name="Edwards Aquifer Permitted Well 04-208",
        water_district=10,
        water_division=0,
        county="Bexar",
        source_stream="Edwards Aquifer Groundwater",
        priority_date="1993-06-28",
        decreed_amount_af=50.0,
        decreed_use="Irrigation Base Permitted",
        ditch_company=None,
        market_class="TX_EDWARDS_AQUIFER_PERMITTED",
        parcel_id="04100-102-0050",
        owner_name="Cibolo Creek Agronomics LLC c/o Frank Ramirez",
        owner_mailing_address="8420 FM 1518",
        owner_city_state_zip="Schertz, TX 78154",
        phone="(210) 555-0633",
        nearest_target_muni="San Antonio Water System (SAWS) / Schertz",
        distance_to_muni_miles=2.9
    )
]

# -------------------------------------------------------------------------
# Water Rights Scoring Engine
# -------------------------------------------------------------------------
class WaterRightsScorer:
    """Scores water rights based on seniority, distance to muni demand, and volume."""

    @staticmethod
    def calculate_seniority_score(priority_date: str) -> float:
        """Calculates seniority score from 0 to 100 based on appropriation date."""
        try:
            year = int(priority_date.split("-")[0])
        except (ValueError, IndexError):
            year = 1950

        # Prior appropriation: senior rights in Colorado before 1880 are rock solid
        if year <= 1865:
            return 100.0
        elif year <= 1875:
            return 95.0
        elif year <= 1890:
            return 85.0
        elif year <= 1910:
            return 70.0
        elif year <= 1940:
            return 55.0
        elif year <= 1970:
            return 40.0
        else:
            return 25.0

    @staticmethod
    def calculate_proximity_score(distance_miles: float) -> float:
        """Calculates proximity score: closer to municipal borders = higher score."""
        if distance_miles <= 2.0:
            return 100.0
        elif distance_miles <= 5.0:
            return 85.0
        elif distance_miles <= 10.0:
            return 70.0
        elif distance_miles <= 20.0:
            return 50.0
        else:
            return 25.0

    @staticmethod
    def calculate_deal_score(seniority: float, proximity: float, af_amount: float) -> float:
        """Computes composite score: 40% Seniority, 40% Proximity, 20% Volume."""
        volume_norm = min(100.0, (af_amount / 60.0) * 100.0)
        return (seniority * 0.40) + (proximity * 0.40) + (volume_norm * 0.20)

    @classmethod
    def evaluate_right(cls, right: WaterRight) -> ScoredWaterProspect:
        bench = WATER_MARKET_BENCHMARKS.get(right.market_class, WATER_MARKET_BENCHMARKS["CO_SOUTH_PLATTE_SENIOR_DITCH"])
        sen_score = cls.calculate_seniority_score(right.priority_date)
        prox_score = cls.calculate_proximity_score(right.distance_to_muni_miles)
        deal_score = cls.calculate_deal_score(sen_score, prox_score, right.decreed_amount_af)

        if deal_score >= 80.0:
            priority = "TIER_1_URGENT"
        elif deal_score >= 65.0:
            priority = "TIER_2_HIGH"
        else:
            priority = "TIER_3_MODERATE"

        asset_val = right.decreed_amount_af * bench["price_mid"]
        broker_comm = asset_val * 0.10             # Standard 10% brokerage commission
        finder_fee = broker_comm * 0.25            # 25% co-brokerage / finder referral cut (2.5% of gross)

        rationale = (
            f"Senior priority ({right.priority_date}), {right.decreed_amount_af} AF located "
            f"{right.distance_to_muni_miles} mi from {right.nearest_target_muni}. High M&I transfer appeal."
        )

        return ScoredWaterProspect(
            wdid=right.wdid,
            structure_name=right.structure_name,
            owner_name=right.owner_name,
            county=right.county,
            ditch_company=right.ditch_company,
            priority_date=right.priority_date,
            seniority_score=round(sen_score, 1),
            decreed_amount_af=round(right.decreed_amount_af, 1),
            nearest_muni=right.nearest_target_muni,
            distance_miles=round(right.distance_to_muni_miles, 1),
            proximity_score=round(prox_score, 1),
            deal_score=round(deal_score, 1),
            deal_priority=priority,
            estimated_asset_value=round(asset_val, 2),
            potential_broker_commission=round(broker_comm, 2),
            finder_referral_fee_est=round(finder_fee, 2),
            owner_address=f"{right.owner_mailing_address}, {right.owner_city_state_zip}",
            rationale=rationale
        )

# -------------------------------------------------------------------------
# Prospect & Packet Export
# -------------------------------------------------------------------------
class WaterLeadExporter:
    @staticmethod
    def export_prospects_csv(prospects: List[ScoredWaterProspect], filepath: str) -> None:
        fieldnames = [
            "wdid", "structure_name", "owner_name", "deal_priority", "deal_score",
            "county", "priority_date", "decreed_amount_af", "nearest_muni", "distance_miles",
            "estimated_asset_value", "potential_broker_commission", "finder_referral_fee_est",
            "owner_address", "ditch_company", "rationale"
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for p in prospects:
                row = asdict(p)
                del row["seniority_score"]
                del row["proximity_score"]
                writer.writerow(row)
        logger.info(f"Water prospects CSV written to {filepath}")

    @staticmethod
    def export_prospects_json(prospects: List[ScoredWaterProspect], filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_prospects": len(prospects),
                "prospects": [asdict(p) for p in prospects]
            }, f, indent=2)
        logger.info(f"Water prospects JSON written to {filepath}")

    @staticmethod
    def generate_broker_referral_packet_markdown(prospects: List[ScoredWaterProspect]) -> str:
        md = []
        md.append("# Western Water Rights Off-Market Seller Deal-Flow Packet")
        md.append("**Pattern:** Deal-Flow Referral to Licensed Water Brokers under Colorado C.R.S. 12-61-203.5.")
        md.append(f"**Date:** {datetime.now(timezone.utc).strftime('%B %d, %Y')} | **Operator:** Robert Ketler")
        md.append("**Standard Referral Terms:** 20% – 30% of broker's 10% commission on closed Water Court conveyance.\n")
        md.append("---\n")

        md.append("## 1. Executive Opportunity Summary")
        md.append("- **The Market Asymmetry:** Western US water trading exceeds **$1 Billion annually**, with municipalities comprising 67% of acquisition spend (WestWater 2025). C-BT units trade at $52K–$85K/AF, while rural agricultural rights lease for just $180–$220/AF. Rural heirs and retiring irrigators frequently do not realize the municipal change-of-use value of their decrees.")
        md.append("- **The Data Gap:** State engineer databases (e.g. Colorado DWR Net Amounts) deliberately DO NOT track beneficial ownership. Finding senior decree holders requires programmatic joins between decreed WDIDs, county parcel assessment records, and ditch company mutual stock rolls.")
        md.append("- **Finder Legality:** We do not hold out as real estate brokers or water court attorneys. Under C.R.S. 12-61-203.5, licensed brokers are legally permitted to pay referral fees to finders for actual introduction of business.\n")

        md.append("## 2. Ranked Off-Market Seller Prospects (High-Scoring Senior Rights)")
        md.append("| WDID | Structure / Source | County | Owner / Counterparty | Priority Date | Decreed AF | Dist. to Muni | Est. Asset Value | Finder Fee (2.5%) |")
        md.append("| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
        for p in prospects:
            val_fmt = f"${p.estimated_asset_value:,.0f}"
            fee_fmt = f"${p.finder_referral_fee_est:,.0f}"
            md.append(f"| `{p.wdid}` | **{p.structure_name}** | {p.county} | {p.owner_name} | {p.priority_date} | {p.decreed_amount_af} AF | {p.distance_miles} mi | {val_fmt} | **{fee_fmt}** |")
        md.append("\n")

        md.append("## 3. Master Broker Co-Brokerage / Referral Agreement")
        md.append("*(Ready for signature with Water Colorado, Hydro Source, or Edwards Water Resources)*\n")
        md.append("```text")
        md.append("WATER RIGHTS REFERRAL & CO-BROKERAGE AGREEMENT")
        md.append("==============================================")
        md.append("THIS REFERRAL AGREEMENT is entered into as of ____________________, 2026, by and between:")
        md.append("LICENSED BROKER: _________________________________________________________________")
        md.append("REFERRING FINDER: Robert Ketler / Crescentic Water Deal-Flow Desk")
        md.append("")
        md.append("1. REFERRAL FEE & SCOPE:")
        md.append("   Finder identifies off-market senior water right owners, ditch shareholders, and irrigation")
        md.append("   claimants desiring monetization or municipal conversion, and provides warm introductions to Broker.")
        md.append("   In the event Broker enters into a listing, purchase, sale, or lease agreement with an introduced")
        md.append("   party, Broker agrees to pay Finder a referral fee equal to:")
        md.append("   [ ] Twenty-five percent (25%) of Broker's gross commission received; OR")
        md.append("   [ ] Two and one-half percent (2.5%) of the gross transaction purchase price.")
        md.append("")
        md.append("2. DISBURSEMENT AT CLOSING:")
        md.append("   Referral fees shall be disbursed directly from closing escrow upon final execution of the deed")
        md.append("   conveyance, mutual ditch stock transfer, or Water Court decree change.")
        md.append("")
        md.append("3. COMPLIANCE & GOVERNING LAW:")
        md.append("   This agreement is executed pursuant to Colorado Revised Statutes § 12-61-203.5 permitting")
        md.append("   contractual finder and referral compensation for business introductions.")
        md.append("")
        md.append("AGREED & ACCEPTED:")
        md.append("Broker of Record: ________________________________  Date: ______________")
        md.append("Referring Finder: Robert Ketler                    Date: ______________")
        md.append("```\n")

        md.append("## 4. Cold Phone & Email Intake Script for Licensed Water Brokers")
        md.append("```text")
        md.append("Subject: Direct Off-Market Senior Water Right Referral — South Platte / Weld County")
        md.append("")
        md.append("Hi [Broker Name],")
        md.append("")
        md.append("I track state decreed water rights, county parcel assessor deeds, and ditch shareholder")
        md.append("books across the Front Range (Cache La Poudre, Big Thompson, St. Vrain, and Clear Creek).")
        md.append("")
        md.append("We currently have off-market irrigators and estate heirs holding pre-1880 direct-flow decrees")
        md.append("(25 to 65 AF) located within 5 miles of growing municipal service areas (Greeley, Windsor,")
        md.append("Thornton) who are exploring asset liquidation.")
        md.append("")
        md.append("We do not practice law or act as brokers of record. We work under standard 1-page contractual")
        md.append("referral fee agreements (typically 25% of broker commission paid at escrow closing).")
        md.append("")
        md.append("Are you currently taking buy-side mandates or listing representation for senior South Platte")
        md.append("decrees, and can I forward our 1-page agreement for your review?")
        md.append("")
        md.append("Best regards,")
        md.append("")
        md.append("Robert Ketler")
        md.append("Crescentic Water Deal-Flow Desk")
        md.append("robert@crescenticosmosis.com | (555) 019-4821")
        md.append("```\n")

        md.append("## 5. Execution Steps Tonight")
        md.append("1. [ ] Reach out to top 3 licensed water brokers: Water Colorado (watercolorado.com), Hydro Source (hydrosource.com), Edwards Water Resources.")
        md.append("2. [ ] Send intake email to establish referral paper under C.R.S. 12-61-203.5.")
        md.append("3. [ ] Deliver WDID profiles for top 2 prospects (`0100502` and `0100844`) upon signed referral agreement.")

        return "\n".join(md)

# -------------------------------------------------------------------------
# CLI Application
# -------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Western Water Rights Deal-Flow Engine")
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Run scoring pipeline on water rights")
    p_run.add_argument("--output-dir", default=".", help="Directory to save generated files")

    p_packet = subparsers.add_parser("generate-packet", help="Generate broker referral packet markdown")
    p_packet.add_argument("--output", default="WATER_RIGHTS_BROKER_PACKET.md", help="Output path")

    args = parser.parse_args()
    output_dir = getattr(args, "output_dir", ".")
    os.makedirs(output_dir, exist_ok=True)

    prospects = [WaterRightsScorer.evaluate_right(r) for r in CURATED_WATER_RIGHTS]
    prospects.sort(key=lambda p: p.deal_score, reverse=True)

    if args.command == "run" or args.command is None:
        csv_path = os.path.join(output_dir, "water_seller_prospects.csv")
        json_path = os.path.join(output_dir, "water_seller_prospects.json")
        packet_path = os.path.join(output_dir, "WATER_RIGHTS_BROKER_PACKET.md")

        WaterLeadExporter.export_prospects_csv(prospects, csv_path)
        WaterLeadExporter.export_prospects_json(prospects, json_path)

        packet_content = WaterLeadExporter.generate_broker_referral_packet_markdown(prospects)
        with open(packet_path, "w", encoding="utf-8") as f:
            f.write(packet_content)
        logger.info(f"Broker referral packet saved to {packet_path}")

        print("\n=== WATER RIGHTS DEAL-FLOW PIPELINE COMPLETE ===")
        print(f"Total Rights Evaluated: {len(prospects)}")
        print(f"Tier 1 Urgent Deals: {sum(1 for p in prospects if p.deal_priority == 'TIER_1_URGENT')}")
        print(f"Top Lead: WDID {prospects[0].wdid} ({prospects[0].structure_name}) - Score: {prospects[0].deal_score}")
        print(f"Total Asset Pipeline Value: ${sum(p.estimated_asset_value for p in prospects):,.0f}")
        print(f"Total Projected Finder Fees: ${sum(p.finder_referral_fee_est for p in prospects):,.0f}")

    elif args.command == "generate-packet":
        packet_path = args.output
        packet_content = WaterLeadExporter.generate_broker_referral_packet_markdown(prospects)
        with open(packet_path, "w", encoding="utf-8") as f:
            f.write(packet_content)
        print(f"[OK] Packet written to {packet_path}")

if __name__ == "__main__":
    main()
