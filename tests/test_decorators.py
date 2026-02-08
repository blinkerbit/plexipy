"""
Tests for the decorators module.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyrest.decorators import (
    RestHandler,
    create_handler,
    crud_handlers,
    delete,
    get,
    post,
    put,
    route,
)
from pyrest.handlers import BaseHandler


def _make_mock_request():
    """Create a mock request with real headers so set_default_headers works."""
    request = MagicMock()
    request.headers = {"Origin": "*"}
    request.connection = MagicMock()
    return request


class TestRouteDecorators:
    """Tests for HTTP method decorators."""

    def test_route_decorator(self):
        """Should set _route_path on class."""

        @route("/users")
        class TestHandler(BaseHandler):
            pass

        assert TestHandler._route_path == "/users"

    def test_get_decorator(self):
        """Should mark method as GET handler."""

        class TestHandler(BaseHandler):
            @get("/items")
            async def list_items(self):
                return "items"

        handler = TestHandler(MagicMock(), _make_mock_request())

        assert hasattr(handler.list_items, "_route_info")
        assert handler.list_items._route_info[0]["method"] == "GET"
        assert handler.list_items._route_info[0]["path"] == "/items"

    def test_post_decorator(self):
        """Should mark method as POST handler."""

        class TestHandler(BaseHandler):
            @post("/items")
            async def create_item(self):
                return "created"

        handler = TestHandler(MagicMock(), _make_mock_request())

        assert hasattr(handler.create_item, "_route_info")
        assert handler.create_item._route_info[0]["method"] == "POST"

    def test_put_decorator(self):
        """Should mark method as PUT handler."""

        class TestHandler(BaseHandler):
            @put("/items/{id}")
            async def update_item(self):
                # For testing purposes
                pass

        handler = TestHandler(MagicMock(), _make_mock_request())

        assert handler.update_item._route_info[0]["method"] == "PUT"

    def test_delete_decorator(self):
        """Should mark method as DELETE handler."""

        class TestHandler(BaseHandler):
            @delete("/items/{id}")
            async def delete_item(self):
                # For testing purposes
                pass

        handler = TestHandler(MagicMock(), _make_mock_request())

        assert handler.delete_item._route_info[0]["method"] == "DELETE"

    def test_multiple_decorators(self):
        """Should handle multiple method decorators."""

        class TestHandler(BaseHandler):
            @get("/")
            @get("/list")
            async def list_items(self):
                # For testing purposes
                pass

        handler = TestHandler(MagicMock(), _make_mock_request())

        assert len(handler.list_items._route_info) == 2


class TestRestHandler:
    """Tests for RestHandler class."""

    @pytest.fixture
    def mock_request(self):
        """Create mock request."""
        return _make_mock_request()

    def test_get_query_param(self, mock_request):
        """Should get query parameter."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(return_value="value")

        result = handler.get_query_param("key")

        assert result == "value"

    def test_get_int_param(self, mock_request):
        """Should parse integer parameter."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(return_value="42")

        result = handler.get_int_param("count")

        assert result == 42

    def test_get_int_param_invalid(self, mock_request):
        """Should return default for invalid integer."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(return_value="not_a_number")

        result = handler.get_int_param("count", default=10)

        assert result == 10

    def test_get_bool_param_true(self, mock_request):
        """Should parse boolean true values."""
        handler = RestHandler(MagicMock(), mock_request)

        for true_value in ["true", "1", "yes", "on", "TRUE", "Yes"]:
            handler.get_argument = MagicMock(return_value=true_value)
            assert handler.get_bool_param("flag") is True

    def test_get_bool_param_false(self, mock_request):
        """Should parse boolean false values."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(return_value="false")

        assert handler.get_bool_param("flag") is False

    def test_paginate(self, mock_request):
        """Should paginate items correctly."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(side_effect=lambda k, d: d)

        items = list(range(100))
        result = handler.paginate(items, page=2, per_page=10)

        assert len(result["items"]) == 10
        assert result["items"][0] == 10
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["total"] == 100
        assert result["pagination"]["total_pages"] == 10
        assert result["pagination"]["has_prev"] is True
        assert result["pagination"]["has_next"] is True

    def test_paginate_first_page(self, mock_request):
        """Should handle first page."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(side_effect=lambda k, d: d)

        items = list(range(50))
        result = handler.paginate(items, page=1, per_page=20)

        assert result["pagination"]["has_prev"] is False
        assert result["pagination"]["has_next"] is True

    def test_paginate_last_page(self, mock_request):
        """Should handle last page."""
        handler = RestHandler(MagicMock(), mock_request)
        handler.get_argument = MagicMock(side_effect=lambda k, d: d)

        items = list(range(50))
        result = handler.paginate(items, page=3, per_page=20)

        assert len(result["items"]) == 10
        assert result["pagination"]["has_prev"] is True
        assert result["pagination"]["has_next"] is False


class TestCreateHandler:
    """Tests for create_handler function."""

    def test_create_handler_with_get(self):
        """Should create handler with GET method."""

        async def list_items(handler):
            handler.success(data=[])

        Handler = create_handler("/items", {"get": list_items})

        assert Handler._route_path == "/items"
        assert hasattr(Handler, "get")

    def test_create_handler_with_multiple_methods(self):
        """Should create handler with multiple methods."""

        async def list_items(handler):
            # For testing purposes
            pass

        async def create_item(handler):
            # For testing purposes
            pass

        Handler = create_handler("/items", {"get": list_items, "post": create_item})

        assert hasattr(Handler, "get")
        assert hasattr(Handler, "post")


class TestCrudHandlers:
    """Tests for crud_handlers function."""

    def test_crud_handlers_all(self):
        """Should create all CRUD handlers."""

        async def list_fn(handler):
            pass

        async def get_fn(handler):
            pass

        async def create_fn(handler):  # For testing purposes
            pass

        async def update_fn(handler):  # For testing purposes
            pass

        async def delete_fn(handler):  # For testing purposes
            pass

        handlers = crud_handlers(
            "users",
            list_func=list_fn,
            get_func=get_fn,
            create_func=create_fn,
            update_func=update_fn,
            delete_func=delete_fn,
        )

        assert len(handlers) == 2  # Collection and item handlers

        # Check paths
        paths = [h[0] for h in handlers]
        assert "/" in paths
        assert any("id" in p for p in paths)

    def test_crud_handlers_partial(self):
        """Should handle partial CRUD operations."""

        async def list_fn(handler):
            pass

        async def get_fn(handler):
            pass

        handlers = crud_handlers("items", list_func=list_fn, get_func=get_fn)

        assert len(handlers) == 2

    def test_crud_handlers_custom_id(self):
        """Should use custom ID parameter name."""

        async def get_fn(handler):
            pass

        handlers = crud_handlers("posts", get_func=get_fn, id_param="post_id")

        item_path = handlers[0][0]
        assert "post_id" in item_path
