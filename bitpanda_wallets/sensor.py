import logging
import asyncio
from datetime import timedelta, datetime

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_WALLET,
    CONF_CURRENCY,
    WALLET_TYPES,
    BITPANDA_API_URL
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=5)  # Fest auf 5 Minuten gesetzt

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Richte die Bitpanda Wallet Sensoren ein."""
    api_key = entry.data[CONF_API_KEY]
    currency = entry.data[CONF_CURRENCY]
    selected_wallets = entry.data.get(CONF_WALLET, list(WALLET_TYPES.keys()))

    coordinator = BitpandaDataUpdateCoordinator(
        hass,
        api_key=api_key,
        currency=currency,
        update_interval=UPDATE_INTERVAL,
        selected_wallets=selected_wallets
    )

    await coordinator.async_config_entry_first_refresh()

    entities = []
    for wallet_type in selected_wallets:
        if wallet_type in WALLET_TYPES:
            entities.append(BitpandaWalletSensor(coordinator, wallet_type, currency))

    async_add_entities(entities)

    @callback
    async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
        """Behandle Optionsänderungen."""
        coordinator.selected_wallets = entry.data.get(CONF_WALLET, list(WALLET_TYPES.keys()))
        await coordinator.async_request_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))


class BitpandaDataUpdateCoordinator(DataUpdateCoordinator):
    """Klasse zur Verwaltung des Datenabrufs von der API."""

    def __init__(self, hass, api_key, currency, update_interval, selected_wallets):
        """Initialisieren."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api_key = api_key
        self.currency = currency
        self.selected_wallets = selected_wallets
        self.session = async_get_clientsession(hass)
        self.ticker_data = {}
        self.next_update = dt_util.utcnow() + self.update_interval  # Initialisiere next_update

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
            "ASSETS": "asset-wallets"
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
            if wallet_type == 'ASSETS':
                total_balance, wallets_info = self._parse_asset_wallets(response_json)
            elif wallet_type == 'FIAT':
                total_balance = self._parse_fiat_wallet(response_json)
                wallets_info = []  # Keine zusätzlichen Attribute für das Fiat Wallet
            else:
                _LOGGER.error("Unbekannter Wallet-Typ in Verarbeitung: %s", wallet_type)
                return {wallet_type: {"total_balance": 0.0, "wallets": []}}
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

    def _parse_asset_wallets(self, response_json):
        """Analysiere Asset-Wallet-Daten."""
        total_balance = 0.0
        wallets_info = []
        data = response_json.get('data', {})
        attributes = data.get('attributes', {})
        # Analysiere Cryptocoin Wallets
        cryptocoin = attributes.get('cryptocoin', {}).get('attributes', {})
        cryptocoin_wallets = cryptocoin.get('wallets', [])
        balance, info = self._collect_asset_wallet_info(cryptocoin_wallets)
        total_balance += balance
        wallets_info.extend(info)
        # Falls gewünscht, können hier auch Commodity Wallets verarbeitet werden
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

    def __init__(self, coordinator, wallet_type, currency):
        """Initialisiere den Sensor."""
        super().__init__(coordinator)
        self.wallet_type = wallet_type
        self.currency = currency

        # Sensorname und unique_id anpassen
        if wallet_type == 'FIAT':
            self._attr_name = f"Bitpanda Wallets Fiat {currency}"
            self._attr_unique_id = f"bitpanda_wallets_fiat_{currency.lower()}"
        elif wallet_type == 'ASSETS':
            self._attr_name = f"Bitpanda Wallets Assets {currency}"
            self._attr_unique_id = f"bitpanda_wallets_assets_{currency.lower()}"

    @property
    def native_value(self):
        """Gibt die Gesamtbalance des Sensors zurück."""
        wallet_data = self.coordinator.data.get(self.wallet_type, {})
        return round(wallet_data.get('total_balance', 0.0), 2)

    @property
    def native_unit_of_measurement(self):
        """Gibt die Maßeinheit zurück."""
        return self.currency  # Angepasste Währung

    @property
    def extra_state_attributes(self):
        """Gibt die Zustandsattribute zurück."""
        # Hole 'last_updated' aus den Koordinatordaten
        last_update = self.coordinator.data.get("last_updated")
        if isinstance(last_update, datetime):
            last_update = dt_util.as_local(last_update).isoformat()
        else:
            last_update = None  # Oder eine passende Nachricht

        # Hole 'next_update' aus dem Koordinator
        next_update = self.coordinator.next_update
        if isinstance(next_update, datetime):
            next_update = dt_util.as_local(next_update).isoformat()
        else:
            next_update = None  # Oder eine passende Nachricht

        attributes = {
            "last_update": last_update,
            "next_update": next_update,
        }
        # Für den Assets Sensor fügen wir 'wallets' hinzu
        if self.wallet_type == 'ASSETS':
            wallet_data = self.coordinator.data.get(self.wallet_type, {})
            wallets_info = wallet_data.get('wallets', [])
            attributes['wallets'] = wallets_info
        return attributes
