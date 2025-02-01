import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_WALLET,
    CONF_CURRENCY,
    WALLET_TYPES,
    SUPPORTED_FIAT_CURRENCIES,
    API_BASE_URL
)

_LOGGER = logging.getLogger(__name__)

class BitpandaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bitpanda Wallets."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            currency = user_input[CONF_CURRENCY]
            # Teste den API-Schlüssel
            if await self._test_api_key(api_key):
                return self.async_create_entry(
                    title=f"Bitpanda Wallets ({currency})",
                    data={
                        CONF_API_KEY: api_key,
                        CONF_CURRENCY: currency,
                        CONF_WALLET: user_input[CONF_WALLET],
                    }
                )
            else:
                errors["base"] = "invalid_api_key"

        data_schema = vol.Schema({
            vol.Required(CONF_API_KEY): str,
            vol.Required(CONF_CURRENCY, default="EUR"): vol.In(SUPPORTED_FIAT_CURRENCIES),
            vol.Required(CONF_WALLET, default=list(WALLET_TYPES.keys())): cv.multi_select(WALLET_TYPES),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def _test_api_key(self, api_key):
        """Test the provided API key."""
        headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json"
        }
        session = aiohttp_client.async_get_clientsession(self.hass)
        try:
            url = f"{API_BASE_URL}/asset-wallets"
            _LOGGER.debug("Testing API key with URL: %s", url)
            async with session.get(url, headers=headers) as response:
                _LOGGER.debug("API Key Test Response Status: %s", response.status)
                response_text = await response.text()
                _LOGGER.debug("API Key Test Response Text: %s", response_text)
                if response.status == 200:
                    data = await response.json()
                    # Prüfe, ob die Antwort die erwarteten Daten enthält
                    if 'data' in data:
                        return True
                    else:
                        _LOGGER.error("Unexpected response data: %s", data)
                elif response.status == 401:
                    _LOGGER.error("Unauthorized access - Invalid API key.")
                else:
                    _LOGGER.error("Unexpected response status: %s", response.status)
        except Exception as err:
            _LOGGER.error("API key validation error: %s", err)
        return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BitpandaOptionsFlow()

class BitpandaOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            # Aktualisiere die Optionen
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=user_input
            )
            return self.async_create_entry(
                title="",
                data={}
            )

        # Initialisiere die Variablen hier
        wallets = self.config_entry.data.get(CONF_WALLET, list(WALLET_TYPES.keys()))

        data_schema = vol.Schema({
            vol.Required(CONF_WALLET, default=wallets): cv.multi_select(WALLET_TYPES),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors
        )
