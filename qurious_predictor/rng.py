"""The game's via.Random generator.

RE Engine's via.Random is a 128-bit xorshift with shift constants (15, 4, 21). Its state is the
generator's StateId (a GUID = four little-endian u32). Determined by black-box observation of
genU32() through REFramework (see docs/RESEARCH.md).
"""

from __future__ import annotations

M32 = 0xFFFFFFFF


class XorShift128:
    __slots__ = ("x", "y", "z", "w", "draws")

    def __init__(self, state: tuple[int, int, int, int] | list[int]):
        self.x, self.y, self.z, self.w = (int(v) & M32 for v in state)
        self.draws = 0

    @classmethod
    def from_bytes(cls, raw: bytes) -> "XorShift128":
        import struct
        return cls(struct.unpack("<4I", raw[:16]))

    def state(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.z, self.w

    def copy(self) -> "XorShift128":
        c = XorShift128(self.state())
        c.draws = self.draws
        return c

    def next_u32(self) -> int:
        """via.Random.genU32()"""
        t = (self.x ^ (self.x << 15)) & M32
        self.x, self.y, self.z = self.y, self.z, self.w
        self.w = (self.w ^ (self.w >> 21) ^ t ^ (t >> 4)) & M32
        self.draws += 1
        return self.w

    def next_f32(self) -> float:
        """via.Random.genF32(): u32 / 2^32."""
        return self.next_u32() / 4294967296.0
