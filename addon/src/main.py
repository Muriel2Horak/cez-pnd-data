"""Main entry point for CEZ PND Home Assistant Add-on.

Reads configuration from environment variables and starts the orchestrator.
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt_client

from .auth import PlaywrightAuthClient
from .mqtt_publisher import MqttPublisher
from .orchestrator import Orchestrator, OrchestratorConfig
from .session_manager import Credentials, CredentialsProvider, SessionStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MQTTClientWrapper:
    """Wrapper for paho.mqtt.client to match expected interface."""
    
    def __init__(self, host: str, port: int, username: str, password: str):
        self._client = mqtt_client.Client()
        self._client.username_pw_set(username, password)
        self._host = host
        self._port = port
        
    def will_set(self, topic: str, payload: str, qos: int = 1, retain: bool = True):
        """Set Last Will and Testament."""
        self._client.will_set(topic, payload, qos, retain)
        
    def connect(self):
        """Connect to MQTT broker."""
        self._client.connect(self._host, self._port, 60)
        
    def publish(self, topic: str, payload: str, qos: int = 1, retain: bool = True):
        """Publish a message to MQTT broker."""
        self._client.publish(topic, payload, qos, retain)
        
    def disconnect(self):
        """Disconnect from MQTT broker."""
        self._client.disconnect()


def read_env_var(name: str, required: bool = True) -> Optional[str]:
    """Read environment variable with validation."""
    value = os.getenv(name)
    if required and not value:
        logger.error(f"Required environment variable {name} is not set")
        sys.exit(1)
    return value


def create_config() -> Dict[str, Any]:
    """Create configuration dictionary from environment variables."""
    config = {
        'cez': {
            'email': read_env_var('CEZ_EMAIL'),
            'password': read_env_var('CEZ_PASSWORD'),
            'electrometer_id': read_env_var('CEZ_ELECTROMETER_ID', required=False) or 'auto',
        },
        'mqtt': {
            'host': read_env_var('MQTT_HOST'),
            'port': int(read_env_var('MQTT_PORT', required=False) or '1883'),
            'username': read_env_var('MQTT_USER', required=False) or '',
            'password': read_env_var('MQTT_PASSWORD', required=False) or '',
        }
    }
    
    # Use electrometer_id from config if not auto
    if config['cez']['electrometer_id'] == 'auto':
        config['cez']['electrometer_id'] = None
        
    return config


async def main():
    """Main application entry point."""
    # Read configuration
    config = create_config()
    
    # Log configuration (excluding password)
    logger.info(f"Starting CEZ PND add-on")
    logger.info(f"Email: {config['cez']['email']}")
    logger.info(f"Electrometer ID: {config['cez']['electrometer_id'] or 'auto-detect'}")
    logger.info(f"MQTT Host: {config['mqtt']['host']}:{config['mqtt']['port']}")
    
    # Create MQTT client
    mqtt_client = MQTTClientWrapper(
        host=config['mqtt']['host'],
        port=config['mqtt']['port'],
        username=config['mqtt']['username'],
        password=config['mqtt']['password']
    )
    
    # Create orchestrator components
    credentials_provider = CredentialsProvider()
    session_store = SessionStore()
    
    auth_client = PlaywrightAuthClient(
        credentials_provider=credentials_provider,
        session_store=session_store
    )
    
    async def fetch_data(cookies):
        return {}
    
    fetcher = fetch_data
    
    # Use a placeholder meter_id for now, it will be detected from data
    meter_id = config['cez']['electrometer_id'] or 'unknown'
    
    mqtt_publisher = MqttPublisher(mqtt_client, meter_id)
    
    # Create orchestrator configuration
    orchestrator_config = OrchestratorConfig(
        meter_id=meter_id,
        poll_interval_seconds=900  # 15 minutes
    )
    
    # Create orchestrator
    orchestrator = Orchestrator(
        config=orchestrator_config,
        auth_client=auth_client,
        fetcher=fetch_data,
        mqtt_publisher=mqtt_publisher
    )
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        shutdown_event.set()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Start the orchestrator loop
        await orchestrator.run_loop()
    except asyncio.CancelledError:
        logger.info("Orchestrator cancelled")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        # Clean shutdown
        logger.info("Shutting down...")
        mqtt_publisher.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)