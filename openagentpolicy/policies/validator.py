from __future__ import annotations

from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.schema import Policy
from openagentpolicy.runtime.policy_field_validation import (
    UnresolvedPolicyField,
    validate_policy_fields,
)


def validate_policies_against_inventory(
    policies: list[Policy], inventory: Inventory
) -> list[UnresolvedPolicyField]:
    return validate_policy_fields(policies, inventory)
