"""Platform-wide constants.

The disclaimer is a product feature (a hard rail), not boilerplate: it appears on every surface
that shows computed output. See NORTH_STAR.md principle 1.
"""

from __future__ import annotations

DISCLAIMER: str = (
    "Computed analytics (Black-76 on the futures price), shown as probabilistic context — "
    "not investment advice. No accuracy or guaranteed return is claimed."
)

# IST is the market timezone for all NSE/BSE timestamps.
IST_TZ = "Asia/Kolkata"
