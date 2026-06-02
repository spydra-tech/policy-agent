"""Procurement desk tools for the agentic policy demo (mock ERP)."""

from __future__ import annotations

from openagentpolicy import policy_tool

_MOCK_VENDORS: dict[str, dict[str, object]] = {
    "V-100": {"vendor_id": "V-100", "name": "Acme Cloud", "terms": "Net 30"},
    "V-200": {"vendor_id": "V-200", "name": "Hardware Depot", "terms": "Net 45"},
}


@policy_tool(
    id="lookup_vendor",
    name="Lookup Vendor",
    description="Read vendor master data",
    risk_level="low",
    side_effect=False,
)
def lookup_vendor(vendor_id: str) -> dict[str, object]:
    return _MOCK_VENDORS.get(
        vendor_id,
        {"vendor_id": vendor_id, "name": "Unknown vendor", "terms": "Net 30"},
    )


@policy_tool(
    id="create_purchase_order",
    name="Create Purchase Order",
    description="Create a purchase order",
    risk_level="medium",
    side_effect=True,
)
def create_purchase_order(
    vendor_id: str,
    amount: float,
    category: str,
) -> dict[str, object]:
    return {
        "status": "created",
        "po_id": f"PO-{vendor_id}-{int(amount)}",
        "vendor_id": vendor_id,
        "amount": amount,
        "category": category,
    }


@policy_tool(
    id="approve_vendor_payment",
    name="Approve Vendor Payment",
    description="Approve payment on a PO",
    risk_level="high",
    side_effect=True,
)
def approve_vendor_payment(po_id: str, amount: float) -> dict[str, object]:
    return {
        "status": "payment_approved",
        "po_id": po_id,
        "amount": amount,
        "payment_ref": f"PAY-{po_id}",
    }
