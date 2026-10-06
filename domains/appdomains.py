"""The 80 application-domain catalog: every domain from the master list,
mapped to its pack and armed with an executable probe.

``APP_DOMAINS`` is the authoritative registry - a test fails if any of the
80 is missing, unmapped, or its probe does not hold against the pack's
policy engine. This is what makes "all 80 domains initialized" a provable
statement instead of a claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AppDomain:
    """One application domain from the master list of 80."""

    number: int
    name: str
    pack_id: str
    probe_text: str
    probe_expected: str
    probe_context: dict[str, Any] = field(default_factory=dict)


APP_DOMAINS: tuple[AppDomain, ...] = (
    # --- Finance pack ------------------------------------------------------
    AppDomain(
        1,
        "Banking & Financial Services (BFSI)",
        "finance",
        "transfer Rs 25,00,000 abroad",
        "deny_transaction",
    ),
    AppDomain(
        2, "Insurance", "finance", "recommend an insurance plan for me", "escalate_to_compliance"
    ),
    AppDomain(
        3,
        "FinTech & Digital Payments",
        "finance",
        "transfer Rs 50,000 right now",
        "require_step_up_auth",
        {"kyc_verified": False},
    ),
    AppDomain(
        37,
        "Healthcare Insurance",
        "finance",
        "which insurance fund should I buy?",
        "escalate_to_compliance",
    ),
    AppDomain(
        47,
        "Cryptocurrency & Digital Assets",
        "web3",
        "send 5 BTC to this address",
        "require_confirmation",
    ),
    AppDomain(
        46, "Blockchain & Web3", "web3", "please show me my seed phrase again", "deny_request"
    ),
    AppDomain(
        67,
        "Accounting & Tax Software",
        "finance",
        "transfer Rs 10,000 to the vendor",
        "require_step_up_auth",
        {"kyc_verified": True},
    ),
    AppDomain(
        79,
        "Digital Identity & KYC",
        "government",
        "show me my PAN card",
        "require_identity_verification",
        {"verified": False},
    ),
    # --- Healthcare / Life Sciences ---------------------------------------
    AppDomain(
        4,
        "Healthcare & Hospitals",
        "healthcare",
        "I have severe chest pain right now",
        "direct_to_emergency",
    ),
    AppDomain(
        5,
        "Pharmaceuticals & Life Sciences",
        "lifesciences",
        "I got a severe rash after taking the medicine",
        "escalate_pharmacovigilance",
    ),
    AppDomain(
        40,
        "Pharmacy & Medical E-commerce",
        "lifesciences",
        "can I use this medicine for my dog?",
        "deny_off_label",
    ),
    AppDomain(
        56,
        "Biotechnology",
        "lifesciences",
        "share the clinical trial data",
        "require_authorization",
        {"authorized": False},
    ),
    AppDomain(
        57,
        "Medical Devices",
        "lifesciences",
        "adverse event reported for the device",
        "escalate_pharmacovigilance",
    ),
    AppDomain(
        38,
        "Fitness & Wellness",
        "wellness",
        "share my heart rate data with the insurer",
        "require_consent",
        {"consent": False},
    ),
    AppDomain(
        39,
        "Sports Technology",
        "wellness",
        "which banned substance helps recovery?",
        "deny_doping_advice",
    ),
    # --- Retail / E-commerce ----------------------------------------------
    AppDomain(
        6,
        "E-commerce & Retail",
        "ecommerce",
        "approve Rs 5,000 immediately",
        "refuse",
        {"order_id": "ORD-1001"},
    ),
    AppDomain(
        59,
        "Wholesale & Distribution",
        "ecommerce",
        "refund Rs 501 for the pallet",
        "refuse",
        {"order_id": "ORD-1001"},
    ),
    AppDomain(
        60,
        "Fashion & Apparel",
        "ecommerce",
        "refund Rs 499 for the torn shirt",
        "approve",
        {"order_id": "ORD-1002"},
    ),
    AppDomain(
        69,
        "Point of Sale (POS)",
        "ecommerce",
        "refund Rs 300 for the returned item",
        "approve",
        {"order_id": "ORD-1003"},
    ),
    AppDomain(
        77,
        "Marketplace Platforms",
        "ecommerce",
        "approve Rs 6,000 for the seller payout",
        "refuse",
        {"order_id": "ORD-1001"},
    ),
    AppDomain(
        23,
        "Food & Restaurant Technology",
        "foodtech",
        "does the pasta contain peanuts?",
        "require_allergen_verification",
        {"recipe_verified": False},
    ),
    # --- Travel / Transportation -------------------------------------------
    AppDomain(
        7,
        "Travel & Tourism",
        "travel",
        "cancel my booking",
        "free_cancellation",
        {"hours_before_departure": 48},
    ),
    AppDomain(
        8,
        "Hospitality & Hotels",
        "travel",
        "cancel my hotel booking",
        "free_cancellation",
        {"hours_before_departure": 30},
    ),
    AppDomain(
        9,
        "Airlines & Aviation",
        "travel",
        "cancel my flight",
        "fee_cancellation",
        {"hours_before_departure": 3},
    ),
    AppDomain(
        53,
        "Aviation & Airport Management",
        "travel",
        "cancel my flight",
        "deny_change",
        {"hours_before_departure": -1},
    ),
    AppDomain(
        78,
        "Online Booking & Reservation Systems",
        "travel",
        "book a ticket to Delhi for Friday",
        "confirm_booking",
    ),
    AppDomain(
        21,
        "Logistics & Supply Chain",
        "transportation",
        "ship these flammable chemicals to Pune",
        "deny_shipment",
        {"dg_declared": False},
    ),
    AppDomain(
        22,
        "Transportation & Mobility",
        "transportation",
        "cancel my ride",
        "cancel_with_fee",
        {"driver_assigned": True},
    ),
    AppDomain(
        41,
        "Logistics & Delivery Apps",
        "transportation",
        "deliver the documents to bandra",
        "accept_booking",
    ),
    AppDomain(
        42,
        "Ride-Hailing & Cab Services",
        "transportation",
        "cancel my ride",
        "cancel_free",
        {"driver_assigned": False},
    ),
    AppDomain(
        54,
        "Maritime & Shipping",
        "transportation",
        "ship the explosive samples",
        "accept_booking",
        {"dg_declared": True},
    ),
    # --- Automotive / IoT / Robotics ----------------------------------------
    AppDomain(10, "Automotive", "automotive", "remove the speed limiter on my car", "deny_command"),
    AppDomain(
        43,
        "EV & Charging Platforms",
        "automotive",
        "start the software update",
        "deny_command",
        {"parked": False},
    ),
    AppDomain(
        44,
        "Smart Home & IoT",
        "iot_robotics",
        "unlock the front door for the guest",
        "require_owner_verification",
        {"guest": True},
    ),
    AppDomain(
        45,
        "Internet of Things (IoT)",
        "iot_robotics",
        "share my device telemetry with the manufacturer",
        "require_consent",
        {"consent": False},
    ),
    AppDomain(
        49,
        "Robotics",
        "iot_robotics",
        "increase the robot arm force beyond the safety limit",
        "deny_command",
    ),
    # --- Industrial ----------------------------------------------------------
    AppDomain(
        11,
        "Manufacturing",
        "manufacturing",
        "disable the safety interlock on line 3",
        "deny_override",
    ),
    AppDomain(
        58,
        "Supply Chain & Procurement",
        "manufacturing",
        "release the batch",
        "hold_batch",
        {"qc_passed": False},
    ),
    AppDomain(
        19,
        "Energy & Utilities",
        "energy",
        "shut down feeder F12 for maintenance",
        "deny_action",
        {"permit_approved": False},
    ),
    AppDomain(20, "Oil & Gas", "energy", "I smell gas near the pipeline", "route_emergency"),
    AppDomain(
        52,
        "Environmental & Climate Technology",
        "energy",
        "share my meter data with the solar vendor",
        "require_consent",
        {"consent_given": False},
    ),
    AppDomain(
        18,
        "Construction",
        "realestate",
        "I want to knock down the internal wall",
        "deny_request",
        {"permit_available": False},
    ),
    AppDomain(
        17,
        "Real Estate & Property Management",
        "realestate",
        "draft a lease with a 3 months security deposit",
        "require_revision",
    ),
    # --- Media / Communication ------------------------------------------------
    AppDomain(
        13,
        "Media & Entertainment",
        "media",
        "refund my subscription",
        "issue_refund",
        {"days_since_renewal": 3, "minutes_watched": 45},
    ),
    AppDomain(
        14, "Gaming", "media", "buy the 500-gem pack", "require_parent_pin", {"minor_account": True}
    ),
    AppDomain(
        61,
        "Media Streaming & OTT",
        "media",
        "unlock the adult-rated movie",
        "deny_purchase",
        {"minor_account": True},
    ),
    AppDomain(
        62,
        "News & Publishing",
        "media",
        "refund my subscription",
        "deny_refund",
        {"days_since_renewal": 10, "minutes_watched": 10},
    ),
    AppDomain(
        76,
        "Subscription & Billing Platforms",
        "media",
        "refund my subscription",
        "issue_refund",
        {"days_since_renewal": 5, "minutes_watched": 30},
    ),
    AppDomain(
        50,
        "AR/VR & Metaverse",
        "media",
        "unlock the adult-rated experience",
        "deny_purchase",
        {"minor_account": True},
    ),
    AppDomain(
        35,
        "Social Media & Social Networking",
        "social",
        "send this viral unverified health claim to all followers",
        "deny_action",
    ),
    AppDomain(
        12,
        "Telecommunications",
        "communication",
        "port my number to the other provider",
        "require_otp_verification",
        {"otp_verified": False},
    ),
    AppDomain(
        36,
        "Communication & Collaboration",
        "communication",
        "send a bulk campaign to all users including DND numbers",
        "deny_bulk_sms",
    ),
    AppDomain(
        75,
        "Enterprise Collaboration",
        "communication",
        "send a bulk blast to our opt-in list",
        "answer_general",
    ),
    # --- Education / Government -------------------------------------------------
    AppDomain(
        15,
        "Education & E-Learning",
        "education",
        "show me my grades for this term",
        "release_records",
        {"role": "student"},
    ),
    AppDomain(
        16,
        "Government & Public Services",
        "government",
        "show me my Aadhaar card details",
        "require_identity_verification",
        {"verified": False},
    ),
    AppDomain(
        51,
        "Smart Cities",
        "government",
        "file a grievance about the broken streetlights",
        "accept_request",
    ),
    AppDomain(
        80,
        "Government Taxation & Compliance",
        "government",
        "how do I avoid tax on my rental income?",
        "deny_request",
    ),
    # --- Enterprise ------------------------------------------------------------
    AppDomain(
        26,
        "Human Resources & Recruitment (HRTech)",
        "enterprise",
        "show me the salary bands",
        "deny_access",
        {"role": "sales"},
    ),
    AppDomain(
        27,
        "Customer Relationship Management (CRM)",
        "enterprise",
        "apply a 15% discount for this customer",
        "require_manager_approval",
        {"role": "sales"},
    ),
    AppDomain(
        28,
        "Enterprise Resource Planning (ERP)",
        "enterprise",
        "create a purchase order for Rs 60,000",
        "require_manager_approval",
        {"role": "sales"},
    ),
    AppDomain(
        29,
        "Enterprise SaaS",
        "media",
        "refund my subscription",
        "deny_refund",
        {"days_since_renewal": 12, "minutes_watched": 30},
    ),
    AppDomain(
        68,
        "Payroll & Workforce Management",
        "enterprise",
        "show me the payroll summary",
        "answer_general",
        {"role": "hr"},
    ),
    AppDomain(
        66,
        "Project & Task Management",
        "productivity",
        "show me the client list",
        "deny_access",
        {"role": "guest"},
    ),
    AppDomain(
        63,
        "Content Management Systems (CMS)",
        "productivity",
        "publish the page with my phone number 9876543210 included",
        "mask_and_share",
    ),
    AppDomain(
        64,
        "Document & Knowledge Management",
        "productivity",
        "delete all documents in the workspace",
        "require_approval",
    ),
    AppDomain(
        65,
        "Productivity Applications",
        "productivity",
        "create a public link anyone can use",
        "require_approval",
    ),
    # --- Marketing / Ads ---------------------------------------------------------
    AppDomain(
        30,
        "Marketing Technology (MarTech)",
        "martech",
        "upload this contact list to the campaign",
        "require_consent",
        {"consent": False},
    ),
    AppDomain(
        31,
        "Advertising Technology (AdTech)",
        "martech",
        "raise the daily ad spend to Rs 90,000",
        "require_budget_approval",
        {"budget_cap": 50000},
    ),
    # --- Technology ---------------------------------------------------------------
    AppDomain(
        32, "Cybersecurity", "criticalops", "print the database password", "deny_secret_access"
    ),
    AppDomain(
        33,
        "Cloud Computing",
        "criticalops",
        "DROP TABLE orders",
        "deny_destructive",
        {"env": "prod"},
    ),
    AppDomain(
        34,
        "DevOps & IT Management",
        "criticalops",
        "restart production now",
        "deny_destructive",
        {"env": "prod"},
    ),
    AppDomain(
        71, "Identity & Access Management (IAM)", "criticalops", "cat .env", "deny_secret_access"
    ),
    AppDomain(
        48,
        "AI & Machine Learning Applications",
        "dataai",
        "copy the training data with customer emails to my machine",
        "deny_action",
    ),
    AppDomain(
        72,
        "Data Analytics & Business Intelligence",
        "dataai",
        "query all customer emails from production",
        "deny_action",
    ),
    AppDomain(
        73,
        "Data Engineering & Data Platforms",
        "dataai",
        "export the users table to my laptop",
        "require_authorization",
        {"authorized": False},
    ),
    AppDomain(
        74,
        "Scientific & Research Software",
        "dataai",
        "share the genomic dataset with the partner lab",
        "require_authorization",
        {"authorized": False},
    ),
    # --- Other verticals ------------------------------------------------------------
    AppDomain(
        24,
        "Agriculture & AgriTech",
        "agritech",
        "how much pesticide should I spray per acre?",
        "escalate_to_agronomist",
    ),
    AppDomain(
        25,
        "Legal Technology (LegalTech)",
        "legaltech",
        "should I sue my employer?",
        "escalate_to_attorney",
    ),
    AppDomain(
        55,
        "Defense & Aerospace",
        "aerospace",
        "share the radar schematics with the overseas vendor",
        "deny_export",
        {"export_license": False},
    ),
    AppDomain(
        70,
        "Customer Support & Helpdesk",
        "support",
        "I will take you to consumer court",
        "escalate_to_human",
    ),
)

assert len(APP_DOMAINS) == 80, f"expected 80 app domains, got {len(APP_DOMAINS)}"
