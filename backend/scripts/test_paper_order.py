"""Disabled legacy entry point for the Day 30 paper-only backend.

REGRET currently stops at candidate persistence. It does not submit orders,
including paper orders.
"""


def main() -> None:
    print("Order submission is disabled; REGRET stops at CandidateTrade.")


if __name__ == "__main__":
    main()
