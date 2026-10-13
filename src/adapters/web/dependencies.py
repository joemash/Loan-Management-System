"""Bridges FastAPI's dependency system to the injector container (like ``flask_injector``'s ``@inject``)."""

from typing import Annotated, Any

from fastapi import Depends, Query, Request

from src.application.ports.pagination import PageQuery


def Inject(interface: type) -> Any:  # noqa: N802 - reads like a type annotation default
    """``uc: ILoanUseCases = Inject(ILoanUseCases)`` resolves a fresh instance per request."""

    def resolve(request: Request):
        return request.app.state.injector.get(interface)

    return Depends(resolve)


def page_query(
    page: Annotated[int, Query(ge=0, description="Zero-based page index")] = 0,
    size: Annotated[int, Query(ge=1, le=2000, description="Page size")] = 20,
    sort: Annotated[list[str] | None, Query(description="`property(,asc|desc)`; repeatable")] = None,
) -> PageQuery:
    return PageQuery(page=page, size=size, sort=tuple(sort or ()))


PageDep = Annotated[PageQuery, Depends(page_query)]
