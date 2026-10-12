"""Domain models."""


class Base:
    def describe(self) -> str:
        return self.label()

    def label(self) -> str:
        return "base"


class User(Base):
    def __init__(self, name: str) -> None:
        self.name = name

    def label(self) -> str:
        return format_name(self.name)


def format_name(name: str) -> str:
    return name.strip().title()
