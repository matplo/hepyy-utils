#!/usr/bin/env python3
"""
patch_jewel_partons.py -- write JEWEL's outgoing hard partons into the HepMC output.

    python patch_jewel_partons.py jewel-2.6.0.f jewel-2.6.0-partons.f

Short HepMC output only (SHORTHEPMC T, the default). Per event it adds:
  * two particle records with HepMC status 23 (the Pythia 8 code for outgoing hard-process
    partons), barcodes 3 and 4, right after the two beam nucleons: the matrix-element partons
    (JEWEL's LME1, LME2) after PYTHIA's initial-state shower and before JEWEL's (vacuum or medium)
    final-state shower -- the same definition in jewel-*-vac and jewel-*-simple;
  * the hard-process pT, PARI(17), in the event-scale field of the E line (JEWEL writes 0 there).
Readers that select status 1, 3 and 4 (Rivet, hepmc2tables.py, hepyy-utils) are unaffected.
Nothing is written for e+e- (EEJJ) or Drell-Yan (PPDY) events.

The script refuses to patch if any expected source line is missing (another JEWEL version).
"""
import sys

DECL = """C--outgoing hard partons before the final-state shower (HepMC status 23)
      COMMON/HARDPART/PHARD(2,5),KHARD(2),NHARD
      DOUBLE PRECISION PHARD
      INTEGER KHARD,NHARD
"""

EDITS = [
    # declarations: genevent and CONVERTTOHEPMC (both have IMPLICIT NONE on the next line)
    ("\tsubroutine genevent(j,b1,b2)\n\timplicit none\n",
     "\tsubroutine genevent(j,b1,b2)\n\timplicit none\n" + DECL, 1),
    ("\tSUBROUTINE CONVERTTOHEPMC(J,EVNUM,PID,beam1,beam2)\n\tIMPLICIT NONE\n",
     "\tSUBROUTINE CONVERTTOHEPMC(J,EVNUM,PID,beam1,beam2)\n\tIMPLICIT NONE\n" + DECL, 1),
    # reset per event
    (" 99\t  CALL PYEVNT\n", " 99\t  CALL PYEVNT\n      NHARD=0\n", 1),
    # store the matrix-element partons once JEWEL has identified them
    ("\t  PID=K(LME1,2)\n",
     "\t  PID=K(LME1,2)\n"
     "C--store the outgoing hard partons before the final-state shower\n"
     "      NHARD=2\n"
     "      KHARD(1)=K(LME1,2)\n"
     "      KHARD(2)=K(LME2,2)\n"
     + "".join(f"      PHARD({i},{c})=P(LME{i},{c})\n" for i in (1, 2) for c in range(1, 6)), 1),
    # short output: count the two records in the vertex and write pT-hat in the E line
    ("\t  if(writedummies) NFIRST=NFIRST+nscatcen\n\n"
     "\t  WRITE(J,5000)'E ',EVNUM,-1,0.d0,0.d0,0.d0,0,0,NVERTEX,1,2,0,1,\n"
     "     &PARI(10)\n",
     "\t  if(writedummies) NFIRST=NFIRST+nscatcen\n"
     "      IF((NHARD.EQ.2).AND.(COLLIDER.NE.'EEJJ')) NFIRST=NFIRST+2\n\n"
     "      WRITE(J,5000)'E ',EVNUM,-1,PARI(17),0.d0,0.d0,0,0,NVERTEX,\n"
     "     &1,2,0,1,PARI(10)\n", 1),
]

# the two records go right after the beams of the short output (first occurrence only)
ANCHOR = "C--write out scattering centres\n\tif(writescatcen) then\n\t    do 133 i=1,nscatcen\n"
PARTONS = """C--write out the outgoing hard partons (status 23)
      IF((NHARD.EQ.2).AND.(COLLIDER.NE.'EEJJ'))THEN
        PBARCODE=PBARCODE+1
        WRITE(J,5500)'P ',PBARCODE,KHARD(1),PHARD(1,1),PHARD(1,2),
     &  PHARD(1,3),PHARD(1,4),PHARD(1,5),23,0,0,0,0
        PBARCODE=PBARCODE+1
        WRITE(J,5500)'P ',PBARCODE,KHARD(2),PHARD(2,1),PHARD(2,2),
     &  PHARD(2,3),PHARD(2,4),PHARD(2,5),23,0,0,0,0
      ENDIF
"""


def main(src, dst):
    text = open(src).read()
    if "COMMON/HARDPART/" in text:
        sys.exit(f"{src} is already patched")
    for old, new, count in EDITS:
        found = text.count(old)
        if found != count:
            sys.exit(f"expected {count} occurrence(s), found {found}: patch by hand\n{old}")
        text = text.replace(old, new)
    if text.count(ANCHOR) != 1:
        sys.exit("short-output scattering-centre block not found: patch by hand")
    text = text.replace(ANCHOR, PARTONS + ANCHOR)
    long_lines = [n for n, line in enumerate(text.splitlines(), 1)
                  if not line.startswith(("C", "c", "!", "*")) and len(line.expandtabs(8)) > 72
                  and ("HARD" in line or "PARI(17)" in line)]
    if long_lines:
        sys.exit(f"patched lines exceed column 72: {long_lines}")
    open(dst, "w").write(text)
    print(f"wrote {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
