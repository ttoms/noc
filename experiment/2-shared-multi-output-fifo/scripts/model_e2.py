#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle model of the E2 2x2 switch with registered mo_fifo selection.

This mirrors the RTL state machines, not the earlier E1 combinational model:
  * per input: SharedFifo cell pool + VC queues
  * per input/output: registered selection (sel_vld/sel_vc/vc_locked) + RR
  * per output: external 2:1 RR + packet lock, combinational output mux
  * source writes at the end of a cycle; same-cycle read/free cells can be reused

The model is intended for trace-driven comparison with `xbar_2x2_shared`.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve()
EXP1 = HERE.parents[2] / "1-2x2-crossbar-fifo-vs-voq"
sys.path.insert(0, str(EXP1 / "scripts"))

from model_e1 import Packet, SharedFifo  # noqa: E402


def load_trace(path: str) -> dict[int, list[Packet]]:
    by_src: dict[int, list[Packet]] = {0: [], 1: []}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            src = int(r["src"])
            by_src.setdefault(src, []).append(
                Packet(
                    seq=int(r["seq"]),
                    src=src,
                    dst=int(r["dst"]),
                    length=int(r["len"]),
                    arrival=int(r["arrival"]),
                    vc=int(r.get("vc", 0)),
                )
            )
    return by_src


class Source:
    def __init__(self, packets: list[Packet]):
        self.packets = sorted(packets, key=lambda p: (p.arrival, p.seq))
        self.idx = 0
        self.current: Packet | None = None
        self.loaded_cycle: int | None = None
        self.flit_idx = 0
        self.stall_cycles = 0
        self.accepted_flits = 0

    def step(self, cycle: int, fifo: SharedFifo, extra_free: int) -> tuple[Packet, int] | None:
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
            self.stall_cycles += 1
            return None
        flit = (self.current, self.flit_idx)
        if self.flit_idx == 0:
            self.current.accepted = cycle
        self.accepted_flits += 1
        self.flit_idx += 1
        if self.flit_idx == self.current.length:
            self.current = None
            self.loaded_cycle = None
            self.flit_idx = 0
            if self.idx < len(self.packets):
                nxt = self.packets[self.idx]
                if nxt.arrival <= cycle:
                    self.current = nxt
                    self.loaded_cycle = cycle
                    self.idx += 1
        return flit


class MoFifo:
    """One input's shared FIFO with registered per-output selection."""

    def __init__(self, fifo: SharedFifo, n_out: int):
        self.fifo = fifo
        self.n_out = n_out
        self.vc_num = fifo.vc_num
        self.sel_vld = [False] * n_out
        self.sel_vc = [0] * n_out
        self.rr = [0] * n_out

    def empty_vc(self, vc: int) -> bool:
        return not self.fifo.vc_q[vc]

    def head(self, vc: int):
        return self.fifo.head(vc)

    def out_vld(self, out: int) -> bool:
        return self.sel_vld[out] and not self.empty_vc(self.sel_vc[out])

    def out_meta(self, out: int):
        if not self.out_vld(out):
            return None
        return self.head(self.sel_vc[out])

    def pick(self, out: int) -> int | None:
        start = self.rr[out]
        for k in range(self.vc_num):
            vc = (start + k) % self.vc_num
            if self.fifo.vc_locked_to[vc] is not None:
                continue
            head = self.head(vc)
            if head is not None and head.dst == out:
                return vc
        return None

    def transfer(self, out: int, cycle: int):
        """Pop the selected cell; set packet timestamps; return the cell."""
        if not self.out_vld(out):
            return None
        vc = self.sel_vc[out]
        cell = self.head(vc)
        # The RTL TB samples at negedge and prints physical_cycle - 1.
        if cell.sop:
            cell.packet.start = cycle - 1
        if cell.eop:
            cell.packet.end = cycle - 1
        self.fifo.pop(vc)
        if cell.eop:
            self.sel_vld[out] = False
            self.fifo.vc_locked_to[vc] = None
        return cell

    def latch_selection(self, out: int, vc: int) -> None:
        self.sel_vld[out] = True
        self.sel_vc[out] = vc
        self.fifo.vc_locked_to[vc] = out
        self.rr[out] = (vc + 1) % self.vc_num


@dataclass
class Stats:
    delivered: list[Packet] = field(default_factory=list)
    accepted_pkts: int = 0
    accepted_flits: int = 0
    delivered_pkts: int = 0
    delivered_flits: int = 0
    source_stalls: int = 0


class Switch:
    def __init__(self, sources, cell_num, vc_num, n_out, warmup=0,
                 rdy_period=0, rdy_high=0):
        self.n_out = n_out
        self.warmup = warmup
        self.fifos = [SharedFifo(i, cell_num, vc_num) for i in range(2)]
        self.mo = [MoFifo(f, n_out) for f in self.fifos]
        self.sources = sources
        self.locked = [False] * n_out
        self.locked_in = [0] * n_out
        self.rr_out = [0] * n_out
        self.stats = Stats()
        self.cycle = 0
        self.rdy_period = rdy_period
        self.rdy_high = rdy_high

    def _out_ready(self, out: int, cycle: int) -> bool:
        if self.rdy_period <= 0:
            return True
        return ((cycle + 2 * out) % self.rdy_period) < self.rdy_high

    def step(self) -> None:
        cycle = self.cycle
        measure = cycle >= self.warmup

        # Start-of-cycle visible outputs from the input FIFOs.
        f_vld = [[self.mo[i].out_vld(o) for o in range(self.n_out)] for i in range(2)]
        f_meta = [[self.mo[i].out_meta(o) for o in range(self.n_out)] for i in range(2)]

        # External output selection (combinational) + registered lock.
        gnt_vld = [False] * self.n_out
        sel_in = [0] * self.n_out
        out_vld = [False] * self.n_out
        transfers: list[tuple[int, int, bool]] = []
        for o in range(self.n_out):
            if self.locked[o]:
                sel_in[o] = self.locked_in[o]
                out_vld[o] = f_vld[sel_in[o]][o]
            else:
                req0 = f_vld[0][o]
                req1 = f_vld[1][o]
                if not req0 and not req1:
                    continue
                first = self.rr_out[o]
                i = first if (req0 if first == 0 else req1) else 1 - first
                gnt_vld[o] = True
                sel_in[o] = i
                self.rr_out[o] = 1 - i
                out_vld[o] = f_vld[i][o]
            if out_vld[o] and self._out_ready(o, cycle):
                meta = f_meta[sel_in[o]][o]
                transfers.append((sel_in[o], o, meta.eop))

        # A read frees a cell; the same-cycle source write may reuse it.
        frees = [0, 0]
        for i, o, _ in transfers:
            frees[i] += 1

        writes: list[tuple[int, Packet, int]] = []
        for i in range(2):
            flit = self.sources[i].step(cycle, self.fifos[i], frees[i])
            if flit is not None:
                pkt, idx = flit
                writes.append((i, pkt, idx))
                if idx == 0:
                    self.stats.accepted_pkts += 1
                self.stats.accepted_flits += 1

        # Internal selection for the next cycle is based on pre-pop state.
        latch: list[tuple[int, int, int]] = []
        for i in range(2):
            for o in range(self.n_out):
                if self.mo[i].sel_vld[o]:
                    continue
                vc = self.mo[i].pick(o)
                if vc is not None:
                    latch.append((i, o, vc))

        # Read handshakes: pop cells and release EOP locks.
        for i, o, eop in transfers:
            cell = self.mo[i].transfer(o, cycle)
            if measure:
                self.stats.delivered_flits += 1
            if eop:
                self.stats.delivered_pkts += 1
                self.stats.delivered.append(cell.packet.copy())
                self.locked[o] = False
        # Apply external lock for grants that did not transfer EOP.
        for o in range(self.n_out):
            if self.locked[o]:
                continue
            if gnt_vld[o]:
                transferred_eop = any(
                    i == sel_in[o] and oo == o and eop
                    for i, oo, eop in transfers
                )
                if not transferred_eop:
                    self.locked[o] = True
                    self.locked_in[o] = sel_in[o]
        # Apply internal selections.
        for i, o, vc in latch:
            self.mo[i].latch_selection(o, vc)

        # Apply writes after reads, so a freed cell can be reused.
        for i, pkt, idx in writes:
            self.fifos[i].push(pkt, idx)

        for f in self.fifos:
            f.check()
        self.cycle += 1


def run(trace_path: str, cell_num: int, vc_num: int, n_out: int,
        cycles: int, warmup: int, csv_path: str | None = None,
        rdy_period: int = 0, rdy_high: int = 0) -> dict:
    by_src = load_trace(trace_path)
    sources = [Source(by_src.get(0, [])), Source(by_src.get(1, []))]
    sw = Switch(sources, cell_num, vc_num, n_out, warmup,
                rdy_period=rdy_period, rdy_high=rdy_high)
    for _ in range(warmup):
        sw.step()
    sw.stats = Stats()
    for _ in range(cycles - warmup):
        sw.step()
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["seq", "src", "dst", "len", "vc", "arrival", "accepted", "start", "end"])
            for p in sw.stats.delivered:
                w.writerow([p.seq, p.src, p.dst, p.length, p.vc,
                            p.arrival, p.accepted, p.start, p.end])
    return {
        "delivered_pkts": sw.stats.delivered_pkts,
        "delivered_flits": sw.stats.delivered_flits,
        "accepted_pkts": sw.stats.accepted_pkts,
        "accepted_flits": sw.stats.accepted_flits,
        "source_stalls": sum(s.stall_cycles for s in sources),
        "cycle": sw.cycle,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--cell-num", type=int, default=16)
    ap.add_argument("--vc-num", type=int, default=2)
    ap.add_argument("--n-out", type=int, default=2)
    ap.add_argument("--cycles", type=int, default=2600)
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--rdy-period", type=int, default=0)
    ap.add_argument("--rdy-high", type=int, default=0)
    args = ap.parse_args()
    print(run(args.trace, args.cell_num, args.vc_num, args.n_out,
              args.cycles, args.warmup, args.csv,
              args.rdy_period, args.rdy_high))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
