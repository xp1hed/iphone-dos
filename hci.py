""" usage: sudo python hci.py"""

import struct, time, collections
import usb.core, usb.util


class HciError(Exception):
    pass


class Dongle:
    def __init__(self):
        dev = usb.core.find(custom_match=lambda d: (
            d.bDeviceClass, d.bDeviceSubClass, d.bDeviceProtocol) == (0xE0, 0x01, 0x01))
        if dev is None:
            raise HciError("Couldnt find Bluetooth dongle (class E0/01/01) (did you run as sudo?)")
        self.dev = dev
        try:
            dev.set_configuration() # Select configuration 1 if no active configuration is set
        except usb.core.USBError as e:
            print(f"set_configuration Warning: {e}")
        
        self.iface = self.ep_in = None
        for intf in dev.get_active_configuration():
            if intf.bAlternateSetting != 0:
                continue
            for ep in intf:
                if (usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_INTR and
                        usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN):
                    self.iface, self.ep_in = intf.bInterfaceNumber, ep.bEndpointAddress
                    break
            if self.ep_in is not None:
                break
        if self.ep_in is None:
            raise HciError("Couldn't find interrupt IN endpoint for events")
        usb.util.claim_interface(dev, self.iface)
        self.pending = collections.deque() # Save other evnents when waiting for command response

    def close(self):
        try:
            usb.util.release_interface(self.dev, self.iface)
        finally:
            usb.util.dispose_resources(self.dev)

    def _read(self, timeout_ms):
        try:
            return bytes(self.dev.read(self.ep_in, 512, timeout_ms)) # Max event packet length
        except usb.core.USBTimeoutError:
            return None

    def read_event(self, timeout_ms=200):
        if self.pending:
            return self.pending.popleft()
        return self._read(timeout_ms)

    def cmd(self, op, params = b"", timeout = 3.0):
        """(status, return parameters) returned. If no response, status =- 1."""
        pkt = struct.pack("<HB", op, len(params)) + bytes(params)
        # HCI command: control transfer, no H4 indicator
        self.dev.ctrl_transfer(0x20, 0x00, 0, self.iface, pkt, 1000)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ev = self._read(200)
            if not ev or len(ev) < 2:
                continue
            end = min(len(ev), 2 + ev[1])
            if ev[0] == 0x0E and end >= 6 and struct.unpack_from("<H", ev, 3)[0] == op:
                return ev[5], ev[6:end]
            if ev[0] == 0x0F and end >= 6 and struct.unpack_from("<H", ev, 4)[0] == op:
                return ev[2], b""
            self.pending.append(ev)
        return -1, b""

    def ok(self, op, params = b"", what = ""):
        st, ret = self.cmd(op, params)
        # print(f"[{op:04X}] {what} status=0x{st:02X}")
        if st != 0:
            raise HciError(f"[{op:04X}] {what} Failed: status={st}")
        return ret

    def version(self):
        r = self.ok(0x1001, what="Read Local Version")
        return dict(hci_ver=r[0], hci_rev=struct.unpack_from("<H", r, 1)[0], lmp_ver=r[3],
                    manuf=struct.unpack_from("<H", r, 4)[0], lmp_sub=struct.unpack_from("<H", r, 6)[0])

    def ble_init(self, name=""):
        """Respond to BLEDevice::init(name): Initialize controller + set event mask."""
        self.ok(0x0C03, what="Reset")
        if self.version()["lmp_sub"] == 0x8761:
            raise HciError("Firmware not loaded: run sudo python fw.py")
        # When its reset, mask goes back to default, so must set again every time
        self.ok(0x0C01, bytes([0xFF] * 5 + [0x1F, 0x00, 0x20]), "Set Event Mask")      # Trun on LE Meta Event
        self.ok(0x2001, bytes([0xFF, 0x1F, 0, 0, 0, 0, 0, 0]), "LE Set Event Mask")    # Connection related LE events
        addr = self.ok(0x1009, what="Read BD_ADDR")
        print("BD_ADDR", ":".join(f"{b:02X}" for b in reversed(addr[:6])))
        return name