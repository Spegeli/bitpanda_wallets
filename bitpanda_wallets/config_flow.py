from typing import Any
import voluptuous as vol
import aiohttp
import logging

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import config_validation as cv

from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, CONF_CURRENCY, CONF_API_KEY, CONF_WALLET, FIAT_CURRENCIES, DEFAULT_FIAT_CURRENCY, WALLET_TYPES, BITPANDA_API_URL

_LOGGER = logging.getLogger(__name__)

async def _test_api_key(hass, api_key):
    """Test the provided API key."""
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        url = f"{BITPANDA_API_URL}/asset-wallets"
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


class BitpandaWalletsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bitpanda Wallets."""

    VERSION = 1
    _currency: str = None
    _api_key: str = None

    async def async_step_user(self, user_input: dict[str, Any] = None):
        """Handle the initial step."""
        errors = {}
        if user_input:
            api_key = user_input[CONF_API_KEY]
            currency = user_input[CONF_CURRENCY]
            # Teste den API-Schlüssel
            if await _test_api_key(self.hass, api_key):
                self._currency = currency
                self._api_key = api_key
                return await self.async_step_wallets()
            errors["base"] = "invalid_api_key"

        translations = await async_get_translations(self.hass, self.hass.config.language, "config")

        data_schema = vol.Schema({
            vol.Required(CONF_API_KEY): cv.string,
            vol.Required(CONF_CURRENCY, default=DEFAULT_FIAT_CURRENCY): vol.In({
                currency: translations.get(f"component.bitpanda_wallets.config.currency.{currency}", currency)
                for currency in FIAT_CURRENCIES
            })
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_wallets(self, user_input: dict[str, Any] = None):
        """Handle the wallets selection step."""
        errors = {}

        if user_input and (selected := user_input.get(CONF_WALLET)):
            return self.async_create_entry(
                title=f"Bitpanda Wallets ({self._currency})",
                data={
                    CONF_CURRENCY: self._currency,
                    CONF_API_KEY: self._api_key
                },
                options={
                    CONF_WALLET: selected
                }
            )
            
        if user_input:            
            errors["base"] = "no_wallets_selected"

        selector_config = selector.SelectSelectorConfig(
            options=list(WALLET_TYPES.keys()),
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN
        )

        wallets_schema = vol.Schema({
            vol.Required(CONF_WALLET, default=[]): selector.SelectSelector(selector_config)
        })

        return self.async_show_form(
            step_id="wallets",
            data_schema=wallets_schema,
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BitpandaWalletsOptionsFlow()


class BitpandaWalletsOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow updates."""

    async def async_step_init(self, user_input: dict[str, Any] = None):
        """Manage the options."""
        self._currency = self.config_entry.data[CONF_CURRENCY]
        self.api_key = self.config_entry.data[CONF_API_KEY]
        self._wallets = self.config_entry.options.get(CONF_WALLET, list(WALLET_TYPES.keys()))
        
        return await self.async_step_wallets()

    async def async_step_wallets(self, user_input: dict[str, Any] = None):
        """Handle wallets selection during options flow."""
        errors = {}

        if user_input and (selected := user_input.get(CONF_WALLET)):
            self._wallets = selected
            return self.async_create_entry(
                title="",
                data={
                    CONF_WALLET: self._wallets
                }
            )
            
        if user_input:            
            errors["base"] = "no_wallets_selected"
            
        selector_config = selector.SelectSelectorConfig(
            options=list(WALLET_TYPES.keys()),
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN
        )

        wallets_schema = vol.Schema({
            vol.Required(CONF_WALLET, default=self._wallets): selector.SelectSelector(selector_config)
        })

        return self.async_show_form(
            step_id="wallets",
            data_schema=wallets_schema,
            errors=errors
        )
