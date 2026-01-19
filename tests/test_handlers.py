"""
Tests for the handlers module.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import tornado.testing
import tornado.web
from tornado.httpclient import HTTPClientError

from pyrest.handlers import (
    BaseHandler, HealthHandler, AuthLoginHandler, 
    AuthRegisterHandler, get_auth_handlers, BASE_PATH
)


class TestBaseHandler:
    """Tests for BaseHandler class."""
    
    def test_base_path_constant(self):
        """BASE_PATH should be /pyrest."""
        assert BASE_PATH == "/pyrest"
    
    def test_get_json_body_valid(self):
        """Should parse valid JSON body."""
        mock_handler = MagicMock(spec=BaseHandler)
        mock_handler.request.body = b'{"key": "value"}'
        
        result = BaseHandler.get_json_body(mock_handler)
        
        assert result == {"key": "value"}
    
    def test_get_json_body_invalid(self):
        """Should return empty dict for invalid JSON."""
        mock_handler = MagicMock(spec=BaseHandler)
        mock_handler.request.body = b'not valid json'
        
        result = BaseHandler.get_json_body(mock_handler)
        
        assert result == {}
    
    def test_success_response(self):
        """Should format success response correctly."""
        mock_handler = MagicMock(spec=BaseHandler)
        mock_handler.set_status = MagicMock()
        mock_handler.write = MagicMock()
        
        BaseHandler.success(mock_handler, data={"foo": "bar"}, message="OK")
        
        mock_handler.set_status.assert_called_with(200)
        write_call = mock_handler.write.call_args[0][0]
        assert write_call["success"] is True
        assert write_call["message"] == "OK"
        assert write_call["data"] == {"foo": "bar"}
    
    def test_error_response(self):
        """Should format error response correctly."""
        mock_handler = MagicMock(spec=BaseHandler)
        mock_handler.set_status = MagicMock()
        mock_handler.write = MagicMock()
        
        BaseHandler.error(mock_handler, message="Something went wrong", status_code=400)
        
        mock_handler.set_status.assert_called_with(400)
        write_call = mock_handler.write.call_args[0][0]
        assert write_call["success"] is False
        assert write_call["error"] == "Something went wrong"


class TestAuthHandlers:
    """Tests for authentication handlers."""
    
    def test_get_auth_handlers_returns_list(self):
        """Should return list of handler tuples."""
        handlers = get_auth_handlers()
        
        assert isinstance(handlers, list)
        assert len(handlers) > 0
        
        # Check format
        for handler in handlers:
            assert len(handler) >= 2
            assert isinstance(handler[0], str)
            assert handler[0].startswith("/pyrest")
    
    def test_auth_handlers_paths(self):
        """Should include all auth paths."""
        handlers = get_auth_handlers()
        paths = [h[0] for h in handlers]
        
        assert "/pyrest/auth/login" in paths
        assert "/pyrest/auth/register" in paths
        assert "/pyrest/auth/refresh" in paths
        assert "/pyrest/auth/me" in paths
        assert "/pyrest/auth/azure/login" in paths
        assert "/pyrest/auth/azure/callback" in paths
        assert "/pyrest/health" in paths


class TestHandlersIntegration(tornado.testing.AsyncHTTPTestCase):
    """Integration tests for handlers using Tornado test client."""
    
    def get_app(self):
        """Create test application."""
        handlers = [
            (r"/pyrest/health", HealthHandler),
        ]
        return tornado.web.Application(handlers)
    
    def test_health_endpoint(self):
        """Health endpoint should return healthy status."""
        response = self.fetch("/pyrest/health")
        
        assert response.code == 200
        
        data = json.loads(response.body)
        assert data["success"] is True
        assert data["data"]["status"] == "healthy"
