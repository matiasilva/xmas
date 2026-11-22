#!/usr/bin/env python3
"""Datasheet-to-pad check.

Compares what each part's datasheet says about its pins with the net that the
matching pad carries in tree.kicad_pcb.

    python3 checks/pad_check.py [path/to/tree.kicad_pcb]

Exit status is 1 if any check fails. Items that are only correct under a
stated assembly condition are printed as CONDITION and do not fail the run.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_pcb import Board  # noqa: E402

GND, VCC = '/GND', '/VCC'

# --- Datasheet facts --------------------------------------------------------

# Puya PY32F002B datasheet V1.8, table 3-2, QFN20 column (PY32F002BF15U).
U1_PINS = {
    '1': 'PC0/NRST', '2': 'PC1/OSCIN', '3': 'PB7/OSCOUT', '4': 'VSS',
    '5': 'PB6/SWDIO', '6': 'VCC', '7': 'PB5', '8': 'PB4', '9': 'PB3',
    '10': 'PB2', '11': 'PB1', '12': 'PB0', '13': 'PA0', '14': 'PA1',
    '15': 'PA2/SWCLK', '16': 'PA3', '17': 'PA4', '18': 'PA5', '19': 'PA6',
    '20': 'PA7',
}
# Same datasheet, tables 3-4 and 3-5: timer outputs available on each port pin.
TIMER_OUTPUTS = {
    'PA0': {'TIM1_CH1'}, 'PA1': {'TIM1_CH2'}, 'PA2': {'TIM1_CH4'},
    'PA3': {'TIM1_CH2'}, 'PA4': {'TIM1_CH3', 'TIM14_CH1'},
    'PA5': {'TIM1_CH1', 'TIM14_CH1'}, 'PA6': set(), 'PA7': {'TIM1_CH4'},
    'PB0': {'TIM1_CH2', 'TIM1_CH3N'}, 'PB1': {'TIM1_CH2N', 'TIM1_CH4'},
    'PB2': {'TIM1_CH1N', 'TIM1_CH3'}, 'PB5': {'TIM1_CH3', 'TIM14_CH1'},
    'PB7': {'TIM14_CH1'},
}
# Nets that must sit on a specific U1 pin function.
U1_FIXED = {'VSS': GND, 'VCC': VCC, 'PB6/SWDIO': '/SWDIO',
            'PA2/SWCLK': '/SWCLK', 'PC0/NRST': '/NRST'}
# PWM plan from TODO.md: the timer channel each LED net is meant to use.
PWM_PLAN = {'/LED1': 'TIM14_CH1', '/LED2': 'TIM1_CH1', '/LED3': 'TIM1_CH2',
            '/LED4': 'TIM1_CH4', '/LED5': 'TIM1_CH4', '/LED6': 'TIM1_CH3'}

# Chongtian CT-1608UOC-P6-0H (LCSC C52676004) and CT-1608URC-P6-0H (C52676005):
# both are reverse-polarity parts. Datasheet page 2: pin 1 is the marked end
# and is the anode (+); pin 2 is the cathode (-).
LED_ANODE_PIN = {'CT-1608UOC-P6-0H': '1', 'CT-1608URC-P6-0H': '1'}

# Which board pad the part's pin 1 (marked end) is fitted on. The project
# footprint LED_0603_1608Metric_ReversePolarity numbers its pads to match the
# part, so pin 1 goes on pad 1 and no rotation is needed at assembly.
LED_PIN1_ON_PAD = '1'

# XUNPU TS-1088-AR02016 (LCSC C720477): two-terminal SPST, either way round.
# J1 has no datasheet; it is checked against the silkscreen legend instead.
J1_LEGEND = {'1': GND, '2': VCC, '3': '/SWDIO', '4': '/SWCLK', '5': '/NRST'}
LEGEND_NAMES = {GND: 'GND', VCC: 'VTref', '/SWDIO': 'SWDIO', '/SWCLK': 'SWCLK', '/NRST': 'NRST'}

NOT_CHECKED = {
    'SW1': 'MSK12C02 slide switch: no datasheet has been read for it',
    'BT1': 'MY-2032-16 battery clip: no datasheet has been read for it',
}

results = []


def record(status, ref, text):
    results.append((status, ref, text))


def led_roles(board, ref):
    """Return (anode_pad, cathode_pad) for an LED, from how the board wires it:
    the anode pad is the one that reaches VCC through a resistor."""
    fp = board[ref]
    for pad in ('1', '2'):
        net = fp.net(pad)
        for other_ref, other_pad in board.on_net(net):
            if other_ref.startswith('R'):
                r = board[other_ref]
                far = r.net('2' if other_pad == '1' else '1')
                if far == VCC:
                    return pad, ('2' if pad == '1' else '1')
    raise ValueError('%s: neither pad reaches VCC through a resistor' % ref)


def check_u1(board):
    u1 = board['U1']
    name_net = {}
    for pin, name in U1_PINS.items():
        name_net[name] = u1.net(pin)
    for name, want in U1_FIXED.items():
        pin = [p for p, n in U1_PINS.items() if n == name][0]
        got = name_net[name]
        record('PASS' if got == want else 'FAIL', 'U1',
               'pin %s (%s) carries %s%s' % (pin, name, got, '' if got == want else ', expected ' + want))
    ep = u1.net('21')
    record('PASS' if ep == GND else 'FAIL', 'U1', 'exposed pad carries %s' % ep)
    for net, channel in PWM_PLAN.items():
        pins = [p for p in U1_PINS if u1.net(p) == net]
        if len(pins) != 1:
            record('FAIL', 'U1', '%s is on %d MCU pins' % (net, len(pins)))
            continue
        port = U1_PINS[pins[0]].split('/')[0]
        ok = channel in TIMER_OUTPUTS.get(port, set())
        record('PASS' if ok else 'FAIL', 'U1',
               '%s on pin %s (%s): %s %s' % (net, pins[0], port, channel,
                                              'is available' if ok else 'is NOT available on this pin'))
    used = set(U1_FIXED.values()) | set(PWM_PLAN) | {'/BTN'}
    for pin, name in U1_PINS.items():
        net = u1.net(pin)
        if net not in used and not net.startswith('unconnected-'):
            record('FAIL', 'U1', 'pin %s (%s) carries unexpected net %s' % (pin, name, net))
    btn = [p for p in U1_PINS if u1.net(p) == '/BTN']
    record('PASS' if len(btn) == 1 else 'FAIL', 'U1',
           'button net is on pin %s (%s)' % (btn[0], U1_PINS[btn[0]]) if len(btn) == 1 else 'button net is on %d pins' % len(btn))


def check_leds(board):
    for ref in board.refs('D'):
        fp = board[ref]
        if fp.value not in LED_ANODE_PIN:
            record('FAIL', ref, 'no datasheet data for part %s' % fp.value)
            continue
        anode_pad, cathode_pad = led_roles(board, ref)
        ds_anode = LED_ANODE_PIN[fp.value]
        ds_cathode = '2' if ds_anode == '1' else '1'
        # pad that each datasheet pin lands on under the stated assembly intent
        pin_to_pad = {'1': LED_PIN1_ON_PAD, '2': '2' if LED_PIN1_ON_PAD == '1' else '1'}
        ok = pin_to_pad[ds_anode] == anode_pad and pin_to_pad[ds_cathode] == cathode_pad
        record('PASS' if ok else 'FAIL', ref,
               '%s: datasheet anode (pin %s) on pad %s [%s], cathode on pad %s [%s]' % (
                   fp.value, ds_anode, pin_to_pad[ds_anode], fp.net(pin_to_pad[ds_anode]),
                   pin_to_pad[ds_cathode], fp.net(pin_to_pad[ds_cathode])))
        if LED_PIN1_ON_PAD != '1':
            record('CONDITION', ref,
                   'only correct if the marked end (pin 1) is fitted on pad %s; '
                   'fitted pin 1 on pad 1 it is reversed and will not light' % LED_PIN1_ON_PAD)


def check_sw2(board):
    sw = board['SW2']
    nets = {sw.net('1'), sw.net('2')}
    record('PASS' if nets == {'/BTN', GND} else 'FAIL', 'SW2',
           '%s: terminals carry %s (part is symmetrical)' % (sw.value, ' and '.join(sorted(nets))))


def check_j1(board):
    j1 = board['J1']
    for pad, want in J1_LEGEND.items():
        got = j1.net(pad)
        record('PASS' if got == want else 'FAIL', 'J1',
               'pad %s carries %s%s' % (pad, got, '' if got == want else ', expected ' + want))
    legend = ' '.join(t for t in board.texts if 'SWDIO' in t)
    pairs = dict(re.findall(r'(\d)\s+([A-Za-z]+)', legend))
    want_pairs = {pad: LEGEND_NAMES[net] for pad, net in J1_LEGEND.items()}
    record('PASS' if pairs == want_pairs else 'FAIL', 'J1',
           'silkscreen legend reads %s' % ', '.join('%s %s' % kv for kv in sorted(pairs.items())))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, '..', 'tree.kicad_pcb')
    board = Board(path)
    check_u1(board)
    check_leds(board)
    check_sw2(board)
    check_j1(board)
    for ref, why in NOT_CHECKED.items():
        if ref in board.footprints:
            record('SKIPPED', ref, why)
    width = max(len(r[1]) for r in results)
    for status, ref, text in results:
        print('%-9s %-*s  %s' % (status, width, ref, text))
    counts = {s: sum(1 for r in results if r[0] == s) for s in ('PASS', 'FAIL', 'CONDITION', 'SKIPPED')}
    print('\n%(PASS)d passed, %(FAIL)d failed, %(CONDITION)d conditional, %(SKIPPED)d not checked' % counts)
    return 1 if counts['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
