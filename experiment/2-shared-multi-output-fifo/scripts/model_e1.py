#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle model for the E1 2x2 switch with per-input 1W2R shared FIFOs.

Topology
--------
Two inputs, two outputs.  Each input owns one shared cell pool with VC-linked
FIFO chains (``mo_fifo_top``).  Each pool has two read ports, one per output,
but the switch grants at most one read flit per input per cycle, matching the
single input link of the Experiment 1 VOQ baseline.  Outputs arbitrate over the
two input pools; a multi-flit packet locks (input, vc) until EOP.

Model contract
--------------
* Source: one outstanding packet per input; load at ``arrival``, first flit the
  next cycle; ``gap=0`` loads the next already-arrived packet on the last flit
  edge.
* Write capacity is checked against the start-of-cycle free count, exactly like
  the Experiment 1 FIFO contract.  A cell freed by a read in the same cycle is
  not reused by that cycle's write.  ``same_cycle_free=True`` is an optional
  extension, not used for the main comparison.
* Reads use the head visible at the start of the cycle.  Writes commit at the
  end of the cycle and become visible next cycle.
* No drop: a cell is freed only after a read handshake; pool-full only stalls
  the source.

The model is self-checking: every cycle can verify cell conservation, VC chain
integrity, output-lock consistency, and packet flit continuity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Packet:
    seq: int
    src: int
    dst: int
    length: int
    arrival: int
    vc: int
    accepted: int | None = None
    start: int | None = None
    end: int | None = None

    def copy(self) -> "Packet":
        return Packet(
            seq=self.seq,
            src=self.src,
            dst=self.dst,
            length=self.length,
            arrival=self.arrival,
            vc=self.vc,
            accepted=self.accepted,
            start=self.start,
            end=self.end,
        )


@dataclass
class Flit:
    packet: Packet
    index: int

    @property
    def sop(self) -> bool:
        return self.index == 0

    @property
    def eop(self) -> bool:
        return self.index == self.packet.length - 1


@dataclass
class Cell:
    cell_id: int
    packet: Packet
    index: int
    vc: int
    dst: int

    @property
    def sop(self) -> bool:
        return self.index == 0

    @property
    def eop(self) -> bool:
        return self.index == self.packet.length - 1


@dataclass
class Stats:
    source_stall_cycles: int = 0
    source_stall_by_input: list[int] = field(default_factory=lambda: [0, 0])
    accepted_pkts: int = 0
    accepted_flits: int = 0
    delivered_pkts: int = 0
    delivered_flits: int = 0
    latency_sum: int = 0
    latency_n: int = 0
    admit_latency_sum: int = 0
    admit_latency_n: int = 0
    admit_latencies: list[int] = field(default_factory=list)
    queue_latency_sum: int = 0
    queue_latency_n: int = 0
    pool_occupancy_sum: int = 0
    max_pool_occupancy: int = 0
    max_total_occupancy: int = 0
    output_idle_cycles: int = 0
    output_backpressure_cycles: int = 0
    output_backpressure_by_output: list[int] = field(default_factory=lambda: [0, 0])
    dual_read_cycles: int = 0
    dual_read_cycles_by_input: list[int] = field(default_factory=lambda: [0, 0])
    arb_loss_events: int = 0
    vc_hol_cycles: int = 0
    vc_hol_by_input: list[int] = field(default_factory=lambda: [0, 0])
    out_flits: list[int] = field(default_factory=lambda: [0, 0])
    per_input_flits: list[int] = field(default_factory=lambda: [0, 0])
    per_dst_flits: list[int] = field(default_factory=lambda: [0, 0])
    per_input_output_flits: list[list[int]] = field(
        default_factory=lambda: [[0, 0], [0, 0]]
    )
    per_vc_flits: list[int] = field(default_factory=list)
    delivered: list[Packet] = field(default_factory=list)
    all_delivered: list[Packet] = field(default_factory=list)

    def reset(self) -> None:
        self.source_stall_cycles = 0
        self.source_stall_by_input = [0, 0]
        self.accepted_pkts = 0
        self.accepted_flits = 0
        self.delivered_pkts = 0
        self.delivered_flits = 0
        self.latency_sum = 0
        self.latency_n = 0
        self.admit_latency_sum = 0
        self.admit_latency_n = 0
        self.admit_latencies = []
        self.queue_latency_sum = 0
        self.queue_latency_n = 0
        self.pool_occupancy_sum = 0
        self.max_pool_occupancy = 0
        self.max_total_occupancy = 0
        self.output_idle_cycles = 0
        self.output_backpressure_cycles = 0
        self.output_backpressure_by_output = [0, 0]
        self.dual_read_cycles = 0
        self.dual_read_cycles_by_input = [0, 0]
        self.arb_loss_events = 0
        self.vc_hol_cycles = 0
        self.vc_hol_by_input = [0, 0]
        self.out_flits = [0, 0]
        self.per_input_flits = [0, 0]
        self.per_dst_flits = [0, 0]
        self.per_input_output_flits = [[0, 0], [0, 0]]
        self.per_vc_flits = []
        self.delivered = []
        # all_delivered intentionally keeps the full run.


class SharedFifo:
    """One input's 1W / N-read shared cell pool with per-VC FIFO chains."""

    def __init__(self, input_idx: int, cell_num: int, vc_num: int):
        if cell_num <= 0 or vc_num <= 0:
            raise ValueError("cell_num and vc_num must be positive")
        self.input_idx = input_idx
        self.cell_num = cell_num
        self.vc_num = vc_num
        self.free: deque[int] = deque(range(cell_num))
        self.cells: list[Cell | None] = [None] * cell_num
        self.vc_q: list[deque[int]] = [deque() for _ in range(vc_num)]
        self.vc_locked_to: list[int | None] = [None] * vc_num
        self.allocated: set[int] = set()
        self.total_alloc = 0
        self.total_free = 0

    def occupancy(self) -> int:
        return sum(len(q) for q in self.vc_q)

    def can_write(self, extra_free: int = 0) -> bool:
        return len(self.free) + extra_free > 0

    def head(self, vc: int) -> Cell | None:
        q = self.vc_q[vc]
        if not q:
            return None
        return self.cells[q[0]]

    def head_id(self, vc: int) -> int | None:
        q = self.vc_q[vc]
        return q[0] if q else None

    def push(self, packet: Packet, index: int) -> Cell:
        if not self.free:
            raise AssertionError("push without a free cell")
        cell_id = self.free.popleft()
        if self.cells[cell_id] is not None:
            raise AssertionError("free cell still holds data")
        cell = Cell(
            cell_id=cell_id,
            packet=packet,
            index=index,
            vc=packet.vc,
            dst=packet.dst,
        )
        self.cells[cell_id] = cell
        self.vc_q[packet.vc].append(cell_id)
        self.allocated.add(cell_id)
        self.total_alloc += 1
        return cell

    def pop(self, vc: int) -> Cell:
        q = self.vc_q[vc]
        if not q:
            raise AssertionError("pop from empty VC")
        cell_id = q.popleft()
        if cell_id not in self.allocated:
            raise AssertionError("popping an unallocated cell")
        cell = self.cells[cell_id]
        if cell is None:
            raise AssertionError("popping an empty cell slot")
        if cell.vc != vc:
            raise AssertionError("cell vc mismatch")
        self.cells[cell_id] = None
        self.allocated.remove(cell_id)
        self.free.append(cell_id)
        self.total_free += 1
        return cell

    def check(self) -> None:
        total_chain = 0
        seen: set[int] = set()
        for vc, q in enumerate(self.vc_q):
            total_chain += len(q)
            prev_packet: Packet | None = None
            prev_index = -1
            for cell_id in q:
                if cell_id in seen:
                    raise AssertionError(f"cell {cell_id} appears twice")
                seen.add(cell_id)
                if cell_id not in self.allocated:
                    raise AssertionError(f"cell {cell_id} in chain but not allocated")
                cell = self.cells[cell_id]
                if cell is None:
                    raise AssertionError(f"cell {cell_id} in chain but empty")
                if cell.vc != vc:
                    raise AssertionError("cell stored under wrong VC")
                if cell.packet.vc != vc:
                    raise AssertionError("packet stored under wrong VC")
                if not (0 <= cell.index < cell.packet.length):
                    raise AssertionError("flit index out of range")
                if cell.eop != (cell.index == cell.packet.length - 1):
                    raise AssertionError("EOP marker mismatch")
                if prev_packet is None:
                    # The chain may start mid-packet after earlier flits were
                    # read and freed; that is a valid in-flight prefix.
                    prev_packet = cell.packet
                    prev_index = cell.index
                elif cell.index == 0:
                    if prev_index != prev_packet.length - 1:
                        raise AssertionError("packet boundary before previous EOP")
                    prev_packet = cell.packet
                    prev_index = 0
                else:
                    if prev_packet is not cell.packet:
                        raise AssertionError("flit of a different packet follows")
                    if cell.index != prev_index + 1:
                        raise AssertionError("non-contiguous flit index")
                    prev_index = cell.index
        if len(self.allocated) != total_chain:
            raise AssertionError("allocated set and chain count differ")
        if len(self.free) + total_chain != self.cell_num:
            raise AssertionError("cell conservation failed")
        if len(set(self.free)) != len(self.free):
            raise AssertionError("duplicate cell in free list")
        if set(self.free) & self.allocated:
            raise AssertionError("cell both free and allocated")
        if set(self.free) | self.allocated != set(range(self.cell_num)):
            raise AssertionError("cell IDs not partitioned")
        for cell_id in self.free:
            if self.cells[cell_id] is not None:
                raise AssertionError("free cell slot not empty")
        for cell_id in self.allocated:
            if self.cells[cell_id] is None:
                raise AssertionError("allocated cell slot empty")
        for vc, owner in enumerate(self.vc_locked_to):
            if owner is not None and owner not in (0, 1):
                raise AssertionError("invalid VC lock owner")


class Source:
    """One-outstanding-packet source, one flit per cycle, gap=0 by default."""

    def __init__(self, src: int, packets: list[Packet], gap: int = 0):
        self.src = src
        self.gap = gap
        self.packets = sorted(packets, key=lambda p: (p.arrival, p.seq))
        self.idx = 0
        self.current: Packet | None = None
        self.loaded_cycle: int | None = None
        self.flit_idx = 0

    def step(
        self,
        cycle: int,
        fifo: SharedFifo,
        measure: bool,
        stats: Stats,
        extra_free: int = 0,
    ) -> Flit | None:
        if self.current is None:
            if self.idx < len(self.packets):
                nxt = self.packets[self.idx]
                if nxt.arrival <= cycle:
                    self.current = nxt
                    self.loaded_cycle = cycle
                    self.flit_idx = 0
                    self.idx += 1
            return None

        if self.loaded_cycle is not None and cycle <= self.loaded_cycle:
            return None

        if not fifo.can_write(extra_free=extra_free):
            if measure:
                stats.source_stall_cycles += 1
                stats.source_stall_by_input[self.src] += 1
            return None

        flit = Flit(packet=self.current, index=self.flit_idx)
        if measure:
            if self.flit_idx == 0:
                stats.accepted_pkts += 1
            stats.accepted_flits += 1
        if self.flit_idx == 0:
            self.current.accepted = cycle
        self.flit_idx += 1
        if self.flit_idx == self.current.length:
            self.current = None
            self.loaded_cycle = None
            self.flit_idx = 0
            if self.gap == 0 and self.idx < len(self.packets):
                nxt = self.packets[self.idx]
                if nxt.arrival <= cycle:
                    self.current = nxt
                    self.loaded_cycle = cycle
                    self.idx += 1
        return flit


class Switch:
    def __init__(
        self,
        sources: list[Source],
        cell_num: int,
        vc_num: int,
        warmup: int,
        rdy_period: int = 0,
        rdy_high: int = 0,
        same_cycle_free: bool = False,
        check_every: int = 1,
    ):
        if len(sources) != 2:
            raise ValueError("E1 model fixes two inputs")
        self.sources = sources
        self.cell_num = cell_num
        self.vc_num = vc_num
        self.warmup = warmup
        self.rdy_period = rdy_period
        self.rdy_high = rdy_high
        self.same_cycle_free = same_cycle_free
        self.check_every = max(1, check_every)
        self.fifos = [
            SharedFifo(i, cell_num, vc_num) for i in range(2)
        ]
        self.stats = Stats()
        self.stats.per_vc_flits = [0] * vc_num
        self.stats.per_input_output_flits = [[0, 0], [0, 0]]
        self.cycle = 0
        self.out_rr = [0, 0]
        self.in_rr = [[0, 0], [0, 0]]
        self.locked = [False, False]
        self.locked_in = [-1, -1]
        self.locked_vc = [-1, -1]
        self.active_pkt: list[Packet | None] = [None, None]
        self.last_idx = [-1, -1]
        self.lifetime_accepted_flits = 0
        self.lifetime_delivered_flits = 0
        self.invariant_checks = 0

    def _ready(self, out: int, cycle: int) -> bool:
        if self.rdy_period <= 0:
            return True
        return ((cycle + 2 * out) % self.rdy_period) < self.rdy_high

    def _lock(self, out: int, inp: int, vc: int) -> None:
        if self.locked[out]:
            raise AssertionError("locking an already locked output")
        if self.fifos[inp].vc_locked_to[vc] is not None:
            raise AssertionError("VC already locked by another output")
        self.locked[out] = True
        self.locked_in[out] = inp
        self.locked_vc[out] = vc
        self.fifos[inp].vc_locked_to[vc] = out

    def _unlock(self, out: int) -> None:
        if not self.locked[out]:
            raise AssertionError("unlocking an unlocked output")
        inp = self.locked_in[out]
        vc = self.locked_vc[out]
        if self.fifos[inp].vc_locked_to[vc] != out:
            raise AssertionError("VC lock owner mismatch")
        self.fifos[inp].vc_locked_to[vc] = None
        self.locked[out] = False
        self.locked_in[out] = -1
        self.locked_vc[out] = -1

    def _select_vc(self, inp: int, out: int) -> int | None:
        """RR over eligible, unlocked VCs for one input/output read port."""
        fifo = self.fifos[inp]
        start = self.in_rr[inp][out]
        for k in range(self.vc_num):
            vc = (start + k) % self.vc_num
            if fifo.vc_locked_to[vc] is not None:
                continue
            head = fifo.head(vc)
            if head is not None and head.dst == out:
                return vc
        return None

    def _candidates(self) -> list[tuple[int, int, Cell | None] | None]:
        """Return (input, vc, head-or-None) per output, or None.

        The shared FIFO has one read port per output, so both outputs may read
        the same input in the same cycle, provided they use different VCs.
        A VC is never served by two outputs: ``vc_locked_to`` and ``dst``
        enforce that.
        """
        selections: list[tuple[int, int, Cell | None] | None] = [None, None]

        # Locked outputs keep their VC; the other output may still use the
        # same input through its own read port and a different VC.
        for out in range(2):
            if not self.locked[out]:
                continue
            inp = self.locked_in[out]
            vc = self.locked_vc[out]
            head = self.fifos[inp].head(vc)
            if head is not None:
                if head.dst != out or head.vc != vc:
                    raise AssertionError("locked VC head mismatch")
            selections[out] = (inp, vc, head)

        # Unlocked outputs arbitrate independently over the two input pools.
        for out in range(2):
            if self.locked[out]:
                continue
            req = [False, False]
            cand: list[tuple[int, int, Cell] | None] = [None, None]
            for inp in range(2):
                vc = self._select_vc(inp, out)
                if vc is None:
                    continue
                head = self.fifos[inp].head(vc)
                if head is None:
                    raise AssertionError("selected empty VC")
                req[inp] = True
                cand[inp] = (inp, vc, head)
            if not any(req):
                continue
            if req[0] and req[1]:
                self.stats.arb_loss_events += 1
            first = self.out_rr[out]
            inp = first if req[first] else 1 - first
            item = cand[inp]
            if item is None:
                raise AssertionError("arbitration selected no candidate")
            _, vc, head = item
            selections[out] = (inp, vc, head)
            self.out_rr[out] = 1 - inp
            self.in_rr[inp][out] = (vc + 1) % self.vc_num

        # A VC cannot be read by both outputs in one cycle.
        used: set[tuple[int, int]] = set()
        for sel in selections:
            if sel is None:
                continue
            key = (sel[0], sel[1])
            if key in used:
                raise AssertionError("same VC selected by both outputs")
            used.add(key)
        return selections

    def _apply_transfer(
        self,
        out: int,
        inp: int,
        vc: int,
        flit: Cell,
        cycle: int,
        measure: bool,
    ) -> None:
        packet = flit.packet
        if flit.vc != vc or packet.vc != vc:
            raise AssertionError("transferred cell VC mismatch")
        if packet.dst != out:
            raise AssertionError("transferred cell destination mismatch")
        if flit.eop != (flit.index == packet.length - 1):
            raise AssertionError("EOP marker mismatch")

        if self.last_idx[out] < 0:
            if flit.index != 0:
                raise AssertionError("non-SOP starts an output packet")
            self.active_pkt[out] = packet
        else:
            if flit.sop:
                raise AssertionError("SOP before previous EOP")
            if packet is not self.active_pkt[out]:
                raise AssertionError("flit from a different packet")
            if flit.index != self.last_idx[out] + 1:
                raise AssertionError("non-contiguous output flit index")

        if flit.sop:
            packet.start = cycle - 1
        if measure:
            self.stats.delivered_flits += 1
            self.stats.out_flits[out] += 1
            self.stats.per_input_flits[inp] += 1
            self.stats.per_dst_flits[out] += 1
            self.stats.per_input_output_flits[inp][out] += 1
            self.stats.per_vc_flits[vc] += 1
        self.lifetime_delivered_flits += 1

        if flit.eop:
            packet.end = cycle - 1
            self._record_delivery(packet, cycle, measure)
            self.active_pkt[out] = None
            self.last_idx[out] = -1
            if self.locked[out]:
                self._unlock(out)
        else:
            self.last_idx[out] = flit.index
            if not self.locked[out]:
                self._lock(out, inp, vc)

    def _record_delivery(self, packet: Packet, cycle: int, measure: bool) -> None:
        self.stats.all_delivered.append(packet.copy())
        if not measure:
            return
        if packet.accepted is None or packet.start is None:
            raise AssertionError("delivered packet missing timestamps")
        self.stats.delivered_pkts += 1
        self.stats.latency_sum += (cycle - 1) - packet.arrival
        self.stats.latency_n += 1
        if packet.accepted >= self.warmup:
            admit = (cycle - 1) - packet.accepted
            self.stats.admit_latency_sum += admit
            self.stats.admit_latency_n += 1
            self.stats.admit_latencies.append(admit)
        self.stats.queue_latency_sum += packet.start - packet.accepted
        self.stats.queue_latency_n += 1
        self.stats.delivered.append(packet.copy())

    def _count_vc_hol(self, selections, rdy: list[bool]) -> None:
        """Approximate VC-internal HOL: head output blocked while a later
        packet in the same VC targets another output."""
        for inp, fifo in enumerate(self.fifos):
            for vc, q in enumerate(fifo.vc_q):
                if not q:
                    continue
                head = fifo.head(vc)
                if head is None:
                    continue
                hd = head.dst
                # Is this VC actually transferring this cycle?
                sel = selections[hd]
                served = (
                    sel is not None
                    and sel[0] == inp
                    and sel[1] == vc
                    and rdy[hd]
                )
                if served:
                    continue
                # Is the head's output unavailable to this input this cycle?
                blocked = False
                if self.locked[hd] and self.locked_in[hd] != inp:
                    blocked = True
                elif sel is not None and not (sel[0] == inp and sel[1] == vc):
                    blocked = True
                elif sel is not None and not rdy[hd]:
                    blocked = True
                if not blocked:
                    continue
                # A later packet in the same VC with a different destination.
                seen_head_packet = None
                for cell_id in list(q)[1:]:
                    cell = fifo.cells[cell_id]
                    if cell is None:
                        raise AssertionError("empty cell in VC chain")
                    if cell.index == 0:
                        if seen_head_packet is None:
                            seen_head_packet = cell.packet
                        if cell.dst != hd:
                            self.stats.vc_hol_cycles += 1
                            self.stats.vc_hol_by_input[inp] += 1
                            break

    def check(self) -> None:
        total_occ = 0
        for inp, fifo in enumerate(self.fifos):
            fifo.check()
            total_occ += fifo.occupancy()
            for vc, owner in enumerate(fifo.vc_locked_to):
                if owner is not None:
                    if not self.locked[owner]:
                        raise AssertionError("VC locked to an unlocked output")
                    if self.locked_in[owner] != inp or self.locked_vc[owner] != vc:
                        raise AssertionError("VC/output lock mismatch")
        for out in range(2):
            if not self.locked[out]:
                continue
            inp = self.locked_in[out]
            vc = self.locked_vc[out]
            if not (0 <= inp < 2 and 0 <= vc < self.vc_num):
                raise AssertionError("invalid output lock indices")
            if self.fifos[inp].vc_locked_to[vc] != out:
                raise AssertionError("output lock missing VC lock")
            head = self.fifos[inp].head(vc)
            if head is not None:
                if head.dst != out:
                    raise AssertionError("locked head destination mismatch")
                if self.last_idx[out] < 0:
                    if head.index != 0:
                        raise AssertionError("locked VC starts mid-packet")
                else:
                    if head.packet is not self.active_pkt[out]:
                        raise AssertionError("locked VC packet changed")
                    if head.index != self.last_idx[out] + 1:
                        raise AssertionError("locked VC flit gap")
        if (
            self.lifetime_accepted_flits - self.lifetime_delivered_flits
            != total_occ
        ):
            raise AssertionError(
                "lifetime cell conservation failed: "
                f"acc={self.lifetime_accepted_flits} "
                f"del={self.lifetime_delivered_flits} occ={total_occ}"
            )
        self.invariant_checks += 1

    def step(self) -> None:
        cycle = self.cycle
        measure = cycle >= self.warmup
        rdy = [self._ready(0, cycle), self._ready(1, cycle)]

        # Source writes.  In the main comparison, capacity is start-of-cycle,
        # matching the Experiment 1 FIFO contract.
        writes: list[tuple[int, Flit]] = []
        if not self.same_cycle_free:
            for inp, source in enumerate(self.sources):
                flit = source.step(cycle, self.fifos[inp], measure, self.stats)
                if flit is not None:
                    writes.append((inp, flit))
                    self.lifetime_accepted_flits += 1

        selections = self._candidates()
        if measure:
            self._count_vc_hol(selections, rdy)

        transfers: list[tuple[int, int, int, Cell]] = []
        for out in range(2):
            sel = selections[out]
            if sel is None:
                continue
            inp, vc, flit = sel
            if flit is None:
                continue
            if not rdy[out]:
                if measure:
                    self.stats.output_backpressure_cycles += 1
                    self.stats.output_backpressure_by_output[out] += 1
                if not self.locked[out]:
                    self._lock(out, inp, vc)
                continue
            self._apply_transfer(out, inp, vc, flit, cycle, measure)
            transfers.append((out, inp, vc, flit))

        if self.same_cycle_free:
            freed = [0, 0]
            for _, inp, _, _ in transfers:
                freed[inp] += 1
            for inp, source in enumerate(self.sources):
                flit = source.step(
                    cycle,
                    self.fifos[inp],
                    measure,
                    self.stats,
                    extra_free=freed[inp],
                )
                if flit is not None:
                    writes.append((inp, flit))
                    self.lifetime_accepted_flits += 1

        # Reads first, then writes: a same-cycle-free cell is reusable only
        # when same_cycle_free is enabled.
        for out, inp, vc, flit in transfers:
            popped = self.fifos[inp].pop(vc)
            if popped is not flit:
                raise AssertionError("selected flit vanished")
        for inp, flit in writes:
            if flit.packet.src != inp:
                raise AssertionError("source wrote a packet from another input")
            if not (0 <= flit.packet.vc < self.vc_num):
                raise AssertionError("source VC out of range")
            fifo = self.fifos[inp]
            was_empty = len(fifo.vc_q[flit.packet.vc]) == 0
            fifo.push(flit.packet, flit.index)
            if was_empty and fifo.vc_locked_to[flit.packet.vc] is not None:
                owner = fifo.vc_locked_to[flit.packet.vc]
                if self.active_pkt[owner] is None:
                    if flit.index != 0:
                        raise AssertionError("locked empty VC got mid-packet")
                else:
                    if flit.packet is not self.active_pkt[owner]:
                        raise AssertionError("locked VC got another packet")
                    if flit.index != self.last_idx[owner] + 1:
                        raise AssertionError("locked VC got a flit gap")

        if measure:
            busy_outputs = len(transfers)
            self.stats.output_idle_cycles += 2 - busy_outputs
            reads_by_input = [0, 0]
            for _, inp, _, _ in transfers:
                reads_by_input[inp] += 1
            for inp in range(2):
                if reads_by_input[inp] >= 2:
                    self.stats.dual_read_cycles += 1
                    self.stats.dual_read_cycles_by_input[inp] += 1
            occ0 = self.fifos[0].occupancy()
            occ1 = self.fifos[1].occupancy()
            self.stats.pool_occupancy_sum += occ0 + occ1
            self.stats.max_pool_occupancy = max(
                self.stats.max_pool_occupancy, occ0, occ1
            )
            self.stats.max_total_occupancy = max(
                self.stats.max_total_occupancy, occ0 + occ1
            )

        if self.cycle % self.check_every == 0:
            self.check()
        self.cycle += 1

    def finish(self) -> None:
        self.check()


def jain(values: list[int]) -> float:
    total = sum(values)
    if total == 0:
        return 0.0
    return (total * total) / (len(values) * sum(v * v for v in values))


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return float(ordered[idx])


def summarize(
    stats: Stats,
    cycles: int,
    cell_num: int,
    vc_num: int,
    vc_mode: str,
    same_cycle_free: bool,
    invariant_checks: int,
) -> dict:
    measured = max(1, cycles)
    delivered_tp = stats.delivered_flits / measured
    latencies = [
        p.end - p.arrival
        for p in stats.delivered
        if p.end is not None and p.arrival is not None
    ]
    return {
        "mode": "shared",
        "cell_num": cell_num,
        "vc_num": vc_num,
        "vc_mode": vc_mode,
        "same_cycle_free": same_cycle_free,
        "delivered_pkts": stats.delivered_pkts,
        "delivered_flits": stats.delivered_flits,
        "delivered_tp": delivered_tp,
        "utilization": delivered_tp / 2.0,
        "accepted_pkts": stats.accepted_pkts,
        "accepted_flits": stats.accepted_flits,
        "accepted_tp": stats.accepted_flits / measured,
        "avg_pkt_latency": (
            stats.latency_sum / stats.latency_n if stats.latency_n else 0.0
        ),
        "p99_pkt_latency": percentile(latencies, 0.99),
        "avg_admit_latency": (
            stats.admit_latency_sum / stats.admit_latency_n
            if stats.admit_latency_n
            else 0.0
        ),
        "p99_admit_latency": percentile(stats.admit_latencies, 0.99),
        "avg_queue_latency": (
            stats.queue_latency_sum / stats.queue_latency_n
            if stats.queue_latency_n
            else 0.0
        ),
        "avg_pool_occupancy": stats.pool_occupancy_sum / (measured * 2),
        "pool_utilization": stats.pool_occupancy_sum / (measured * 2 * cell_num),
        "max_pool_occupancy": stats.max_pool_occupancy,
        "max_total_pool_occupancy": stats.max_total_occupancy,
        "source_stall_cycles": stats.source_stall_cycles,
        "source_stall_rate": stats.source_stall_cycles / (measured * 2),
        "source_stall_by_input": stats.source_stall_by_input,
        "output_idle_cycles": stats.output_idle_cycles,
        "output_idle_rate": stats.output_idle_cycles / (measured * 2),
        "output_backpressure_cycles": stats.output_backpressure_cycles,
        "output_backpressure_rate": stats.output_backpressure_cycles / (measured * 2),
        "output_backpressure_by_output": stats.output_backpressure_by_output,
        "dual_read_cycles": stats.dual_read_cycles,
        "dual_read_rate": stats.dual_read_cycles / measured,
        "dual_read_cycles_by_input": stats.dual_read_cycles_by_input,
        "arb_loss_events": stats.arb_loss_events,
        "vc_hol_cycles": stats.vc_hol_cycles,
        "vc_hol_rate": stats.vc_hol_cycles / (measured * 2),
        "vc_hol_by_input": stats.vc_hol_by_input,
        "out_flits": stats.out_flits,
        "per_input_flits": stats.per_input_flits,
        "per_dst_flits": stats.per_dst_flits,
        "per_input_output_flits": stats.per_input_output_flits,
        "per_vc_flits": stats.per_vc_flits,
        "jain_out": jain(stats.out_flits),
        "jain_input": jain(stats.per_input_flits),
        "per_out_0_tp": stats.out_flits[0] / measured,
        "per_out_1_tp": stats.out_flits[1] / measured,
        "per_input_0_tp": stats.per_input_flits[0] / measured,
        "per_input_1_tp": stats.per_input_flits[1] / measured,
        "invariant_checks": invariant_checks,
    }


def load_trace(path: str) -> dict[int, list[Packet]]:
    by_src: dict[int, list[Packet]] = {0: [], 1: []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            src = int(row["src"])
            by_src.setdefault(src, []).append(
                Packet(
                    seq=int(row["seq"]),
                    src=src,
                    dst=int(row["dst"]),
                    length=int(row["len"]),
                    arrival=int(row["arrival"]),
                    vc=int(row.get("vc", 0)),
                )
            )
    return by_src


def run(
    trace_path: str,
    cell_num: int,
    vc_num: int,
    vc_mode: str,
    cycles: int,
    warmup: int,
    rdy_period: int = 0,
    rdy_high: int = 0,
    same_cycle_free: bool = False,
    check_every: int = 1,
    csv_path: str | None = None,
) -> dict:
    if cycles <= warmup:
        raise ValueError("cycles must exceed warmup")
    by_src = load_trace(trace_path)
    sources = [Source(src, by_src.get(src, []), gap=0) for src in range(2)]
    switch = Switch(
        sources,
        cell_num,
        vc_num,
        warmup,
        rdy_period=rdy_period,
        rdy_high=rdy_high,
        same_cycle_free=same_cycle_free,
        check_every=check_every,
    )
    for _ in range(warmup):
        switch.step()
    switch.stats.reset()
    switch.stats.per_vc_flits = [0] * vc_num
    for _ in range(cycles - warmup):
        switch.step()
    switch.finish()
    result = summarize(
        switch.stats,
        cycles - warmup,
        cell_num,
        vc_num,
        vc_mode,
        same_cycle_free,
        switch.invariant_checks,
    )
    trace_pkts = 0
    trace_flits = 0
    for packets in by_src.values():
        for packet in packets:
            if warmup <= packet.arrival < cycles:
                trace_pkts += 1
                trace_flits += packet.length
    result["trace_offered_pkts"] = trace_pkts
    result["trace_offered_flits"] = trace_flits
    result["trace_offered_tp"] = trace_flits / (cycles - warmup)
    result["trace_offered_pkt_rate"] = trace_pkts / (cycles - warmup)
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(
                ["seq", "src", "dst", "len", "vc", "arrival", "accepted", "start", "end"]
            )
            for p in sorted(
                switch.stats.all_delivered, key=lambda x: x.end or 0
            ):
                writer.writerow(
                    [
                        p.seq,
                        p.src,
                        p.dst,
                        p.length,
                        p.vc,
                        p.arrival,
                        p.accepted,
                        p.start,
                        p.end,
                    ]
                )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="E1 shared-buffer 2x2 cycle model")
    ap.add_argument("--trace", required=True)
    ap.add_argument("--cell-num", type=int, required=True)
    ap.add_argument("--vc-num", type=int, default=2)
    ap.add_argument("--vc-mode", default="per_dst")
    ap.add_argument("--cycles", type=int, default=4000)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--rdy-period", type=int, default=0)
    ap.add_argument("--rdy-high", type=int, default=0)
    ap.add_argument("--same-cycle-free", action="store_true")
    ap.add_argument("--check-every", type=int, default=1)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = run(
        args.trace,
        args.cell_num,
        args.vc_num,
        args.vc_mode,
        args.cycles,
        args.warmup,
        args.rdy_period,
        args.rdy_high,
        args.same_cycle_free,
        args.check_every,
        args.csv,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
