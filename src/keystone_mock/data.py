"""Synthetic data and per-tenant configuration for the Keystone Core mock.

Everything here is fabricated. SSNs use the 9xx area range, which the SSA never
issues, so they can't collide with a real person. Names and addresses are invented.

Two tenants run the same "vendor product" with different configuration, the way
two credit unions would both run Keystone Core 7.x:

- lakeshore: stock labels, no interstitials.
- pinecrest: relabelled fields and menu items, a different balance column
  header, renamed products, and a mandatory daily bulletin after sign-on.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Account:
    suffix: str
    product: str  # product code, e.g. SAV / CHK / MMS
    status: str
    current: Decimal
    available: Decimal
    nickname: str = ""


@dataclass
class Member:
    number: str
    first: str
    middle: str
    last: str
    since: str
    ssn: str
    dob: str
    address: str
    phone: str
    email: str
    accounts: list[Account] = field(default_factory=list)
    restriction: str | None = None
    pending_address_change: bool = False

    @property
    def display_name(self) -> str:
        return f"{self.first} {self.middle} {self.last}".upper()


# Product catalogue: code -> (minimum opening deposit, dividend rate). Display names are per-tenant.
PRODUCTS: dict[str, tuple[Decimal, str]] = {
    "SAV": (Decimal("5.00"), "0.10%"),
    "CHK": (Decimal("0.00"), "0.00%"),
    "MMS": (Decimal("1000.00"), "2.35%"),
    "HCL": (Decimal("0.00"), "0.50%"),
    "C12": (Decimal("500.00"), "3.90%"),
}
OPENABLE = ["SAV", "MMS", "HCL", "C12"]

SUPERVISOR_LIMIT = Decimal("10000.00")


@dataclass
class TenantConfig:
    key: str
    name: str
    color: str
    labels: dict[str, str]
    products: dict[str, str]
    daily_bulletin: bool = False


STOCK_LABELS = {
    "member_inquiry": "Member Inquiry",
    "open_sub_menu": "Open Sub-Account",
    "member_number": "Member Number",
    "last_name": "Last Name",
    "ssn4": "SSN (last 4)",
    "current_balance": "Current Balance",
    "available_balance": "Available Balance",
    "open_sub_action": "Open Sub-Account",
}

STOCK_PRODUCTS = {
    "SAV": "Share Savings",
    "CHK": "Share Draft Checking",
    "MMS": "Money Market Share",
    "HCL": "Holiday Club",
    "C12": "Share Certificate 12 Mo",
}

TENANTS: dict[str, TenantConfig] = {
    "lakeshore": TenantConfig(
        key="lakeshore",
        name="Lakeshore Community Credit Union",
        color="#1f3b73",
        labels=dict(STOCK_LABELS),
        products=dict(STOCK_PRODUCTS),
    ),
    "pinecrest": TenantConfig(
        key="pinecrest",
        name="Pinecrest Federal Credit Union",
        color="#2e5e3a",
        labels={
            **STOCK_LABELS,
            "member_inquiry": "Member Lookup",
            "member_number": "Member #",
            "current_balance": "Ledger Balance",
            "open_sub_action": "Add Share Account",
        },
        products={**STOCK_PRODUCTS, "SAV": "Primary Savings", "MMS": "Premier Money Market"},
        daily_bulletin=True,
    ),
}

# Operator accounts for the mock. The password is a local-only dev value for a fake app;
# the automation side reads credentials from its own environment and never persists them.
USERS = {
    "tlr_demo": {"name": "TELLER DEMO", "role": "TLR2", "password": "keystone-demo"},
}
SUPERVISORS = {"sup_kim": "4471"}


def _members() -> dict[str, Member]:
    d = Decimal
    return {
        m.number: m
        for m in [
            Member(
                "100234", "Dana", "R", "Whitfield", "04/18/2011", "912-45-6612", "02/11/1984",
                "4418 Larch Hollow Rd, Marquette MI 49855", "(906) 555-0142", "d.whitfield@example.com",
                [
                    Account("00", "SAV", "Open", d("2431.18"), d("2406.18")),
                    Account("10", "CHK", "Open", d("1088.40"), d("1088.40")),
                ],
            ),
            Member(
                "100891", "Gregory", "A", "Whitfield", "09/02/2016", "912-77-0431", "07/30/1971",
                "12 Harbor View Ct, Munising MI 49862", "(906) 555-0199", "gwhit@example.com",
                [Account("00", "SAV", "Open", d("15.02"), d("15.02"))],
            ),
            Member(
                "100555", "Priya", "N", "Castellanos", "01/09/2019", "913-20-8841", "11/05/1990",
                "77 Ore Dock St, Marquette MI 49855", "(906) 555-0107", "priya.c@example.com",
                [
                    Account("00", "SAV", "Open", d("640.00"), d("640.00")),
                    Account("10", "CHK", "Open", d("212.75"), d("212.75")),
                ],
                pending_address_change=True,
            ),
            Member(
                "100777", "Marcus", "T", "Ellery", "06/23/2008", "914-02-5570", "03/14/1966",
                "901 Presque Isle Ave, Marquette MI 49855", "(906) 555-0163", "mellery@example.com",
                [Account("00", "SAV", "Frozen", d("9120.44"), d("0.00"))],
                restriction="FRAUD ALERT - REFER TO BSA OFFICER",
            ),
            Member(
                "104410", "Owen", "J", "Pruitt", "10/30/2003", "915-66-2208", "12/01/1958",
                "3 Birch Ln, Negaunee MI 49866", "(906) 555-0120", "opruitt@example.com",
                [
                    Account("00", "SAV", "Open", d("25310.77"), d("25310.77")),
                    Account("10", "CHK", "Open", d("3302.10"), d("3302.10")),
                    Account("21", "MMS", "Open", d("48000.00"), d("48000.00")),
                ],
            ),
        ]
    }


SEED_MEMBERS = _members()


def fresh_members() -> dict[str, Member]:
    return copy.deepcopy(SEED_MEMBERS)


def money(v: Decimal) -> str:
    return f"${v:,.2f}"
