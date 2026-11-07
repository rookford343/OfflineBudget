"""Version of the money-calculation rules.

Hand-bumped integer. Bump it in any commit that changes what a calculation
means (not refactors that keep every figure identical), and add a matching
`- vN:` line to the "Calculation changelog" in docs/architecture.md.
"""

CALC_VERSION: int = 12
