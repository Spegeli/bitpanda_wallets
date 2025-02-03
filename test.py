from datetime import timedelta, datetime
import logging
import asyncio

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_API_KEY, CONF_WALLET, CONF_CURRENCY, WALLET_TYPES, BITPANDA_API_URL, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    """Richte die Bitpanda Wallet Sensoren ein."""
    api_key = entry.data[CONF_API_KEY]
    currency = entry.data[CONF_CURRENCY]
    selected_wallets = entry.options.get(CONF_WALLET, list(WALLET_TYPES.keys()))
    update_interval = float(UPDATE_INTERVAL)
    
    coordinator = BitpandaDataUpdateCoordinator(hass, api_key, currency, update_interval, selected_wallets)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady("No data received from Bitpanda API")

    entities = []
    for wallet_type in selected_wallets:
        if wallet_type in coordinator.data:
            entities.append(BitpandaWalletSensor(coordinator, wallet_type, currency))
        else:
            _LOGGER.warning("Wallet %s not found in Bitpanda API data", wallet_type)

    async_add_entities(entities)

    # Registriere den Update-Listener für Optionen-Änderungen
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle updated options."""
    await hass.config_entries.async_reload(entry.entry_id)

class BitpandaDataUpdateCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Bitpanda API."""
 
    def __init__(self, hass: HomeAssistant, api_key: str, currency: str, update_interval_minutes: float, selected_wallets) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes)
        )
        self.api_key = api_key
        self.currency = currency
        self.selected_wallets = selected_wallets
        self.session = async_get_clientsession(hass)
        self.ticker_data = {}
        self.next_update = dt_util.utcnow() + self.update_interval

    async def _async_update_data(self):
        """Aktualisiere Daten über die API."""
        headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        }
        data = {}
        try:
            # Ticker-Daten abrufen
            ticker_url = "https://api.bitpanda.com/v1/ticker"
            async with self.session.get(ticker_url) as ticker_response:
                ticker_response.raise_for_status()
                ticker_data = await ticker_response.json()
                _LOGGER.debug("Ticker-Daten abgerufen.")
            self.ticker_data = ticker_data

            # Wallet-Daten abrufen
            tasks = []
            for wallet_type in self.selected_wallets:
                tasks.append(self._fetch_wallets(wallet_type, headers))
            results = await asyncio.gather(*tasks)
            for result in results:
                data.update(result)
            # Füge das Aktualisierungsdatum hinzu
            data["last_updated"] = dt_util.utcnow()
            return data
        except Exception as err:
            _LOGGER.error("Fehler beim Abrufen der Daten: %s", err)
            raise UpdateFailed(f"Fehler beim Abrufen der Daten: {err}") from err
        finally:
            # Aktualisiere next_update unabhängig vom Erfolg
            self.next_update = dt_util.utcnow() + self.update_interval

    async def _fetch_wallets(self, wallet_type, headers):
        """Hole Wallet-Daten für einen bestimmten Typ."""
        wallet_endpoint_map = {
            "FIAT": "fiatwallets",
            "STOCK": "asset-wallets",
            "INDEX": "asset-wallets",
            "METAL": "asset-wallets",
            "CRYPTOCOIN": "asset-wallets",
            "ETF": "asset-wallets",
        }
        endpoint = wallet_endpoint_map.get(wallet_type)
        if not endpoint:
            _LOGGER.error("Unbekannter Wallet-Typ: %s", wallet_type)
            return {wallet_type: {"total_balance": 0.0, "wallets": []}}

        url = f"{BITPANDA_API_URL}/{endpoint}"
        _LOGGER.debug("Abrufen von Daten für %s von URL: %s", wallet_type, url)
        async with self.session.get(url, headers=headers) as response:
            _LOGGER.debug("Antwortstatus für %s: %s", wallet_type, response.status)
            response_text = await response.text()
            _LOGGER.debug("Antworttext für %s: %s", wallet_type, response_text)
            response.raise_for_status()
            response_json = await response.json()
            # Analysiere die Antwort und sammle Wallet-Details
            if wallet_type == "FIAT":
                total_balance = self._parse_fiat_wallet(response_json)
                wallets_info = []
            else:
                total_balance, wallets_info = self._parse_asset_wallets(response_json, wallet_type)
            return {wallet_type: {"total_balance": total_balance, "wallets": wallets_info}}

    def _parse_fiat_wallet(self, response_json):
        """Analysiere Fiat-Wallet-Daten und gebe die Balance zurück."""
        wallets = response_json.get('data', [])
        for wallet in wallets:
            attributes = wallet.get('attributes', {})
            currency = attributes.get('fiat_symbol', '')  # Korrekte Schlüsselverwendung
            if currency == self.currency:
                balance = float(attributes.get('balance', 0.0))
                return balance  # Da wir nur ein Fiat Wallet haben, können wir direkt zurückkehren
        return 0.0  # Falls kein Wallet gefunden wurde oder Balance 0 ist

    def _parse_asset_wallets(self, response_json, wallet_type):
        """Analysiere Asset-Wallet-Daten."""
        total_balance = 0.0
        wallets_info = []
        data = response_json.get('data', {})
        attributes = data.get('attributes', {})
    
        # Convert wallet_type to lowercase for consistent matching
        wallet_type_lower = wallet_type.lower()
    
        # Directly access the specific wallet type data
        wallet_data = attributes.get(wallet_type_lower, {}).get('attributes', {})
        wallets = wallet_data.get('wallets', [])

        for wallet in wallets:
            attributes = wallet.get('attributes', {})
            balance_token = float(attributes.get('balance', 0.0))
            if balance_token > 0:
                currency = attributes.get(f'{wallet_type_lower}_symbol', '')
                # Hole den Preis aus den Ticker-Daten
                price = float(self.ticker_data.get(currency, {}).get(self.currency, 0))
                balance_converted = balance_token * price
                total_balance += balance_converted
                name = attributes.get('name', '')
                wallets_info.append({
                    "name": name,
                    "balance_token": balance_token,
                    f"balance_{self.currency.lower()}": round(balance_converted, 2),
                    "currency": currency
                })

        return total_balance, wallets_info

    def _collect_asset_wallet_info(self, wallets):
        """Sammle Asset Wallet Informationen, berechne Werte in der ausgewählten Währung."""
        total = 0.0
        wallets_info = []
        for wallet in wallets:
            attributes = wallet.get('attributes', {})
            balance_token = float(attributes.get('balance', 0.0))
            if balance_token > 0:
                currency = attributes.get('cryptocoin_symbol', '')
                # Hole den Preis aus den Ticker-Daten
                price = float(self.ticker_data.get(currency, {}).get(self.currency, 0))
                balance_converted = balance_token * price
                total += balance_converted
                name = attributes.get('name', '')
                wallets_info.append({
                    "name": name,
                    "balance_token": balance_token,
                    f"balance_{self.currency.lower()}": round(balance_converted, 2),
                    "currency": currency
                })
        return total, wallets_info


class BitpandaWalletSensor(CoordinatorEntity, SensorEntity):
    """Repräsentation eines Bitpanda Wallet Sensors."""
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = False

    def __init__(self, coordinator: BitpandaDataUpdateCoordinator, wallet_type: str, currency: str) -> None:
        super().__init__(coordinator)
        self.wallet_type = wallet_type
        self.currency = currency
        if wallet_type == 'FIAT':
            self._attr_name = f"Bitpanda Wallets Fiat {currency}"
            self._attr_unique_id = f"{DOMAIN}_fiat_{currency.lower()}"
        else:
            self._attr_name = f"Bitpanda Wallets {wallet_type} {currency}"
            self._attr_unique_id = f"{DOMAIN}_{wallet_type.lower()}_{currency.lower()}"

    @property
    def native_value(self):
        """Gibt die Gesamtbalance des Sensors zurück."""
        wallet_data = self.coordinator.data.get(self.wallet_type, {})
        return round(wallet_data.get('total_balance', 0.0), 2)

    @property
    def native_unit_of_measurement(self):
        """Gibt die Maßeinheit zurück."""
        return self.currency

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        attributes = {
            "last_update": dt_util.as_local(self.coordinator.data.get("last_updated")).isoformat(),
            "next_update": dt_util.as_local(self.coordinator.next_update).isoformat(),
            **({"wallets": self.coordinator.data.get(self.wallet_type, {}).get('wallets', [])} if self.wallet_type in ['STOCK', 'INDEX', 'METAL', 'CRYPTOCOIN', 'ETF'] else {})
        }
        return attributes

    async def async_added_to_hass(self) -> None:
        """Register update listener."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
