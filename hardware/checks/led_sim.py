#!/usr/bin/env python3
"""LED polarity simulation.

Builds a SPICE circuit from the pad-to-net data in tree.kicad_pcb and runs a
few DC operating points with ngspice. The MCU is not modelled: each LED pin is
a stub that is driven low, driven high, or left floating.

    python3 checks/led_sim.py [path/to/tree.kicad_pcb]

ngspice is taken from the PATH if present, otherwise from the library bundled
with KiCad (override with NGSPICE_LIB=/path/to/libngspice). Exit status is 1
if any expectation fails.
"""
import ctypes
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_pcb import Board  # noqa: E402
from pad_check import LED_ANODE_PIN, LED_PIN1_ON_PAD, VCC, GND  # noqa: E402

VBAT = 3.0          # fresh CR2032, volts
RBAT = 15.0         # cell internal resistance, ohms
RPIN = 30.0         # stub output resistance of an MCU pin, ohms
LIT_MIN, LIT_MAX = 0.3e-3, 3e-3   # a lit LED should carry between these, amps
DARK_MAX = 20e-6                  # a dark LED must carry less than this, amps
VR_MAX = 5.0                      # datasheet maximum reverse voltage, volts

# Typical diode model fitted to the datasheets: about 2.0 V at 5 mA,
# 10 uA reverse leakage at 5 V.
LED_MODEL = '.model LED D(Is=7.9e-20 N=2 Rs=4 BV=5 IBV=10u)'

KICAD_LIBS = [
    '/Applications/KiCad/KiCad.app/Contents/Frameworks/libngspice.0.dylib',
    '/usr/lib/x86_64-linux-gnu/libngspice.so.0',
    '/usr/lib/libngspice.so.0',
    r'C:\Program Files\KiCad\*\bin\libngspice-0.dll',
]


class Ngspice:
    def __init__(self):
        self.cli = shutil.which('ngspice')
        self.lib = None
        if self.cli:
            return
        candidates = [os.environ['NGSPICE_LIB']] if os.environ.get('NGSPICE_LIB') else []
        for pattern in KICAD_LIBS:
            candidates += glob.glob(pattern)
        for path in candidates:
            if os.path.exists(path):
                self._load(path)
                return
        sys.exit('ngspice not found: install it or set NGSPICE_LIB')

    def _load(self, path):
        self.lib = ctypes.CDLL(path)
        self.out = []
        text_cb = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        exit_cb = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool,
                                   ctypes.c_int, ctypes.c_void_p)
        bg_cb = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
        self._keep = (
            text_cb(lambda s, i, u: (self.out.append(s.decode(errors='replace')), 0)[1]),
            text_cb(lambda s, i, u: 0),
            exit_cb(lambda a, b, c, d, u: 0),
            bg_cb(lambda a, b, u: 0),
        )
        self.lib.ngSpice_Init.argtypes = [text_cb, text_cb, exit_cb, ctypes.c_void_p,
                                          ctypes.c_void_p, bg_cb, ctypes.c_void_p]
        self.lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
        self.lib.ngSpice_Init(self._keep[0], self._keep[1], self._keep[2], None, None, self._keep[3], None)

    def run(self, netlist):
        """Run a netlist that prints values; return {name: float}."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'c.cir')
            with open(path, 'w') as f:
                f.write(netlist)
            if self.cli:
                text = subprocess.run([self.cli, '-b', path], capture_output=True, text=True).stdout
            else:
                self.out = []
                self.lib.ngSpice_Command(('source ' + path).encode())
                text = '\n'.join(self.out)
                self.lib.ngSpice_Command(b'destroy all')
                self.lib.ngSpice_Command(b'remcirc')
        values = {}
        for name, number in re.findall(r'([a-z]\([a-z0-9_]+\))\s*=\s*([-+0-9.eE]+)', text):
            values[name] = float(number)
        return values


def build(board, pin_state, pin1_on_pad):
    """Netlist for one scenario.

    pin_state: {led net: 'low' | 'high' | 'hiz'}
    pin1_on_pad: '1' or '2', the pad the LEDs' marked end is fitted on.
    """
    nodes = {GND: '0'}

    def node(net):
        if net not in nodes:
            nodes[net] = 'n%d' % len(nodes)
        return nodes[net]

    bt, sw1 = board['BT1'], board['SW1']
    lines = ['* generated from tree.kicad_pcb',
             'Vbat batt 0 %g' % VBAT,
             'Rbat batt %s %g' % (node(bt.net('1')), RBAT),
             '* slide switch closed between pads 2 and 3',
             'Rsw1 %s %s 0.01' % (node(sw1.net('2')), node(sw1.net('3')))]
    if node(bt.net('2')) != '0':
        raise ValueError('battery negative is not on GND')
    for ref in board.refs('R'):
        r = board[ref]
        ohms = float(r.value.lower().replace('k', 'e3').replace('r', ''))
        lines.append('%s %s %s %g' % (ref, node(r.net('1')), node(r.net('2')), ohms))
    for ref in board.refs('C'):
        c = board[ref]
        lines.append('%s %s %s 100n' % (ref, node(c.net('1')), node(c.net('2'))))
    probes = {}
    for ref in board.refs('D'):
        fp = board[ref]
        anode_pin = LED_ANODE_PIN[fp.value]
        pad_of = {'1': pin1_on_pad, '2': '2' if pin1_on_pad == '1' else '1'}
        anode_net = fp.net(pad_of[anode_pin])
        cathode_net = fp.net(pad_of['2' if anode_pin == '1' else '1'])
        lines.append('%s %s %s LED' % (ref, node(anode_net), node(cathode_net)))
    # MCU stub: one ammeter and one driver per LED pin, nothing else of U1
    u1 = board['U1']
    for led_net in sorted(pin_state):
        pads = [p for p, nets in u1.pads.items() if led_net in nets]
        if len(pads) != 1:
            raise ValueError('%s is not on exactly one U1 pad' % led_net)
        tag = led_net.strip('/').lower()
        lines.append('Vp_%s %s stub_%s 0' % (tag, node(led_net), tag))
        state = pin_state[led_net]
        if state == 'low':
            lines.append('Rs_%s stub_%s 0 %g' % (tag, tag, RPIN))
        elif state == 'high':
            lines.append('Rs_%s stub_%s %s %g' % (tag, tag, node(VCC), RPIN))
        else:
            lines.append('Rs_%s stub_%s 0 1e9' % (tag, tag))
        probes[led_net] = 'vp_%s' % tag
    lines.append(LED_MODEL)
    prints = ' '.join('i(%s)' % p for p in probes.values())
    volts = ' '.join('v(%s)' % node(n) for n in sorted(pin_state)) + ' v(%s)' % node(VCC)
    lines += ['.control', 'op', 'print ' + prints, 'print ' + volts, '.endc', '.end', '']
    return '\n'.join(lines), probes, nodes


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', 'tree.kicad_pcb')
    board = Board(path)
    spice = Ngspice()
    led_of = {}  # led net -> LED reference
    for ref in board.refs('D'):
        for pad in ('1', '2'):
            net = board[ref].net(pad)
            if net.startswith('/LED'):
                led_of[net] = ref
    nets = sorted(led_of)
    other = '1' if LED_PIN1_ON_PAD == '2' else '2'

    scenarios = [('all pins low', {n: 'low' for n in nets}, LED_PIN1_ON_PAD, {n: 'lit' for n in nets})]
    for only in nets:
        scenarios.append(('only %s low' % led_of[only],
                          {n: ('low' if n == only else 'high') for n in nets}, LED_PIN1_ON_PAD,
                          {n: ('lit' if n == only else 'dark') for n in nets}))
    scenarios.append(('all pins floating', {n: 'hiz' for n in nets}, LED_PIN1_ON_PAD, {n: 'dark' for n in nets}))
    scenarios.append(('all pins low, LEDs fitted pin 1 on pad %s' % other,
                      {n: 'low' for n in nets}, other, {n: 'dark' for n in nets}))

    print('LED marked end (pin 1) on pad %s unless stated. Currents in mA.\n' % LED_PIN1_ON_PAD)
    head = '%-40s' % 'scenario' + ''.join('%8s' % led_of[n] for n in nets) + '   result'
    print(head)
    print('-' * len(head))
    failed = 0
    for name, state, pad, expect in scenarios:
        netlist, probes, nodes = build(board, state, pad)
        values = spice.run(netlist)
        row, ok = '', True
        vcc = values.get('v(%s)' % nodes[VCC])
        for n in nets:
            key = 'i(%s)' % probes[n]
            if key not in values:
                sys.exit('ngspice gave no value for %s in scenario "%s"' % (key, name))
            amps = values[key]
            row += '%8.3f' % (amps * 1e3)
            if expect[n] == 'lit':
                ok &= LIT_MIN <= amps <= LIT_MAX
            else:
                ok &= abs(amps) < DARK_MAX
            # reverse voltage across the LED when it is the wrong way round
            reverse = vcc - values['v(%s)' % nodes[n]] if pad != LED_PIN1_ON_PAD else 0.0
            ok &= reverse <= VR_MAX
        failed += 0 if ok else 1
        print('%-40s%s   %s' % (name, row, 'as expected' if ok else 'UNEXPECTED'))
    print('\n%d scenarios, %d unexpected' % (len(scenarios), failed))
    print('Expected: a lit LED carries %.1f-%.1f mA, a dark one under %.0f uA.' % (
        LIT_MIN * 1e3, LIT_MAX * 1e3, DARK_MAX * 1e6))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
