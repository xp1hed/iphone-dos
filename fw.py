"""RTL8761B fw loader, sudo python fw.py"""
"""You need RTL8761B fimware and cfg files, e.g. rtl8761bu_fw.bin and rtl8761bu_config.bin from Realtek SDK"""

import struct, sys, time
from hci import Dongle, HciError

ROM_SUBVER = 0x8761
FRAG = 252


def load(d, fw_path, cfg_path):
    fw, cfg = open(fw_path, "rb").read(), open(cfg_path, "rb").read()
    d.ok(0x0C03, what="Reset")
    v = d.version()
    print(f"LMP subver 0x{v['lmp_sub']:04X}")
    if v["lmp_sub"] != ROM_SUBVER:
        print("Firmware already loaded or different chip, skipping")
        return

    rom = d.ok(0xFC6D, what="ROM version")[0]
    print(f"ROM version = {rom}")
    if fw[:8] != b"Realtech":
        raise HciError("Firmware signature mismatch")
    fw_version, num = struct.unpack_from("<IH", fw, 8)
    chip = struct.unpack_from(f"<{num}H", fw, 14)
    plen = struct.unpack_from(f"<{num}H", fw, 14 + 2 * num)
    poff = struct.unpack_from(f"<{num}I", fw, 14 + 4 * num)
    for i in range(num):
        print(f"  patch[{i}]: chip_id={chip[i]} len={plen[i]} off={poff[i]}")
    if rom + 1 not in chip:
        raise HciError("No patch available for this ROM version")
    pick = chip.index(rom + 1)
    if plen[pick] < 4 or poff[pick] + plen[pick] > len(fw):
        raise HciError("Patch range overflow")

    payload = (fw[poff[pick]:poff[pick] + plen[pick] - 4]
               + struct.pack("<I", fw_version) + cfg)
    nfrag = (len(payload) + FRAG - 1) // FRAG
    print(f"payload {len(payload)} bytes, {nfrag} fragments")
    if nfrag > 0x7F:
        raise HciError("Fragments exceed 127 (index wraparound not supported)")

    for i in range(nfrag):
        idx = i | (0x80 if i == nfrag - 1 else 0)
        st, _ = d.cmd(0xFC20, bytes([idx]) + payload[i * FRAG:(i + 1) * FRAG])
        if st != 0 and i != nfrag - 1: # Last fragment may have weird response while applying
            raise HciError(f"Fragment {i} Failed: status={st}")

    time.sleep(0.5)
    d.ok(0x0C03, what="Reset")
    after = d.version()["lmp_sub"]
    print(f"Loaded after LMP subver 0x{after:04X}")
    if after == ROM_SUBVER:
        raise HciError("subver is unchanged: firmware loading failed")
    print("OK: firmware loaded")


if __name__ == "__main__":
    fw = sys.argv[1] if len(sys.argv) > 1 else "rtl8761bu_fw.bin"
    cfg = sys.argv[2] if len(sys.argv) > 2 else "rtl8761bu_config.bin"
    d = Dongle()
    try:
        load(d, fw, cfg)
    finally:
        d.close()