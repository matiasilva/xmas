"""Minimal reader for a .kicad_pcb file: footprints, their pads and nets.

Pure standard library, so the checks run with any Python 3.
"""
import re

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


def parse(text):
    stack = [[]]
    for tok in _TOKEN.findall(text):
        if tok == '(':
            stack.append([])
        elif tok == ')':
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace('\\n', '\n'))
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _children(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


class Footprint:
    def __init__(self, node):
        self.lib_id = node[1]
        self.props = {p[1]: p[2] for p in _children(node, 'property') if len(p) > 2}
        self.ref = self.props.get('Reference', '?')
        self.value = self.props.get('Value', '')
        self.pads = {}  # pad number -> net name ('' if none)
        for pad in _children(node, 'pad'):
            number = pad[1]
            if number == '':
                continue  # paste-only apertures and mounting holes
            nets = _children(pad, 'net')
            net = nets[0][-1] if nets else ''
            self.pads.setdefault(number, set()).add(net)

    def net(self, pad):
        nets = self.pads.get(str(pad))
        if not nets:
            raise KeyError('%s has no pad %s' % (self.ref, pad))
        if len(nets) > 1:
            raise ValueError('%s pad %s is on several nets: %s' % (self.ref, pad, sorted(nets)))
        return next(iter(nets))


class Board:
    def __init__(self, path):
        with open(path, encoding='utf-8') as f:
            tree = parse(f.read())
        self.footprints = {}
        for node in _children(tree, 'footprint'):
            fp = Footprint(node)
            self.footprints[fp.ref] = fp
        self.texts = [t[1] for t in _children(tree, 'gr_text')]

    def __getitem__(self, ref):
        return self.footprints[ref]

    def refs(self, prefix):
        found = [r for r in self.footprints if re.fullmatch(prefix + r'\d+', r)]
        return sorted(found, key=lambda r: int(r[len(prefix):]))

    def on_net(self, net):
        """All (ref, pad) pairs on a net."""
        return sorted((fp.ref, pad) for fp in self.footprints.values()
                      for pad, nets in fp.pads.items() if net in nets)
