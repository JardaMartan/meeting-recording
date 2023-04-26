import os
from datetime import datetime, timedelta, timezone
from webexteamssdk import WebexTeamsAPI, AccessToken, ApiError
import json

import logging

WEBEX_TOKEN_FILE = "webex_tokens_{}.json"

TOKEN_REFRESH_TIME_MARGIN = 3600 # seconds

class AccessTokenAbs(AccessToken):
    """
    Store Access Token with a real timestamp.
    
    Access Tokens are generated with 'expires-in' information. In order to store them
    it's better to have a real expiration date and time. Timestamps are saved in UTC.
    Note that Refresh Token expiration is not important. As long as it's being used
    to generate new Access Tokens, its validity is extended even beyond the original expiration date.
    
    Attributes:
        expires_at (float): When the access token expires
        refresh_token_expires_at (float): When the refresh token expires.
    """
    def __init__(self, access_token_json = None, storage_key = "default",
            token_storage_path = "./",
            client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID"),
            client_secret = os.getenv("WEBEX_INTEGRATION_CLIENT_SECRET")):

        self.storage_key = storage_key
        self.token_storage_path = token_storage_path
        self.client_id = client_id
        self.client_secret = client_secret
        
        self._token_refreshed = False
        
        if access_token_json is None:
            access_token_json = self._load_tokens()
            super().__init__(access_token_json)
        else:
            super().__init__(access_token_json)
            self._set_tokens_expiration()
            self._save_tokens()


        logging.info(f"Token data: {self._json_data}")
        
    @property
    def access_token(self):
        exp = datetime.fromtimestamp(self.expires_at)
        diff_sec = (exp - datetime.utcnow()).total_seconds()
        if diff_sec < TOKEN_REFRESH_TIME_MARGIN:
            logging.info(f"Access Token expiring in {diff_sec} sec. Attempting refresh.")
            self.refresh_tokens()
            if not self._token_refreshed:
                return None
            
        return super().access_token
    
    @property
    def expires_at(self):
        return self._json_data.get("expires_at")
        
    @expires_at.setter
    def expires_at(self, exp_at):
        self._json_data["expires_at"] = exp_at
        
    @property
    def refresh_token_expires_at(self):
        return self._json_data.get("refresh_token_expires_at")
        
    @refresh_token_expires_at.setter
    def refresh_token_expires_at(self, exp_at):
        self._json_data["refresh_token_expires_at"] = exp_at
        
    @property
    def token_refreshed(self):
        res = self._token_refreshed
        self._token_refreshed = False # auto reset after read
        return res
        
    def _set_tokens_expiration(self):
        if not "expires_at" in self._json_data.keys():
            self._json_data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds = self.expires_in)).timestamp()
        logging.debug(f"Access Token expires in: {self.expires_in} seconds, at: {self.expires_at}")
        if not "refresh_token_expires_at" in self._json_data.keys():
            self._json_data["refresh_token_expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds = self.refresh_token_expires_in)).timestamp()
        logging.debug(f"Refresh Token expires in: {self.refresh_token_expires_in} seconds, at: {self.refresh_token_expires_at}")

    def _save_tokens(self):
        """
        Save tokens.
        
        Parameters:
        """        
        logging.debug(f"AT timestamp: {self.expires_at}")
        file_destination = self._get_webex_token_file()
        try:
            with open(file_destination, "w") as file:
                logging.debug(f"Saving Webex tokens to: {file_destination}")
                json.dump(self._json_data, file)
        except Exception as e:
            logging.info(f"Webex token save exception: {e}")

        # self._token_refreshed = True # indicate that the Webex token has been refreshed

    def _get_webex_token_file(self):
        if len(self.token_storage_path) > 0:
            if self.token_storage_path[-1] != "/":
                self.token_storage_path += "/"
        return self.token_storage_path + WEBEX_TOKEN_FILE.format(self.storage_key)

    def _load_tokens(self):
        """
        Load tokens.
        
        Parameters:
            
        Returns:
            AccessTokenAbs: Access & Refresh Token object or None
        """
        try:
            file_source = self._get_webex_token_file()
            with open(file_source, "r") as file:
                logging.debug(f"Loading Webex tokens from: {file_source}")
                access_token_json = json.load(file)
                return access_token_json
        except Exception as e:
            logging.info(f"Webex token load exception: {e}")

    def refresh_tokens(self):
        """
        Run the Webex 'get new token by using refresh token' operation.
        
        Get new Access Token. Note that the expiration of the Refresh Token is automatically
        extended no matter if it's indicated. So if this operation is run regularly within
        the time limits of the Refresh Token (typically 3 months), the Refresh Token never expires.
        
        Parameters:
            
        Returns:
            str: message indicating the result of the operation
        """
        integration_api = WebexTeamsAPI(access_token="12345")
        try:
            self._json_data = integration_api.access_tokens.refresh(self.client_id, self.client_secret, self.refresh_token).json_data
            self._set_tokens_expiration()
            self._save_tokens()
            
            self._token_refreshed = True
            logging.info(f"Tokens refreshed for key {self.storage_key}")
        except ApiError as e:
            logging.error(f"Error refreshing an access token. Client Id and Secret loading error: {e}")
