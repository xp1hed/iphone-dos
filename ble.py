import struct
from hci import HciError

# # BLEAdvertising::setAdvertisementType() values (same as HCI Adv Type)
ADV_IND, ADV_DIRECT_HIGH, ADV_SCAN_IND, ADV_NONCONN_IND, ADV_DIRECT_LOW = 0, 1, 2, 3, 4

# Original code(hello.cpp) passes string names for advertisement type, so we map them to integer values.
_ADV_TYPE_NAMES = {
    "ADV_TYPE_IND": ADV_IND,
    "ADV_TYPE_DIRECT_IND_HIGH": ADV_DIRECT_HIGH,
    "ADV_TYPE_SCAN_IND": ADV_SCAN_IND,
    "ADV_TYPE_NONCONN_IND": ADV_NONCONN_IND,
    "ADV_TYPE_DIRECT_IND_LOW": ADV_DIRECT_LOW,
}


class AdvertisementData:
    """BLEAdvertisementData: (type, value) items to build a 31-byte AD byte string."""
    def __init__(self):
        self.items = []

    def _add(self, t, v):
        self.items.append((t, bytes(v)))

    def set_flags(self, flags): # setFlags(0x06) = LE General Discoverable | BR/EDR Not Supported
        self._add(0x01, [flags])

    def set_name(self, name): # setName()
        self._add(0x09, name.encode())

    def set_short_name(self, name): # setShortName()
        self._add(0x08, name.encode())

    def set_manufacturer_data(self, data): # setManufacturerData(): front 2 bytes are company iD
        self._add(0xFF, data)

    def set_appearance(self, value): # setAppearance()
        self._add(0x19, struct.pack("<H", value))

    def set_complete_services16(self, uuid16): # setCompleteServices(BLEUUID(0xXXXX)) (16bit UUID)
        self._add(0x03, struct.pack("<H", uuid16))

    def set_service_data16(self, uuid16, data): # setServiceData()
        self._add(0x16, struct.pack("<H", uuid16) + bytes(data))

    def add_data(self, raw): # addData(): already [length, type, value] bytes are added as is
        self.items.append((None, bytes(raw)))

    def encode(self):
        out = b""
        for t, v in self.items:
            out += v if t is None else bytes([len(v) + 1, t]) + v
        if len(out) > 31:
            raise HciError(f"Advertisement data exceeds 31 bytes: {len(out)}")
        return out


def _to_raw(data):
    """Make data transmittable as bytes."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return data.encode()


def _pad(ad): # HCI format: [valid length(1)] + data(31, padded with 0)
    if len(ad) > 31:
        raise HciError(f"Advertisement data exceeds 31 bytes: {len(ad)}")
    return bytes([len(ad)]) + ad.ljust(31, b"\0")


class Advertising:
    """BLEAdvertising respond."""
    def __init__(self, dongle):
        self.d = dongle
        self.adv = AdvertisementData()
        self.scan_rsp = None
        self.type = ADV_IND # ESP32 default is connectable advertising

        self.min_interval = 0xA0 # per 0.625ms
        self.max_interval = 0xA0

    def set_advertisement_data(self, data): # setAdvertisementData()
        self.adv = data

    def set_scan_response_data(self, data): # setScanResponseData()
        self.scan_rsp = data

    def set_advertisement_type(self, t): # setAdvertisementType()
        if isinstance(t, str):
            if t not in _ADV_TYPE_NAMES:
                raise HciError(f"Unknown advertisement type name: {t!r}")
            t = _ADV_TYPE_NAMES[t]
        self.type = int(t)

    def set_min_interval(self, v): # setMinInterval()
        self.min_interval = int(v)

    def set_max_interval(self, v): # setMaxInterval()
        self.max_interval = int(v)

    def start(self): # start()
        d = self.d
        d.ok(0x200A, b"\x00", "Adv Disable")
        d.ok(0x2006, struct.pack("<HHBBB6sBB", self.min_interval, self.max_interval,
                                 self.type, 0, 0, b"\0" * 6, 0x07, 0), "Set Adv Params")
        d.ok(0x2008, _pad(_to_raw(self.adv)), "Set Adv Data")
        if self.scan_rsp is not None:
            d.ok(0x2009, _pad(_to_raw(self.scan_rsp)), "Set Scan Response Data")
        d.ok(0x200A, b"\x01", "Adv Enable")

    def stop(self): # stop()
        self.d.cmd(0x200A, b"\x00")


class Server:
    """BLEServer respond, GATT's are not implemented"""
    def __init__(self, dongle):
        self._adv = Advertising(dongle)

    def get_advertising(self): # getAdvertising()
        return self._adv


def create_server(dongle): # BLEDevice::createServer()
    return Server(dongle)