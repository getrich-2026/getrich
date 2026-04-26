"""分页参数与响应结构。"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def make_page_params(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> PageParams:
    """规范化分页参数，clamp 到合法区间。"""
    page = max(1, page)
    page_size = max(1, min(MAX_PAGE_SIZE, page_size))
    return PageParams(page=page, page_size=page_size)


def make_pagination(page: PageParams, total: int) -> dict[str, object]:
    """生成 OpenAPI 中 Pagination 字段。"""
    total_pages = (total + page.page_size - 1) // page.page_size if page.page_size else 0
    has_more = page.page * page.page_size < total
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total": total,
        "total_pages": total_pages,
        "has_more": has_more,
    }
