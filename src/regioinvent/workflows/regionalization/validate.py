"""
Structural validation of the regionalized database before it is written to Brightway.

Catches, with the offending activities named, the defects that otherwise surface only as a
NaN LCA score (pypardiso) or a "Factor is exactly singular" error (SuperLU/UMFPACK):

  * an activity with no, or a zero, production exchange
  * an activity whose self-consumption cancels its production (net diagonal ~ 0): the
    technology-mix-of-market-group self-loop
  * a non-finite exchange amount
  * a consumption market with no input of its own product
"""

import math
from collections import defaultdict


def validate_regioinvent_processes(regio, rel_tol=1e-9):
    """
    Log a warning, with the offending activities named, if any regioinvent process would make
    the technosphere matrix singular or carry a non-finite coefficient. Called by the pipeline
    right before write_database(); the database is written regardless.

    :return: dict {problem kind: [descriptions]} — empty when the database is clean, so a
             caller that wants to stop can do `if validate_regioinvent_processes(regio): ...`
    """
    problems = defaultdict(list)

    for ds in regio.regioinvent_in_wurst:
        label = f"{ds['name']} | {ds.get('reference product', '')} | {ds['location']}"
        own = (ds["database"], ds["code"])
        production = [e for e in ds["exchanges"] if e["type"] == "production"]

        if len(production) != 1:
            problems["production exchange count != 1"].append(f"{label} ({len(production)})")
            continue
        prod_amount = production[0]["amount"]
        if not isinstance(prod_amount, (int, float)) or not math.isfinite(prod_amount) or prod_amount == 0:
            problems["production amount zero or non-finite"].append(f"{label} ({prod_amount!r})")
            continue

        self_input = 0.0
        for e in ds["exchanges"]:
            amount = e.get("amount")
            if not isinstance(amount, (int, float)) or not math.isfinite(amount):
                problems["non-finite exchange amount"].append(f"{label} <- {e.get('name')} ({amount!r})")
                continue
            if e["type"] == "technosphere" and e.get("input") == own:
                self_input += amount

        # Brightway: diagonal = production - sum(self inputs); zero means singular
        if abs(prod_amount - self_input) <= rel_tol * abs(prod_amount):
            problems["self-consumption cancels production (singular column)"].append(
                f"{label} (production {prod_amount}, self input {self_input})"
            )

        if ds["name"].startswith("consumption market for "):
            product = ds["reference product"]
            has_product_input = any(
                e["type"] == "technosphere" and e.get("name") == product for e in ds["exchanges"]
            )
            if not has_product_input:
                problems["consumption market without input of its product"].append(label)

    if problems:
        lines = []
        for kind, items in problems.items():
            lines.append(f"- {kind}: {len(items)}")
            lines.extend(f"    {item}" for item in items[:10])
            if len(items) > 10:
                lines.append(f"    ... and {len(items) - 10} more")
        regio.logger.warning(
            "The regionalized database will produce a singular or non-finite technosphere "
            "matrix (LCA scores will be NaN or garbage for the processes listed and everything "
            "that depends on them). Writing anyway.\n" + "\n".join(lines)
        )
        return problems

    regio.logger.info(
        f"Validation passed: {len(regio.regioinvent_in_wurst)} regioinvent processes, "
        "no singular columns, no non-finite amounts, no empty consumption markets."
    )
    return problems
