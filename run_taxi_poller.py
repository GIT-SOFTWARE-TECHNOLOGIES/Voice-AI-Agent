"""
run_taxi_poller.py
==================
Entry point to run the HubSpot Taxi Poller standalone.

Usage:
  python run_taxi_poller.py
  
Or via Docker:
  command: ["python", "run_taxi_poller.py"]
"""

import logging
from src.taxi.hubspot_taxi_poller import HubSpotTaxiPoller

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s — %(message)s",
    datefmt="%H:%M:%S"
)

if __name__ == "__main__":
    poller = HubSpotTaxiPoller()
    poller.run_forever()