import jwt
from time import sleep
import requests
from dnslib import QTYPE, RCODE, RR

from bountydns.core import logger

from bountydns.core.zone.data import ZoneData


class ApiClient:
    def __init__(self, api_url, api_token):
        self.api_url = api_url
        self.api_token = api_token
        payload = jwt.decode(api_token, verify=False)  # do not trust
        if not "dns_server_name" in payload.keys() or not payload["dns_server_name"]:
            logger.critical("no dns_server_name on api token")
            raise Exception("no dns_server_name on api token")
        self.dns_server_name = payload["dns_server_name"]

    def sync(self):
        logger.info("syncing api token")
        return self.post("/api-token/sync", fail=True)

    def get_zones(self):
        logger.info("getting zones")
        zone_data = self.get(
            f"/dns-server/{self.dns_server_name}/zone",
            params={"includes": ["dns_records"]},
        )
        print("LOOK A THIS ")
        data = [ZoneData(**z) for z in zone_data["zones"]]
        logger.critical(str(data))
        return data

    def get_status(self):
        return self.get("/status")

    def create_dns_request(self, handler, request, request_uuid):
        logger.info("creating dns request")

        name = str(request.q.qname)
        name = name.rstrip(".")
        data = {
            "name": name,
            "source_address": str(handler.client_address[0]),
            "source_port": int(handler.client_address[1]),
            "type": str(QTYPE[request.q.qtype]),
            "protocol": str(handler.protocol),
            "dns_server_name": str(self.dns_server_name),
        }
        self.post("/dns-request", data=data)

    def url(self, url):
        return self.api_url + "/api/v1" + url

    def get(self, url: str, params=None, fail=True):
        params = params or {}
        headers = self.get_default_headers()
        res = requests.get(self.url(url), headers=headers, params=params)

        logger.info("Getting URL: " + str(self.url(url)))

        if fail:
            if res.status_code != 200:
                logger.critical(
                    f"Error getting API {self.url(url)}: " + str(res.json())
                )
            res.raise_for_status()
        return res.json()

    def post(self, url: str, data=None, fail=True):
        data = data or {}
        headers = self.get_default_headers()
        res = requests.post(self.url(url), json=data, headers=headers)
        logger.info("Posting URL: " + str(self.url(url)))

        if fail:
            if res.status_code != 200:
                logger.critical(
                    f"Error posting API {self.url(url)}: " + str(res.json())
                )
            res.raise_for_status()
        return res.json()

    def get_default_headers(self):
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Accept": "application/json",
        }

    def wait_for_up(self):
        seconds = 0
        while True:
            if seconds > 60:
                logger.warning("could not connect to api. api not up")
                return False
            logger.info("checking for api status")
            try:
                sleep(1)
                self.get_status()
                sleep(3)
                return True
            except Exception as e:
                logger.info(
                    "api check not ready after {} seconds: {}".format(
                        str(seconds), str(e.__class__.__name__)
                    )
                )
            seconds = seconds + 1
            sleep(1)
