"""
Simplified routing decorators for PyRest framework.
Provides an easier interface for defining REST endpoints.
"""

import functools
from typing import Callable, Optional, List, Dict, Any, Type
import tornado.web

from .handlers import BaseHandler
from .auth import authenticated as auth_decorator, require_roles


# Registry to store route information
_route_registry: Dict[str, List[Dict[str, Any]]] = {}


def route(path: str):
    """
    Class decorator to set the base path for a handler class.
    
    Usage:
        @route("/users")
        class UsersHandler(BaseHandler):
            @get("/")
            async def list_users(self):
                ...
            
            @get("/{user_id}")
            async def get_user(self, user_id: str):
                ...
    """
    def decorator(cls: Type[BaseHandler]) -> Type[BaseHandler]:
        cls._route_path = path
        return cls
    return decorator


def _method_decorator(http_method: str, path: str = ""):
    """
    Internal decorator factory for HTTP method decorators.
    """
    def decorator(func: Callable) -> Callable:
        # Store route info on the function
        if not hasattr(func, "_route_info"):
            func._route_info = []
        
        func._route_info.append({
            "method": http_method,
            "path": path,
            "handler": func
        })
        
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)
        
        wrapper._route_info = func._route_info
        return wrapper
    
    return decorator


def get(path: str = ""):
    """
    Decorator for GET endpoints.
    
    Usage:
        class MyHandler(BaseHandler):
            @get("/items")
            async def list_items(self):
                return self.success(data=[...])
    """
    return _method_decorator("GET", path)


def post(path: str = ""):
    """
    Decorator for POST endpoints.
    
    Usage:
        class MyHandler(BaseHandler):
            @post("/items")
            async def create_item(self):
                body = self.get_json_body()
                return self.success(data={...})
    """
    return _method_decorator("POST", path)


def put(path: str = ""):
    """
    Decorator for PUT endpoints.
    """
    return _method_decorator("PUT", path)


def patch(path: str = ""):
    """
    Decorator for PATCH endpoints.
    """
    return _method_decorator("PATCH", path)


def delete(path: str = ""):
    """
    Decorator for DELETE endpoints.
    """
    return _method_decorator("DELETE", path)


# Re-export auth decorators for convenience
authenticated = auth_decorator
roles = require_roles


class RestHandler(BaseHandler):
    """
    Enhanced base handler with REST-friendly methods.
    Provides additional conveniences for building REST APIs.
    """
    
    async def get(self, *args, **kwargs):
        """Default GET handler - override in subclass."""
        self.error("Method not allowed", 405)
    
    async def post(self, *args, **kwargs):
        """Default POST handler - override in subclass."""
        self.error("Method not allowed", 405)
    
    async def put(self, *args, **kwargs):
        """Default PUT handler - override in subclass."""
        self.error("Method not allowed", 405)
    
    async def patch(self, *args, **kwargs):
        """Default PATCH handler - override in subclass."""
        self.error("Method not allowed", 405)
    
    async def delete(self, *args, **kwargs):
        """Default DELETE handler - override in subclass."""
        self.error("Method not allowed", 405)
    
    def get_path_param(self, name: str, default: Any = None) -> Any:
        """Get a path parameter by name."""
        return self.path_kwargs.get(name, default)
    
    def get_query_param(self, name: str, default: str = None) -> Optional[str]:
        """Get a query parameter by name."""
        return self.get_argument(name, default)
    
    def get_query_params(self, name: str) -> List[str]:
        """Get all values for a query parameter."""
        return self.get_arguments(name)
    
    def get_int_param(self, name: str, default: int = 0) -> int:
        """Get a query parameter as integer."""
        try:
            return int(self.get_argument(name, str(default)))
        except ValueError:
            return default
    
    def get_bool_param(self, name: str, default: bool = False) -> bool:
        """Get a query parameter as boolean."""
        value = self.get_argument(name, None)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")
    
    def paginate(
        self, 
        items: List[Any], 
        page: Optional[int] = None, 
        per_page: Optional[int] = None,
        max_per_page: int = 100
    ) -> Dict[str, Any]:
        """
        Paginate a list of items.
        
        Args:
            items: List of items to paginate
            page: Page number (1-indexed), defaults from query param
            per_page: Items per page, defaults from query param
            max_per_page: Maximum items per page
            
        Returns:
            Dict with paginated data and metadata
        """
        if page is None:
            page = self.get_int_param("page", 1)
        if per_page is None:
            per_page = self.get_int_param("per_page", 20)
        
        # Clamp values
        page = max(1, page)
        per_page = max(1, min(per_page, max_per_page))
        
        total = len(items)
        total_pages = (total + per_page - 1) // per_page
        
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            "items": items[start:end],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }


def create_handler(
    path: str,
    methods: Dict[str, Callable],
    base_class: Type[BaseHandler] = RestHandler
) -> Type[BaseHandler]:
    """
    Dynamically create a handler class from a dictionary of methods.
    
    Usage:
        async def list_items(handler):
            handler.success(data=[...])
        
        async def create_item(handler):
            body = handler.get_json_body()
            handler.success(data={...})
        
        ItemsHandler = create_handler("/items", {
            "get": list_items,
            "post": create_item
        })
    """
    class_dict = {"_route_path": path}
    
    for method_name, func in methods.items():
        method_name = method_name.lower()
        if method_name in ("get", "post", "put", "patch", "delete"):
            async def method_wrapper(self, func=func, *args, **kwargs):
                return await func(self, *args, **kwargs)
            class_dict[method_name] = method_wrapper
    
    return type("DynamicHandler", (base_class,), class_dict)


# Convenience function for simple CRUD handlers
def crud_handlers(
    resource_name: str,
    list_func: Optional[Callable] = None,
    get_func: Optional[Callable] = None,
    create_func: Optional[Callable] = None,
    update_func: Optional[Callable] = None,
    delete_func: Optional[Callable] = None,
    id_param: str = "id"
) -> List[tuple]:
    """
    Create standard CRUD handlers for a resource.
    
    Usage:
        handlers = crud_handlers(
            "users",
            list_func=list_users,
            get_func=get_user,
            create_func=create_user,
            update_func=update_user,
            delete_func=delete_user
        )
    
    Returns list of handler tuples suitable for get_handlers().
    """
    handlers = []
    
    # List and Create (collection endpoint)
    collection_methods = {}
    if list_func:
        collection_methods["get"] = list_func
    if create_func:
        collection_methods["post"] = create_func
    
    if collection_methods:
        CollectionHandler = create_handler(f"/{resource_name}", collection_methods)
        handlers.append((f"/", CollectionHandler))
    
    # Get, Update, Delete (item endpoint)
    item_methods = {}
    if get_func:
        item_methods["get"] = get_func
    if update_func:
        item_methods["put"] = update_func
    if delete_func:
        item_methods["delete"] = delete_func
    
    if item_methods:
        ItemHandler = create_handler(f"/{resource_name}/{{{id_param}}}", item_methods)
        handlers.append((f"/(?P<{id_param}>[^/]+)", ItemHandler))
    
    return handlers
