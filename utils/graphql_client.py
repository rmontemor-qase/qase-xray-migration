"""GraphQL client with authentication, retry logic, and rate limiting for Xray Cloud API."""

import time
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logger import get_logger

logger = get_logger(__name__)


class GraphQLClient:
    """
    GraphQL client for Xray Cloud API with authentication, retry logic, and rate limiting.
    
    Features:
    - Bearer token authentication with automatic refresh
    - Exponential backoff retry logic
    - Rate limit handling (300 requests per 5 minutes)
    - GraphQL error parsing and handling
    """
    
    AUTH_URL = "https://xray.cloud.getxray.app/api/v2/authenticate"
    GRAPHQL_URL = "https://xray.cloud.getxray.app/api/v2/graphql"
    
    # Rate limits: 300 requests per 5 minutes (Standard plan)
    RATE_LIMIT_REQUESTS = 300
    RATE_LIMIT_WINDOW = 300  # 5 minutes in seconds
    
    def __init__(self, client_id: str, client_secret: str, jira_url: str):
        """
        Initialize the GraphQL client.
        
        Args:
            client_id: Xray Cloud client ID
            client_secret: Xray Cloud client secret
            jira_url: Jira instance URL (e.g., https://yourcompany.atlassian.net)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.jira_url = jira_url.rstrip('/')
        self.token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        
        # Rate limiting tracking
        self.request_timestamps: list = []
        
        # Setup session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def authenticate(self) -> str:
        """
        Authenticate with Xray Cloud and get Bearer token.
        
        Returns:
            Bearer token string
        
        Raises:
            Exception: If authentication fails
        """
        logger.info("Authenticating with Xray Cloud...")
        
        try:
            response = self.session.post(
                self.AUTH_URL,
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                },
                timeout=30
            )
            response.raise_for_status()
            
            # Handle both JSON response {"token": "..."} and plain string token
            data = response.json()
            if isinstance(data, str):
                # Response is a plain string token
                token = data
            elif isinstance(data, dict):
                # Response is a JSON object with token field
                token = data.get("token")
            else:
                raise ValueError(f"Unexpected authentication response format: {type(data)}")
            
            if not token:
                raise ValueError("No token received from authentication endpoint")
            
            # Tokens typically expire after 1 hour, but we'll refresh every 50 minutes to be safe
            self.token = token
            self.token_expires_at = datetime.now() + timedelta(minutes=50)
            
            logger.info("Authentication successful")
            return token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication failed: {e}")
            raise Exception(f"Failed to authenticate with Xray Cloud: {e}")
    
    def _ensure_authenticated(self):
        """Ensure we have a valid token, refresh if needed."""
        if not self.token or (self.token_expires_at and datetime.now() >= self.token_expires_at):
            self.authenticate()
    
    def _check_rate_limit(self):
        """Check and enforce rate limits."""
        now = time.time()
        
        # Remove timestamps older than the rate limit window
        self.request_timestamps = [
            ts for ts in self.request_timestamps
            if now - ts < self.RATE_LIMIT_WINDOW
        ]
        
        # If we're at the limit, wait until the oldest request expires
        if len(self.request_timestamps) >= self.RATE_LIMIT_REQUESTS:
            oldest_timestamp = min(self.request_timestamps)
            wait_time = self.RATE_LIMIT_WINDOW - (now - oldest_timestamp) + 1
            logger.warning(f"Rate limit reached. Waiting {wait_time:.1f} seconds...")
            time.sleep(wait_time)
            # Clean up again after waiting
            self.request_timestamps = [
                ts for ts in self.request_timestamps
                if time.time() - ts < self.RATE_LIMIT_WINDOW
            ]
        
        # Record this request
        self.request_timestamps.append(time.time())
    
    def execute_query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Execute a GraphQL query with retry logic.
        
        Args:
            query: GraphQL query string
            variables: Optional query variables
            max_retries: Maximum number of retry attempts
        
        Returns:
            Response data dictionary
        
        Raises:
            Exception: If query execution fails after retries
        """
        self._ensure_authenticated()
        self._check_rate_limit()
        
        payload = {
            "query": query,
            "variables": variables or {}
        }
        
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"Executing GraphQL query (attempt {attempt + 1}/{max_retries})")
                
                response = self.session.post(
                    self.GRAPHQL_URL,
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                
                # Handle rate limiting (429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited. Waiting {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                
                response.raise_for_status()
                
                # Parse response - handle both JSON dict and string responses
                try:
                    data = response.json()
                except ValueError:
                    # Response might be a plain string
                    response_text = response.text
                    logger.error(f"GraphQL response is not JSON: {response_text[:200]}")
                    raise Exception(f"GraphQL response is not valid JSON: {response_text[:200]}")
                
                # Check if data is a dict
                if not isinstance(data, dict):
                    logger.error(f"GraphQL response is not a dict: {type(data)}, value: {str(data)[:200]}")
                    raise Exception(f"GraphQL response is not a dictionary: {type(data)}")
                
                # Check for GraphQL errors
                if "errors" in data:
                    errors = data["errors"]
                    error_messages = [err.get("message", str(err)) if isinstance(err, dict) else str(err) for err in errors]
                    raise Exception(f"GraphQL errors: {', '.join(error_messages)}")
                
                # Return data field
                return data.get("data", {})
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
        
        raise Exception(f"Failed to execute GraphQL query after {max_retries} attempts: {last_exception}")
    
    def get_jira_rest_api(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make a request to Jira REST API (for projects, attachments, etc.).
        
        Args:
            endpoint: API endpoint (e.g., "/rest/api/3/project")
            params: Optional query parameters
        
        Returns:
            Response data
        """
        self._ensure_authenticated()
        self._check_rate_limit()
        
        url = f"{self.jira_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
        
        try:
            response = self.session.get(url, headers=headers, params=params, timeout=30)
            
            # Log response details for debugging
            logger.debug(f"Jira REST API response status: {response.status_code}")
            logger.debug(f"Jira REST API response headers: {dict(response.headers)}")
            
            response.raise_for_status()
            
            # Handle both JSON and text responses
            content_type = response.headers.get('Content-Type', '')
            try:
                data = response.json()
                if not isinstance(data, dict):
                    logger.warning(f"Response is not a dict, it's {type(data)}: {str(data)[:200]}")
                    return {"raw_response": str(data)}
                return data
            except ValueError as e:
                logger.warning(f"Response is not JSON. Content-Type: {content_type}, Text: {response.text[:200]}")
                return {"error": response.text, "status_code": response.status_code, "content_type": content_type}
        except requests.exceptions.RequestException as e:
            logger.error(f"Jira REST API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response text: {e.response.text[:500]}")
            raise Exception(f"Failed to fetch from Jira REST API: {e}")
