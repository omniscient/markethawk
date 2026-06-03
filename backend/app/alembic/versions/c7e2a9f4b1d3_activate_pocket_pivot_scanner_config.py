"""activate_pocket_pivot_scanner_config

The original seed (1bf5e10f1111) inserted the "Pocket Pivot (Evening)" ScannerConfig
with is_active=false, which left it unreachable: GET /scanner/configs returns only
is_active=true rows, so it never appeared in the Scanner Type dropdown, and it could
not be selected for a manual on-demand run.

This migration activates it, bringing it in line with the other three seeded configs
(all is_active=true). Activating it also surfaced a second seed bug: criteria was stored
as '{}' (a JSON object) while ScannerConfigResponse types it as a list, which 500'd
GET /scanner/configs once the row became visible. This migration also normalizes criteria
to '[]' (matching liquidity_hunt's empty-array form).

It intentionally does NOT add a `universe_id` to parameters — the other scheduled configs
don't carry one either; the nightly beat's universe wiring is a separate, pre-existing
concern tracked outside this migration (see follow-up issue #156).

Revision ID: c7e2a9f4b1d3
Revises: 1bf5e10f1111
Create Date: 2026-06-02

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c7e2a9f4b1d3'
down_revision: Union[str, None] = '1bf5e10f1111'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Activate the config AND normalize `criteria` to a JSON array. The original seed
    # (1bf5e10f1111) stored criteria as '{}' (a JSON object), but ScannerConfigResponse
    # types it as List[Dict[str, Any]]. Serializing the now-active row raised a Pydantic
    # ValidationError ("Input should be a valid list") and 500'd GET /scanner/configs.
    # The other configs use an array (liquidity_hunt is '[]').
    op.execute(
        "UPDATE scanner_configs "
        "SET is_active = true, criteria = '[]'::json "
        "WHERE scanner_type = 'pocket_pivot' AND name = 'Pocket Pivot (Evening)'"
    )


def downgrade() -> None:
    # Reverts activation only. The criteria fix corrects invalid seed data (it was never
    # a valid object) and is intentionally not reverted.
    op.execute(
        "UPDATE scanner_configs SET is_active = false "
        "WHERE scanner_type = 'pocket_pivot' AND name = 'Pocket Pivot (Evening)'"
    )
