"""SeizeIT2 motion -> the compact files eval_seizeit2 reads.

SeizeIT2 is OpenNeuro ds005873 (CC0). Download the `*_mov.edf` and
`*_events.tsv` files of the runs you want into <src>/mov and <src>/events,
then:

    python3 seizeit2_convert.py <src> <out>
    make eval-seizeit2 SEIZEIT2=<out>

For each run: <out>/<run>.acc = float32 ax,ay,az at 25 Hz from the chest
(ECG/EMG) Sensor Dot, or the upper-back one when the chest one is missing,
scaled so the run's median |a| is 1 g (the files' scales differ by hospital);
<out>/<run>.sz = one line per seizure: onset_s duration_s type.
Standard library only.
"""
import os
import statistics
import struct
import sys


def read_edf(path):
    """{label: [physical values]} for every signal except annotations."""
    with open(path, 'rb') as f:
        head = f.read(256)
        ns, nrec = int(head[252:256]), int(head[236:244])
        h = f.read(ns * 256)

        def col(offset, width):
            return [h[offset * ns + i * width:offset * ns + (i + 1) * width].decode().strip() for i in range(ns)]

        labels = col(0, 16)
        o = 16 + 80 + 8
        pmin, pmax = [float(x) for x in col(o, 8)], [float(x) for x in col(o + 8, 8)]
        dmin, dmax = [float(x) for x in col(o + 16, 8)], [float(x) for x in col(o + 24, 8)]
        nsamp = [int(x) for x in col(o + 32 + 80, 8)]
        record = sum(nsamp) * 2
        data = f.read(nrec * record)
    out = {l: [] for l in labels if not l.startswith('EDF')}
    for r in range(nrec):
        base = r * record
        for i, label in enumerate(labels):
            n = nsamp[i]
            if not label.startswith('EDF'):
                gain = (pmax[i] - pmin[i]) / (dmax[i] - dmin[i])
                out[label].extend(pmin[i] + (v - dmin[i]) * gain for v in struct.unpack_from('<%dh' % n, data, base))
            base += 2 * n
    return out


def main(src, out):
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(src, 'mov'))):
        if not name.endswith('_mov.edf'):
            continue
        run = name[:-len('_mov.edf')]
        dst = os.path.join(out, run + '.acc')
        if os.path.exists(dst):
            continue
        ch = read_edf(os.path.join(src, 'mov', name))
        pre = 'ECGEMG SD' if 'ECGEMG SD ACC X' in ch else 'EEG SD'  # chest, else upper back
        x, y, z = ch[pre + ' ACC X'], ch[pre + ' ACC Y'], ch[pre + ' ACC Z']
        k = 1.0 / statistics.median((a * a + b * b + c * c) ** 0.5 for a, b, c in zip(x[::50], y[::50], z[::50]))
        with open(dst + '.tmp', 'wb') as f:
            f.write(struct.pack('<%df' % (3 * len(x)), *[v * k for t in zip(x, y, z) for v in t]))
        os.rename(dst + '.tmp', dst)
        with open(os.path.join(src, 'events', run + '_events.tsv')) as f, open(os.path.join(out, run + '.sz'), 'w') as o:
            for line in f.read().splitlines()[1:]:
                c = line.split('\t')
                if c[2].startswith('sz'):
                    o.write('%s %s %s\n' % (c[0], c[1], c[2]))
        print(run, pre, 'hours %.1f' % (len(x) / 25 / 3600), flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
