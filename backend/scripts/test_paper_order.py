"""Safe legacy entry point; it deliberately performs no order mutation."""


def main() -> None:
    print(
        "Direct submission is disabled. Use the DecisionRouter only after "
        "a genuine ACCEPT and explicit PAPER_EXECUTION_ENABLED=true."
    )


if __name__ == "__main__":
    main()
