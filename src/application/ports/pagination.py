from dataclasses import dataclass


@dataclass(frozen=True)
class PageQuery:
    """Zero-based page request; ``sort`` holds ``"property"`` or ``"property,asc|desc"`` (camelCase)."""

    page: int = 0
    size: int = 20
    sort: tuple[str, ...] = ()


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    size: int

    @property
    def total_pages(self) -> int:
        return (self.total + self.size - 1) // self.size

    def map(self, fn) -> "Page":
        return Page([fn(i) for i in self.items], self.total, self.page, self.size)
