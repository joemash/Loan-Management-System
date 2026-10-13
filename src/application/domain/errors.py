"""Domain and application errors. The web adapter maps them to HTTP statuses.

| Error                   | Java                          | HTTP |
|-------------------------|-------------------------------|------|
| ``NotFoundError``       | ``EntityNotFoundException``   | 404  |
| ``DomainStateError``    | ``IllegalStateException``     | 409  |
| ``DomainValidationError`` | ``IllegalArgumentException`` | 400  |
| ``ConcurrencyError``    | ``OptimisticLockingFailureException`` | 409 |
| ``DataConflictError``   | ``DataIntegrityViolationException``   | 409 |
"""


class NotFoundError(Exception):
    pass


class DomainStateError(Exception):
    pass


class DomainValidationError(ValueError):
    pass


class ConcurrencyError(Exception):
    """The aggregate was modified concurrently (optimistic lock failure)."""


class DataConflictError(Exception):
    """A persistence constraint was violated (duplicate or invalid reference)."""
