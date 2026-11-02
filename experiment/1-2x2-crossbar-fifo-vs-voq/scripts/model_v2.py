#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Edge-accurate 2x2 packet crossbar model, no-drop / backpressure.

Supported queue placements:
  - fifo: one shared input FIFO per input (HOL blocking)
  - voq:  one queue per input per output (no HOL)
  - xp:   one FIFO per crosspoint (input, output).  In the XP-only 2x2
          configuration this has the same observable queue semantics as the
          current IQ-VOQ reference, but it is a separate RTL/TB implementation
          and can be compared independently against the same trace.

Not yet implemented: output queues (OQ) and combined input/output queues
(CIOQ).

Timing model
------------
The model mirrors the RTL pipeline edge by edge:

  * A source loads one trace packet at cycle `arrival` (or later if busy) and
    writes its flits one per cycle, `loaded + 1` onwards.  At most one packet
    is outstanding per input.  After the last flit there is a one-cycle turn
    around before the next packet can be loaded, which matches the RTL TB.
  * The input FIFO is show-ahead.  A flit written at the end of cycle t is
    visible to the arbiter in cycle t+1.  A write is accepted only when the
    FIFO is non-full *at the start of the cycle*; a same-cycle read does not
    free a slot for that write (RTL fifo_sync contract).
  * An output grants a packet at cycle t from the head flits visible at the
    start of t.  The first flit leaves the FIFO at the end of t, so the RTL
    testbench labels it `t-1` (the TB samples at negedge and prints cycle-1).
    The model uses the same labels: start/end are `physical_cycle - 1`.
  * A multi-flit packet locks the output and input until EOP.  While locked
    the output keeps selecting the same input; if that FIFO is empty the
    output stalls without dropping the lock.

The model consumes the same trace.jsonl as the RTL testbench.  In a
deterministic trace, packets.csv (seq/src/dst/len/start/end) is the exact
model/RTL comparison contract.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class Packet:
    seq: int
    src: int
    dst: int
    length: int
    arrival: int
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
            accepted=self.accepted,
            start=self.start,
            end=self.end,
        )


@dataclass
class Flit:
    """One entry in an input queue.  Carries its packet and flit index."""

    packet: Packet
    index: int

    @property
    def sop(self) -> bool:
        return self.index == 0

    @property
    def eop(self) -> bool:
        return self.index == self.packet.length - 1


class InputQueue:
    """Flit-level queue bank.

    `fifo` ignores dst; `voq` and `xp` keep one queue per (input, output).
    The XP-only datapath performs the same flit-level no-drop operations as the
    current IQ-VOQ reference, so sharing the queue-bank implementation keeps
    the cycle contract identical without hiding any RTL difference.
    """

    def __init__(self, mode: str, depth: int):
        if mode not in ("fifo", "voq", "xp"):
            raise ValueError(mode)
        self.mode = mode
        self.depth = depth
        self.fifo: Deque[Flit] = deque()
        self.voqs: list[Deque[Flit]] = [deque(), deque()]
        self.flits = 0
        self.voq_flits = [0, 0]

    def can_write(self, dst: int) -> bool:
        """True if one more flit fits, using the start-of-cycle occupancy."""
        if self.mode == "fifo":
            return self.flits < self.depth
        return self.voq_flits[dst] < self.depth

    def push(self, flit: Flit) -> None:
        if self.mode == "fifo":
            self.fifo.append(flit)
        else:
            self.voqs[flit.packet.dst].append(flit)
            self.voq_flits[flit.packet.dst] += 1
        self.flits += 1

    def head(self) -> Flit | None:
        if self.mode == "fifo":
            return self.fifo[0] if self.fifo else None
        return None

    def head_for(self, dst: int) -> Flit | None:
        if self.mode == "fifo":
            if self.fifo and self.fifo[0].packet.dst == dst:
                return self.fifo[0]
            return None
        return self.voqs[dst][0] if self.voqs[dst] else None

    def pop_head(self, expected: Flit | None = None) -> Flit | None:
        """Remove the FIFO head (the flit selected at the start of the cycle)."""
        if self.mode == "fifo":
            if not self.fifo:
                return None
            flit = self.fifo.popleft()
        else:
            raise RuntimeError(
                "pop_head on a per-destination bank requires a destination"
            )
        if expected is not None and flit is not expected:
            raise AssertionError("queue head moved during a cycle")
        self.flits -= 1
        return flit

    def pop_for(self, dst: int, expected: Flit | None = None) -> Flit | None:
        if self.mode == "fifo":
            return self.pop_head(expected)
        if not self.voqs[dst]:
            return None
        flit = self.voqs[dst].popleft()
        if expected is not None and flit is not expected:
            raise AssertionError("voq head moved during a cycle")
        self.voq_flits[dst] -= 1
        self.flits -= 1
        return flit

    def is_empty(self) -> bool:
        return self.flits == 0

    def fifo_packets(self) -> list[Packet]:
        if self.mode != "fifo":
            return []
        seen: list[Packet] = []
        for flit in self.fifo:
            if flit.sop:
                seen.append(flit.packet)
        return seen

    def debug_occupancy(self, dst: int | None = None) -> int:
        if self.mode == "fifo" or dst is None:
            return self.flits
        return self.voq_flits[dst]


@dataclass
class Stats:
    source_stall_cycles: int = 0
    accepted_pkts: int = 0
    accepted_flits: int = 0
    delivered_pkts: int = 0
    delivered_flits: int = 0
    latency_sum: int = 0
    latency_n: int = 0
    queue_latency_sum: int = 0
    queue_latency_n: int = 0
    queue_occupancy_sum: int = 0
    queue_occupancy_n: int = 0
    max_total_occupancy: int = 0
    max_input_occupancy: int = 0
    max_single_voq_occupancy: int = 0
    output_idle_cycles: int = 0
    hol_cycles: int = 0
    per_src_flits: list[int] = field(default_factory=lambda: [0, 0])
    per_dst_flits: list[int] = field(default_factory=lambda: [0, 0])
    delivered: list[Packet] = field(default_factory=list)
    # Every packet delivered over the whole run, including warmup, for CSV
    # comparison with the RTL testbench (which has no warmup skip).
    all_delivered: list[Packet] = field(default_factory=list)

    def reset(self) -> None:
        self.source_stall_cycles = 0
        self.accepted_pkts = 0
        self.accepted_flits = 0
        self.delivered_pkts = 0
        self.delivered_flits = 0
        self.latency_sum = 0
        self.latency_n = 0
        self.queue_latency_sum = 0
        self.queue_latency_n = 0
        self.queue_occupancy_sum = 0
        self.queue_occupancy_n = 0
        self.max_total_occupancy = 0
        self.max_input_occupancy = 0
        self.max_single_voq_occupancy = 0
        self.output_idle_cycles = 0
        self.hol_cycles = 0
        self.per_src_flits = [0, 0]
        self.per_dst_flits = [0, 0]
        self.delivered = []
        # all_delivered is intentionally not cleared: it must keep the full
        # run so the packet CSV still matches the RTL when warmup > 0.


class Source:
    """One-outstanding-packet source that writes one flit per cycle.

    Loading a packet at cycle ``t`` makes it visible to the source one cycle
    later; the first flit is offered to the queue at cycle ``t+1``.  This is
    exactly the RTL TB source register behaviour.
    """

    def __init__(self, src: int, packets: list[Packet]):
        self.src = src
        self.packets = sorted(packets, key=lambda p: (p.arrival, p.seq))
        self.idx = 0
        self.current: Packet | None = None
        self.loaded_cycle: int | None = None
        self.flit_idx = 0
        self.last_write: Flit | None = None

    def step(
        self, cycle: int, queue: InputQueue, measure: bool, stats: Stats
    ) -> Flit | None:
        """Return a flit to write at the end of this cycle, or None."""
        self.last_write = None

        if self.current is None:
            if self.idx < len(self.packets):
                nxt = self.packets[self.idx]
                if nxt.arrival <= cycle:
                    # Register the packet at this edge; no flit write yet.
                    self.current = nxt
                    self.loaded_cycle = cycle
                    self.flit_idx = 0
                    self.idx += 1
            return None

        # Loaded at `loaded_cycle`, first flit offered from the next cycle on.
        if self.loaded_cycle is not None and cycle <= self.loaded_cycle:
            return None

        if not queue.can_write(self.current.dst):
            if measure:
                stats.source_stall_cycles += 1
            return None

        flit = Flit(packet=self.current, index=self.flit_idx)
        self.last_write = flit
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
        return flit


class Crossbar:
    def __init__(self, mode: str, depths: list[int], sources: list[Source], warmup: int):
        self.mode = mode
        self.queues = [InputQueue(mode, depths[i]) for i in range(2)]
        self.sources = sources
        self.warmup = warmup
        self.out_rr = [0, 0]
        self.locked = [False, False]
        self.locked_src = [0, 0]
        self.stats = Stats()
        self.cycle = 0
        self.debug_rows: list[list[str]] = []
        self.debug = False

    # -- statistics helpers -------------------------------------------------
    def _hol_this_cycle(self) -> bool:
        if self.mode != "fifo":
            return False
        busy_inputs = {self.locked_src[o] for o in range(2) if self.locked[o]}
        busy_outputs = {o for o in range(2) if self.locked[o]}
        for src in range(2):
            if src in busy_inputs:
                continue
            queue = self.queues[src]
            if not queue.fifo:
                continue
            head = queue.fifo[0]
            if head.packet.dst not in busy_outputs:
                continue
            for flit in list(queue.fifo)[1:]:
                if flit.sop and flit.packet.dst not in busy_outputs:
                    return True
        return False

    def _record_delivery(self, flit: Flit, cycle: int, measure: bool) -> None:
        packet = flit.packet
        self.stats.all_delivered.append(packet.copy())
        if not measure:
            return
        self.stats.delivered_pkts += 1
        self.stats.delivered_flits += packet.length
        self.stats.per_src_flits[packet.src] += packet.length
        self.stats.per_dst_flits[packet.dst] += packet.length
        assert packet.start is not None and packet.accepted is not None
        # Labels use the RTL TB convention: physical cycle - 1.
        self.stats.latency_sum += (cycle - 1) - packet.arrival
        self.stats.latency_n += 1
        self.stats.queue_latency_sum += packet.start - packet.accepted
        self.stats.queue_latency_n += 1
        self.stats.delivered.append(packet.copy())

    # -- one physical cycle -------------------------------------------------
    def _debug_snapshot(self) -> dict:
        """State visible during this cycle, before the edge at its end."""
        snap = {
            "sources": [],
            "occ": [],
            "head": [],
            "voq_occ": [],
            "voq_vld": [],
            "locked": None,
        }
        for src in range(2):
            source = self.sources[src]
            if source.current is None:
                snap["sources"].append(("0", "0", "-"))
            else:
                waiting = (
                    1
                    if source.loaded_cycle is not None
                    and self.cycle > source.loaded_cycle
                    else 0
                )
                snap["sources"].append(("1", str(waiting), str(source.flit_idx)))
            queue = self.queues[src]
            if self.mode == "fifo":
                head = queue.head()
                snap["occ"].append(queue.flits)
                snap["head"].append(
                    "-" if head is None else str(head.packet.dst)
                )
            else:
                snap["voq_occ"].append(list(queue.voq_flits))
                snap["voq_vld"].append(
                    [1 if queue.voqs[0] else 0, 1 if queue.voqs[1] else 0]
                )
        snap["locked"] = list(self.locked)
        snap["locked_src"] = list(self.locked_src)
        return snap

    def step(self) -> None:
        cycle = self.cycle
        measure = cycle >= self.warmup
        snap = self._debug_snapshot() if self.debug else None

        # 1) Source decisions use the start-of-cycle queue occupancy.  The
        #    writes commit at the end of the cycle (visible next cycle).
        writes: list[tuple[int, Flit]] = []
        for src in range(2):
            flit = self.sources[src].step(
                cycle, self.queues[src], measure, self.stats
            )
            if flit is not None:
                writes.append((src, flit))

        if measure and self._hol_this_cycle():
            self.stats.hol_cycles += 1

        # 2) Arbitration on the head flits visible at the start of the cycle.
        #    Output 0 is evaluated first, exactly like the RTL request masks.
        sel: list[int | None] = [None, None]  # source selected per output
        sel_flit: list[Flit | None] = [None, None]
        granted = [False, False]

        for out in range(2):
            if self.locked[out]:
                src = self.locked_src[out]
                head = self.queues[src].head_for(out)
                # A locked output keeps its lock even if the FIFO is empty.
                sel[out] = src
                sel_flit[out] = head
                continue

            req = [False, False]
            for src in range(2):
                # head_for() is the shared-FIFO head for mode=fifo and the
                # per-destination queue head for mode=voq/xp.
                head = self.queues[src].head_for(out)
                if head is None or head.packet.dst != out:
                    continue
                # An input already serving the other output cannot be reused.
                other = 1 - out
                if self.locked[other] and self.locked_src[other] == src:
                    continue
                # Output 1 is masked by output 0's combinational grant.
                if out == 1 and granted[0] and sel[0] == src:
                    continue
                req[src] = True

            if not any(req):
                continue
            first = self.out_rr[out]
            src = first if req[first] else (1 - first)
            head = self.queues[src].head_for(out)
            sel[out] = src
            sel_flit[out] = head
            granted[out] = True
            # RR pointer advances on the granted source, like arbiter_rr.
            self.out_rr[out] = 1 - src

        # 3) Output flits present this cycle (locked or newly granted).
        transfers: list[tuple[int, int, Flit]] = []
        for out in range(2):
            if sel[out] is None or sel_flit[out] is None:
                continue
            flit = sel_flit[out]
            transfers.append((out, sel[out], flit))
            packet = flit.packet
            if flit.sop:
                # TB samples at negedge and prints cycle-1.
                packet.start = cycle - 1
            if flit.eop:
                packet.end = cycle - 1
                self._record_delivery(flit, cycle, measure)
                # Lock is released at this edge.
                self.locked[out] = False
            elif granted[out]:
                # A new multi-flit packet locks output and input at this edge.
                self.locked[out] = True
                self.locked_src[out] = sel[out]

        # 4) Apply reads then writes at the end of the cycle.  Reads use the
        #    entries selected above; writes append behind them.  Capacity for
        #    the writes was already checked against the start-of-cycle count.
        for out, src, flit in transfers:
            popped = self.queues[src].pop_for(flit.packet.dst, expected=flit)
            if popped is None:
                raise AssertionError("selected flit vanished")
        for src, flit in writes:
            self.queues[src].push(flit)

        # 5) Statistics sampled after the edge (start of next cycle).
        if measure:
            busy_outputs = len(transfers)
            self.stats.output_idle_cycles += 2 - busy_outputs
            q0, q1 = self.queues[0].flits, self.queues[1].flits
            total_occ = q0 + q1
            self.stats.queue_occupancy_sum += total_occ
            self.stats.queue_occupancy_n += 2
            self.stats.max_total_occupancy = max(
                self.stats.max_total_occupancy, total_occ
            )
            self.stats.max_input_occupancy = max(
                self.stats.max_input_occupancy, q0, q1
            )
            if self.mode in ("voq", "xp"):
                for queue in self.queues:
                    for occ in queue.voq_flits:
                        self.stats.max_single_voq_occupancy = max(
                            self.stats.max_single_voq_occupancy, occ
                        )

        if self.debug:
            self._debug_row(snap, cycle, writes, transfers, granted)

        self.cycle += 1

    def _debug_row(
        self,
        snap: dict,
        cycle: int,
        writes: list[tuple[int, Flit]],
        transfers: list[tuple[int, int, Flit]],
        granted: list[bool],
    ) -> None:
        wr = {src: flit for src, flit in writes}
        tr = {out: (src, flit) for out, src, flit in transfers}
        row = [str(cycle)]
        for src in range(2):
            vld, ready, idx = snap["sources"][src]
            # A source stalls only when it has a flit ready but the write
            # could not be scheduled (target queue full at start of cycle).
            stall = "1" if ready == "1" and src not in wr else "0"
            if self.mode == "fifo":
                row += [
                    vld,
                    str(snap["occ"][src]),
                    snap["head"][src],
                    "1" if src in wr else "0",
                    stall,
                    idx,
                ]
            else:
                row += [
                    vld,
                    "1" if src in wr else "0",
                    stall,
                    idx,
                    str(snap["voq_occ"][src][0]),
                    str(snap["voq_occ"][src][1]),
                    str(snap["voq_vld"][src][0]),
                    str(snap["voq_vld"][src][1]),
                ]
        for out in range(2):
            if out in tr:
                src, flit = tr[out]
                row += [
                    str(src),
                    "1",
                    "1" if flit.sop else "0",
                    "1" if flit.eop else "0",
                    "1" if granted[out] else "0",
                ]
            else:
                row += ["-", "0", "0", "0", "0"]
            row += [
                "1" if snap["locked"][out] else "0",
                str(snap["locked_src"][out]),
            ]
        self.debug_rows.append(row)

    def finish(self, cycles: int) -> None:
        # Packets still in flight at the end of the run are simply not
        # delivered; there is no synthetic drop.
        pass


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


def summarize(stats: Stats, cycles: int, mode: str, depths: list[int]) -> dict:
    delivered_tp = stats.delivered_flits / cycles
    latencies = [
        p.end - p.arrival
        for p in stats.delivered
        if p.end is not None and p.arrival is not None
    ]
    return {
        "mode": mode,
        "depth": depths,
        "delivered_pkts": stats.delivered_pkts,
        "delivered_flits": stats.delivered_flits,
        "delivered_tp": delivered_tp,
        "utilization": delivered_tp / 2.0,
        "accepted_pkts": stats.accepted_pkts,
        "accepted_flits": stats.accepted_flits,
        "accepted_tp": stats.accepted_flits / cycles,
        "avg_pkt_latency": (
            stats.latency_sum / stats.latency_n if stats.latency_n else 0.0
        ),
        "p99_pkt_latency": percentile(latencies, 0.99),
        "avg_queue_latency": (
            stats.queue_latency_sum / stats.queue_latency_n
            if stats.queue_latency_n
            else 0.0
        ),
        "avg_queue_occupancy": (
            stats.queue_occupancy_sum / stats.queue_occupancy_n
            if stats.queue_occupancy_n
            else 0.0
        ),
        "avg_total_queue_occupancy": (
            stats.queue_occupancy_sum / (cycles)
            if stats.queue_occupancy_n
            else 0.0
        ),
        "max_total_queue_occupancy": stats.max_total_occupancy,
        "max_input_queue_occupancy": stats.max_input_occupancy,
        "max_single_voq_occupancy": stats.max_single_voq_occupancy,
        "max_single_dst_queue_occupancy": stats.max_single_voq_occupancy,
        "source_stall_rate": stats.source_stall_cycles / (cycles * 2),
        "output_idle_cycles": stats.output_idle_cycles,
        "output_idle_rate": stats.output_idle_cycles / (cycles * 2),
        "hol_cycles": stats.hol_cycles,
        "hol_rate": stats.hol_cycles / cycles,
        "jain": jain(stats.per_src_flits),
        "jain_dst": jain(stats.per_dst_flits),
        "per_src_0_tp": stats.per_src_flits[0] / cycles,
        "per_src_1_tp": stats.per_src_flits[1] / cycles,
        "per_dst_0_tp": stats.per_dst_flits[0] / cycles,
        "per_dst_1_tp": stats.per_dst_flits[1] / cycles,
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
                )
            )
    return by_src


def run(
    trace_path: str,
    mode: str,
    total_buffer: int,
    cycles: int,
    warmup: int,
    csv_path: str | None,
    cycles_csv: str | None = None,
    per_queue_depth: int | None = None,
) -> dict:
    by_src = load_trace(trace_path)
    sources = [Source(src, by_src.get(src, [])) for src in range(2)]
    if per_queue_depth is not None:
        # Phase 2: capacity is per queue, orthogonal to the queue type.
        # FIFO: per-input shared FIFO; VOQ: per (input, output) queue.
        depths = [per_queue_depth, per_queue_depth]
    elif mode == "fifo":
        depths = [total_buffer // 2, total_buffer // 2]
    elif mode in ("voq", "xp"):
        depths = [total_buffer // 4, total_buffer // 4]
    else:
        raise ValueError(mode)
    if depths[0] <= 0:
        raise ValueError("queue depth must be positive")
    crossbar = Crossbar(mode, depths, sources, warmup)
    crossbar.debug = cycles_csv is not None
    for _ in range(warmup):
        crossbar.step()
    crossbar.stats.reset()
    for _ in range(cycles - warmup):
        crossbar.step()
    result = summarize(crossbar.stats, cycles - warmup, mode, depths)
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
            writer = csv.writer(f)
            writer.writerow(
                ["seq", "src", "dst", "len", "arrival", "accepted", "start", "end"]
            )
            for p in sorted(crossbar.stats.all_delivered, key=lambda x: x.end or 0):
                writer.writerow(
                    [p.seq, p.src, p.dst, p.length, p.arrival, p.accepted, p.start, p.end]
                )
    if cycles_csv:
        with open(cycles_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["cycle"]
            for src in range(2):
                if mode == "fifo":
                    header += [
                        f"in{src}_vld",
                        f"in{src}_occ",
                        f"in{src}_head_dst",
                        f"in{src}_wr",
                        f"in{src}_stall",
                        f"in{src}_flit",
                    ]
                else:
                    header += [
                        f"in{src}_vld",
                        f"in{src}_wr",
                        f"in{src}_stall",
                        f"in{src}_flit",
                        f"in{src}_occ_d0",
                        f"in{src}_occ_d1",
                        f"in{src}_vld_d0",
                        f"in{src}_vld_d1",
                    ]
            for out in range(2):
                header += [
                    f"out{out}_src",
                    f"out{out}_vld",
                    f"out{out}_sop",
                    f"out{out}_eop",
                    f"out{out}_grant",
                    f"out{out}_locked",
                    f"out{out}_locked_src",
                ]
            writer.writerow(header)
            writer.writerows(crossbar.debug_rows)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="edge-accurate no-drop crossbar model")
    parser.add_argument("--trace", required=True)
    parser.add_argument("--mode", choices=["fifo", "voq", "xp"], required=True)
    parser.add_argument("--total-buffer", type=int, default=64)
    parser.add_argument("--per-queue-depth", type=int, default=None,
                        help="capacity per queue (FIFO per input, VOQ/XP per crosspoint)")
    parser.add_argument("--cycles", type=int, default=100_000)
    parser.add_argument("--warmup", type=int, default=10_000)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--cycles-csv", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.cycles <= args.warmup:
        print("ERROR: cycles must exceed warmup", file=sys.stderr)
        return 2
    if args.per_queue_depth is not None:
        if args.per_queue_depth <= 0:
            print("ERROR: per-queue-depth must be positive", file=sys.stderr)
            return 2
    elif args.total_buffer <= 0:
        print("ERROR: total-buffer must be positive", file=sys.stderr)
        return 2
    result = run(
        args.trace,
        args.mode,
        args.total_buffer,
        args.cycles,
        args.warmup,
        args.csv,
        args.cycles_csv,
        args.per_queue_depth,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
