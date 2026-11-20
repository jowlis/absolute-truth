"""Role rotation, so that no single model steers the mission.

Odd cycles:  A plans, B works, A reviews.
Even cycles: B plans, A works, B reviews.

The worker is always reviewed by the other model, and planning alternates every cycle.
In the first cycle (genesis) both models draft, the planner merges, the other reviews.
"""


def roles_for(cycle: int, keys: tuple = ("A", "B")) -> dict:
    planner = keys[(cycle - 1) % 2]
    other = keys[cycle % 2]
    return {"planner": planner, "worker": other, "reviewer": planner}
