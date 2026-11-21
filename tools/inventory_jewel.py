#!/usr/bin/env python3
"""Index JEWEL 2.6.0 Fortran units and direct Pythia dependencies (static scan).

No source is changed. Prefer .stock backups, where present. This is a lexical
index, not a Fortran compiler/call graph: continuation-line arguments and
indirect dependencies need the manual review described in the porting plan.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

UNIT = re.compile(r'^\s*(?:(?:DOUBLE\s+PRECISION|REAL(?:\*\d+)?|INTEGER|LOGICAL)\s+)?(PROGRAM|SUBROUTINE|FUNCTION)\s+(\w+)', re.I)
COMMON = re.compile(r'\bCOMMON\s*/(\w+)/', re.I)
PYREF = re.compile(r'\b(PY\w+)\s*\(', re.I)
CALL = re.compile(r'\bCALL\s+(\w+)', re.I)
DECL = re.compile(r'^\s*(?:DOUBLE\s+PRECISION|INTEGER|LOGICAL|REAL|EXTERNAL|COMMON|DIMENSION|CHARACTER|SAVE|DATA)\b', re.I)

# Reviewed proposed ownership; these are migration assignments, not existing C++ classes.
GROUPS = {
 'RunDriver': 'JEWEL INIT GENEVENT PRINTLOGO PRINTTIME',
 'Pythia8InputAdapter': 'INITPYTHIA INTERPRETPYTHIAEVENT FINDSPECLINES SETCOLOUR',
 'InitialVirtualities': 'FINDVIRTUALITIES FINDMPIVIRTUALITIES GETTHETAM MAKEMASSLESS',
 'ColourBuilder': 'MAKESTRINGS MAKESTRINGS_VAC MAKESTRINGS_MINL ISPRIMSTRING ISSECSTRING ISPRIMHADRON',
 'ShowerEvolution': 'MAKECASCADE MAKEBRANCH MAKESPLITTING REJECTSPLITTING MAKEINSPLIT',
 'ScatteringEvolution': 'DOINSTATESCAT DOCOHSCATTERING DOFISTATESCAT GETNEWMASS GETPNORAD1 GETQVEC DOKINEMATICS GETDELTAT',
 'SplittingKernels': 'GETPROBA GETSUDAKOV GETINSUDAKOV DERIV GETSPLITI GETINSPLITI GETINSUDAFAST GETINSUDARED GETMASS GENERATEZ INTPQQ INTPGGLOW INTPGGHIGH INTPQGLOW INTPQGHIGH PQQ PGQ PGG PQG ALPHAS SPLITFNCINT INSUDAINT',
 'PartonicPdfKernels': 'GETPDF GETPDFXINT GETPDFXINTEXACT PDFINT',
 'ScatteringKernels': 'GETXSECINT GETSSCAT SCATPRIMFUNC GETT XSECINT',
 'Numerics': 'EI EIX EIXINT ODEINT RKSTEPPER RK4STEP POISSONIAN',
 'EventState': 'CLEANUP ISHADRON ISDIQUARK ISLEPTON ISPARTON ISQORG GETPOSITION COMPRESSEVENT COPYLINE',
 'OutputAdapter': 'PEVREC PUTPARTICLESONSHELL CONVERTTOHEPMC',
}
OWNERS = {name: group for group, names in GROUPS.items() for name in names.split()}


def active_lines(path):
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip() or raw[0] in 'cC*!' or raw.lstrip().startswith('!'):
            continue
        # Strip strings before inline comments, so exclamation marks in messages are safe.
        line = re.sub(r"'[^']*(?:''[^']*)*'|\"[^\"]*\"", "''", raw).split('!', 1)[0]
        yield number, line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--outdir', type=Path, required=True)
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    names = ['jewel-2.6.0.f', 'medium-simple.f', 'medium-vac.f', 'meix.f',
             'pythia6425mod-lhapdf6.f', 'subtraction.C', 'release_note-2.6.0.txt', 'Makefile']
    manifest, routines, sites, pythia_units = {}, [], [], {}
    for name in names:
        stock = args.source / (name + '.stock')
        path = stock if stock.exists() else args.source / name
        manifest[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'lines': len(path.read_text().splitlines()), 'read_name': path.name}
        if not name.endswith('.f'):
            continue
        current = None
        for line_no, line in active_lines(path):
            match = UNIT.match(line)
            if match:
                if current:
                    current['end_line'] = line_no - 1
                routine = match[2].upper()
                current = dict(source=name, routine=routine, kind=match[1].lower(),
                               start_line=line_no, end_line=manifest[name]['lines'],
                               cpp_component=('SimpleMedium' if name == 'medium-simple.f' else
                                              'VacuumMedium' if name == 'medium-vac.f' else
                                              OWNERS.get(routine, 'REVIEW')),
                               common_blocks=set(), direct_calls=set(), pythia_refs=set())
                if name.startswith('pythia'):
                    pythia_units[routine] = line_no
                else:
                    routines.append(current)
                continue
            if current is None:
                continue
            current['common_blocks'].update(x.upper() for x in COMMON.findall(line))
            if DECL.match(line):
                continue
            calls = {x.upper() for x in CALL.findall(line)}
            refs = {x.upper() for x in PYREF.findall(line)} | {x for x in calls if x.startswith('PY')}
            current['direct_calls'].update(calls)
            current['pythia_refs'].update(refs)
            if not name.startswith('pythia'):
                for ref in sorted(refs):
                    sites.append(dict(source=name, routine=current['routine'], line=line_no, pythia_symbol=ref))
    assert all(r['cpp_component'] != 'REVIEW' for r in routines), 'Assign newly found routines before using this index.'
    for row in routines:
        for key in ('common_blocks', 'direct_calls', 'pythia_refs'):
            row[key] = ';'.join(sorted(row[key]))
    for row in sites:
        row['definition_line'] = pythia_units.get(row['pythia_symbol'], '')
    for filename, rows in [('routines.csv', routines), ('pythia6-call-sites.csv', sites)]:
        with (args.outdir / filename).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (args.outdir / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{len(routines)} routines, {len(sites)} direct Pythia reference sites')
    print('Pythia symbols:', ', '.join(sorted({r['pythia_symbol'] for r in sites})))


if __name__ == '__main__':
    main()
